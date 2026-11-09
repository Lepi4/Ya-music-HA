"""Rotor queues owned by HA, independently of the browser and other speakers."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .yandex import YandexMusicError

_LOGGER = logging.getLogger(__name__)


def track_id(value: Any) -> str:
    """HA may expose a plain ID, album-qualified ID, or a Music track URL."""
    import re
    match = re.search(r"(?:^|/track/)(\d+)(?=$|[?:/])", str(value or ""))
    return match[1] if match else ""


def position(state: Any) -> float:
    attrs = getattr(state, "attributes", {})
    value = float(attrs.get("media_position") or 0)
    updated = attrs.get("media_position_updated_at")
    if state and state.state == "playing" and updated:
        try:
            stamp = datetime.fromisoformat(updated) if isinstance(updated, str) else updated
            value += max(0, (datetime.now(timezone.utc) - stamp).total_seconds())
        except (ValueError, TypeError):
            pass
    return value


@dataclass
class RadioSession:
    entity_id: str
    station: str
    tracks: list[dict] = field(default_factory=list)
    index: int = -1
    batch: str | None = None
    active: bool = True
    awaiting: bool = False
    observed: bool = False
    finished: bool = False
    waiting: bool = False
    retries: int = 0
    error: str | None = None
    feedback_error: str | None = None
    requested_at: float = 0

    @property
    def current(self) -> dict | None:
        return self.tracks[self.index] if 0 <= self.index < len(self.tracks) else None


class RadioController:
    def __init__(self, service):
        self.service = service
        self.hass = service.hass
        self.sessions: dict[str, RadioSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._closed = False

    def lock(self, entity_id):
        return self._locks.setdefault(entity_id, asyncio.Lock())

    def snapshot(self) -> dict:
        return {key: {"station": s.station, "tracks": [{k: v for k, v in t.items() if k != "_batch"} for t in s.tracks],
                      "index": s.index, "active": s.active, "waiting": s.waiting,
                      "error": s.error, "feedback_error": s.feedback_error}
                for key, s in self.sessions.items()}

    async def feedback(self, s, kind, seconds=0):
        current = s.current
        try:
            await self.service.wave_feedback(s.station, kind, current.get("id") if current else None,
                                             current.get("_batch") if current else s.batch, seconds)
            s.feedback_error = None
        except Exception:
            # An analytics failure must not stop the stream or masquerade as success.
            s.feedback_error = "Не удалось передать событие прослушивания Яндексу"
            _LOGGER.warning("Rotor feedback failed for %s (%s)", s.entity_id, kind)

    async def replenish(self, s):
        cursor = s.current["id"] if s.current else None
        result = await self.service.wave_batch(s.station, cursor)
        s.batch = result.get("batch")
        known = {t["id"] for t in s.tracks}
        for track in result["tracks"]:
            if track["id"] not in known and track.get("available", True):
                s.tracks.append({**track, "_batch": s.batch})
                known.add(track["id"])

    async def start(self, entity_id: str, station: str):
        async with self.lock(entity_id):
            previous = self.sessions.get(entity_id)
            s = RadioSession(entity_id, station)
            try:
                await self.replenish(s)
                if not s.tracks:
                    raise YandexMusicError("Яндекс Музыка не вернула доступные треки волны")
                if previous:
                    await self.finish(previous, "skip")
                    previous.active = False
                self.sessions[entity_id] = s
                await self.feedback(s, "radioStarted")
                await self.play(s, 0)
            except Exception:
                s.active = False
                s.error = "Не удалось запустить волну"
                raise

    async def play(self, s, index):
        if self._closed or not s.active:
            raise YandexMusicError("Сеанс волны завершён")
        old_index = s.index
        s.index = index
        s.awaiting = True
        s.observed = False
        s.finished = False
        s.waiting = False
        s.requested_at = time.monotonic()
        try:
            # HA owns the sequence; the station only plays this Yandex track.
            await self.hass.services.async_call("media_player", "play_media", {
                "entity_id": [s.entity_id], "media_content_type": "track",
                "media_content_id": str(s.current["id"]),
            }, blocking=True)
        except Exception:
            s.index = old_index
            s.awaiting = False
            s.finished = True
            s.waiting = True
            raise
        s.error = None
        s.retries = 0
        # Start feedback is sent on an actual matching playing state, not the request.

    async def finish(self, s, kind, played_seconds=None):
        if s.current and s.observed and not s.finished:
            s.finished = True
            state = self.hass.states.get(s.entity_id)
            seconds = played_seconds if played_seconds is not None else position(state) if state and track_id(state.attributes.get("media_content_id")) == s.current["id"] else 0
            await self.feedback(s, kind, seconds)

    async def advance(self, s, finished=False, index=None, played_seconds=None):
        await self.finish(s, "trackFinished" if finished else "skip", played_seconds)
        target = s.index + 1 if index is None else index
        if target >= len(s.tracks):
            # Rotor responses overlap; bound retries and never wrap to the first batch.
            for _ in range(3):
                await self.replenish(s)
                if target < len(s.tracks):
                    break
            else:
                s.waiting = True
                raise YandexMusicError("Яндекс пока не вернул продолжение волны; повторите «Следующий трек»")
        await self.play(s, max(0, target))
        if s.index > 100:
            del s.tracks[:s.index - 50]
            s.index = 50

    async def control(self, entity_id, action, index=None):
        async with self.lock(entity_id):
            s = self.sessions.get(entity_id)
            if not s:
                return False
            if action in ("stop", "detach"):
                await self.finish(s, "skip")
                s.active = False
                del self.sessions[entity_id]
                if action == "stop":
                    await self.hass.services.async_call("media_player", "media_stop", {"entity_id": [entity_id]}, blocking=True)
                return True
            if not s.active:
                return False
            if action not in ("next", "previous", "select"):
                raise YandexMusicError("Неизвестная команда волны")
            target = max(0, s.index - 1) if action == "previous" else index if action == "select" else None
            if target is not None and not 0 <= target < len(s.tracks):
                raise YandexMusicError("Трек отсутствует в очереди волны")
            try:
                await self.advance(s, index=target)
            except Exception as err:
                s.error = str(err) if isinstance(err, YandexMusicError) else "Не удалось продолжить волну"
                raise
            return True

    async def handle_event(self, event):
        entity_id = event.data.get("entity_id")
        if entity_id not in self.sessions:
            return
        async with self.lock(entity_id):
            s = self.sessions.get(entity_id)
            if not s or not s.active:
                return
            old, new = event.data.get("old_state"), event.data.get("new_state")
            if not new or new.state in ("unknown", "unavailable"):
                return
            expected = s.current["id"] if s.current else ""
            actual = track_id(new.attributes.get("media_content_id"))
            if s.waiting and new.state in ("playing", "paused"):
                # Someone resumed or replaced playback while an upstream retry waited.
                s.active = False
                self.sessions.pop(entity_id, None)
                return
            duration = float((old.attributes.get("media_duration") if old else None) or (s.current or {}).get("duration") or 0)
            if (s.observed and old and old.state == "playing" and new.state == "paused"
                    and actual == expected and duration > 0
                    and float(new.attributes.get("media_position") or 0) >= duration - .25):
                try:
                    await self.advance(s, finished=True, played_seconds=duration)
                except Exception:
                    s.waiting = True
                    s.error = "Не удалось продолжить волну; повторяем загрузку"
                return
            if actual == expected and new.state in ("playing", "paused", "buffering"):
                if new.state == "playing" and not s.observed:
                    s.awaiting = False
                    s.observed = True
                    await self.feedback(s, "trackStarted")
                    # Feed the cursor after actual playback has begun, as in Lampa.
                    if len(s.tracks) - s.index <= 2:
                        try:
                            await self.replenish(s)
                        except Exception:
                            s.error = "Не удалось подгрузить следующие треки; повторим в конце очереди"
                return
            if s.awaiting or s.waiting or not s.observed:
                return
            if old and track_id(old.attributes.get("media_content_id")) not in ("", expected):
                return  # A delayed event for the previous queue item cannot end this one.
            old_matches = old and track_id(old.attributes.get("media_content_id")) == expected
            at_end = old_matches and duration > 0 and position(old) >= duration - 3
            if at_end and old.state == "playing" and (new.state in ("idle", "off") or (actual and actual != expected)):
                try:
                    await self.advance(s, finished=True, played_seconds=min(position(old), duration))
                except Exception:
                    s.waiting = True
                    s.error = "Не удалось продолжить волну; повторяем загрузку"
                    _LOGGER.warning("Rotor continuation failed for %s", entity_id)
            elif new.state in ("idle", "off") or (actual and actual != expected):
                # External playback/stop takes ownership; never fight another controller.
                await self.finish(s, "skip")
                s.active = False
                self.sessions.pop(entity_id, None)

    async def retry_waiting(self, _now=None):
        for entity_id in list(self.sessions):
            async with self.lock(entity_id):
                s = self.sessions.get(entity_id)
                if s and s.awaiting and time.monotonic() - s.requested_at > 30:
                    s.awaiting = False
                    s.error = "Колонка не подтвердила воспроизведение. Проверьте подключение и повторите запуск."
                if not s or not s.active or not s.waiting or s.retries >= 3:
                    continue
                s.retries += 1
                try:
                    await self.advance(s, finished=True)
                except Exception:
                    s.error = "Продолжение волны недоступно. Нажмите «Следующий трек», чтобы повторить."

    def close(self):
        self._closed = True
        for s in self.sessions.values():
            s.active = False
        self.sessions.clear()
