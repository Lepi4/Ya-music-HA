"""Opt-in direct receivers. Station clocks never advance an external queue."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address
import time
from types import SimpleNamespace
from xml.etree import ElementTree

from .radio import position
from .yandex import YandexMusicError


class OutputRequestError(YandexMusicError):
    """An unavailable or conflicting output, rather than a Yandex outage."""

    status_code = 409


@dataclass
class Output:
    station: str
    source: str
    entity_id: str
    tracks: list[dict] = field(default_factory=list)
    index: int = -1
    radio: bool = False
    url: str = ""
    observed: bool = False
    started_at: float = 0
    active: bool = False
    closing: bool = False
    error: str | None = None
    transport_state: object | None = None

    @property
    def current(self):
        return self.tracks[self.index] if 0 <= self.index < len(self.tracks) else None


class DirectOutputs:
    def __init__(self, service):
        self.service = service
        self.hass = service.hass
        self.routes: dict[str, Output] = {}
        self._locks = {}
        self._closed = False
        self._polling_heos = False

    def receiver_entity(self, entity_id):
        component = self.hass.data.get("entity_components", {}).get("media_player")
        return next((e for e in getattr(component, "entities", []) if e.entity_id == entity_id), None)

    def is_heos(self, entity_id):
        entity = self.receiver_entity(entity_id)
        return getattr(getattr(entity, "platform", None), "platform_name", "") == "heos"

    def heos_leader(self, entity_id):
        state = self.hass.states.get(entity_id)
        members = state.attributes.get("group_members") if state else None
        leader = members[0] if members else entity_id
        return leader if self.is_heos(leader) else entity_id

    async def heos_state(self, route):
        """HEOS reports queue slot IDs, not URLs; verify the leader's real URI."""
        from aiohttp import ClientTimeout
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        state = self.hass.states.get(route.entity_id)
        if not state or state.state in ("unknown", "unavailable"):
            return state
        leader = self.receiver_entity(self.heos_leader(route.entity_id))
        # HA's HEOS entity wraps a pyheos player. Read its discovered address;
        # do not store addresses or create a second HEOS control connection.
        address = ip_address(str(getattr(getattr(leader, "_player", None), "ip_address", "")))
        host = f"[{address}]" if address.version == 6 else str(address)
        service = "urn:schemas-upnp-org:service:AVTransport:1"
        session = async_get_clientsession(self.hass)

        async def read(action):
            body = ('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
                    '<s:Body><u:' + action + ' xmlns:u="' + service + '">'
                    '<InstanceID>0</InstanceID></u:' + action + '></s:Body></s:Envelope>')
            async with session.post(
                f"http://{host}:60006/upnp/control/renderer_dvc/AVTransport",
                data=body, headers={"Content-Type": "text/xml; charset=utf-8",
                                   "SOAPAction": f'"{service}#{action}"'},
                timeout=ClientTimeout(total=2),
            ) as response:
                response.raise_for_status()
                document = ElementTree.fromstring(await response.read())
            return {node.tag.rsplit("}", 1)[-1]: node.text for node in document.iter()}

        values, transport = await asyncio.gather(read("GetPositionInfo"), read("GetTransportInfo"))

        def seconds(text):
            try:
                h, m, s = map(float, (text or "").split(":"))
                return h * 3600 + m * 60 + s
            except ValueError:
                return None

        attrs = {**state.attributes, "media_content_id": values.get("TrackURI") or "",
                 "media_position": seconds(values.get("RelTime")),
                 "media_duration": seconds(values.get("TrackDuration")),
                 "media_position_updated_at": datetime.now(timezone.utc)}
        actual_state = {"PLAYING": "playing", "PAUSED_PLAYBACK": "paused",
                        "STOPPED": "idle", "NO_MEDIA_PRESENT": "idle",
                        "TRANSITIONING": "buffering"}.get(transport.get("CurrentTransportState"), state.state)
        return SimpleNamespace(state=actual_state, attributes=attrs)

    async def poll_heos(self, _now=None):
        if self._closed or self._polling_heos:
            return
        self._polling_heos = True
        try:
            for route in list(self.routes.values()):
                if route.closing or not self.is_heos(route.entity_id):
                    continue
                url = route.url
                try:
                    state = await self.heos_state(route)
                except Exception:
                    route.transport_state = None
                    continue
                if self._closed or self.routes.get(route.station) is not route or route.url != url:
                    continue
                if (state and state.state in ("playing", "buffering") and route.observed
                        and not state.attributes.get("media_content_id")):
                    # HEOS briefly empties its URI before reporting idle at EOF.
                    # Keep the last verified position to recognize that EOF.
                    continue
                old, route.transport_state = route.transport_state, state
                await self.handle_event(SimpleNamespace(data={"entity_id": route.entity_id,
                    "old_state": old, "new_state": state, "verified_transport": True}))
        finally:
            self._polling_heos = False

    def lock(self, station):
        return self._locks.setdefault(station, asyncio.Lock())

    def station_entity(self, entity_id):
        component = self.hass.data.get("entity_components", {}).get("media_player")
        entity = next((e for e in getattr(component, "entities", []) if e.entity_id == entity_id), None)
        if entity is None or not isinstance(getattr(entity, "sync_sources", None), dict):
            raise OutputRequestError("Эта Станция не предоставляет внешние источники YandexStation")
        return entity

    def choices(self, station):
        entity = self.station_entity(station)
        component = self.hass.data.get("entity_components", {}).get("media_player")
        entities = {e.entity_id: e for e in getattr(component, "entities", [])}
        choices = {name: {"source": name, "entity_id": item["entity_id"]}
                   for name, item in entity.sync_sources.items() if item.get("entity_id")}
        # Native source lists are captured by YandexStation once at startup.
        # Receivers may arrive later; expose them for direct playback.
        for ident, receiver in entities.items():
            platform = getattr(getattr(receiver, "platform", None), "platform_name", "")
            if platform in ("cast", "dlna_dmr", "heos") and ident not in {c["entity_id"] for c in choices.values()}:
                choices[ident] = {"source": ident, "entity_id": ident}
        return [choice for choice in choices.values()
                if getattr(getattr(entities.get(choice["entity_id"]), "platform", None), "platform_name", "") != "androidtv_remote"]

    async def call(self, action, target, **data):
        await self.hass.services.async_call("media_player", action, {"entity_id": [target], **data}, blocking=True)

    def matches(self, route, state):
        if self.is_heos(route.entity_id) and state is self.hass.states.get(route.entity_id):
            state = route.transport_state
        return bool(state and route.url and str(state.attributes.get("media_content_id") or "") == route.url)

    async def select(self, station, source, direct):
        async with self.lock(station):
            entity = self.station_entity(station)
            sources = getattr(entity, "source_list", None) or []
            receivers = {choice["source"]: choice["entity_id"] for choice in self.choices(station)}
            if source not in sources and not (direct and source in receivers):
                raise OutputRequestError("Источник отсутствует в списке выбранной Станции")
            current = self.routes.get(station)
            if direct and source in receivers:
                receiver = receivers[source]
                state = self.hass.states.get(receiver)
                if not state or state.state in ("unknown", "unavailable"):
                    raise OutputRequestError("Внешний плеер недоступен")
                if receiver == station or any(r.entity_id == receiver and s != station for s, r in self.routes.items()):
                    raise OutputRequestError("Этот внешний плеер уже выбран у другой Станции")
                if current and current.entity_id == receiver:
                    self.verify(current)
                    return
                station_state = self.hass.states.get(station)
                if state.state in ("playing", "buffering") and not (current and self.matches(current, state)):
                    raise OutputRequestError("На внешнем плеере уже играет другой контент. Сначала остановите его")
                # Selecting an output is an explicit request to leave the
                # Station. Validate the receiver first, then pause through the
                # public service before disabling native mirroring. The output
                # owns its next track and clock; no Station timer drives it.
                if station_state and station_state.state in ("playing", "buffering"):
                    await self.call("media_pause", station)
                await self.release(station, stop=True)
                await self.service.radio.control(station, "detach")
                # Public source service disables YandexStation's native mirroring.
                # Do not monkey-patch the dependency or change its global config.
                from custom_components.yandex_station.core.yandex_station import SOURCE_STATION
                await self.call("select_source", station, source=SOURCE_STATION)
                if entity.sync_enabled:
                    raise OutputRequestError("YandexStation не отключила синхронизацию; прямой запуск отменён")
                self.routes[station] = Output(station, source, receiver)
            else:
                if direct and source in entity.sync_sources:
                    raise OutputRequestError("Выберите медиаполучатель Cast/DLNA/HEOS, а не пульт Android TV")
                await self.release(station, stop=True)
                await self.call("select_source", station, source=source)

    async def release(self, station, stop=False):
        route = self.routes.get(station)
        if not route:
            return
        route.active = False
        route.closing = True
        await self.service.radio.control(station, "detach")
        self.routes.pop(station, None)
        if stop and self.matches(route, self.hass.states.get(route.entity_id)):
            await self.call("media_stop", route.entity_id)

    def verify(self, route):
        if self._closed or route.closing or self.routes.get(route.station) is not route:
            raise YandexMusicError("Прямой source больше не выбран")
        entity = self.station_entity(route.station)
        if entity.sync_enabled:
            route.active = False
            raise YandexMusicError("Включена штатная синхронизация YandexStation. Выберите прямой source заново")

    async def play(self, route, tracks, index, radio=False):
        self.verify(route)
        # Resolve before replacing the existing queue; failed network requests
        # leave the current stream alone. MP3 is the broadly supported fallback.
        track = tracks[index]
        url = await self.service.direct_url(str(track["id"]), prefer_mp3=True)
        self.verify(route)
        previous = (route.tracks, route.index, route.radio, route.url, route.observed, route.active, route.transport_state)
        route.tracks, route.index, route.radio, route.url = tracks, index, radio, url
        route.observed, route.active, route.error = False, True, None
        route.transport_state = None
        route.started_at = time.monotonic()
        try:
            if self.is_heos(route.entity_id):
                # HEOS play_url keeps its old queue and can jump into stale
                # streams at EOF. This integration owns the selected playlist;
                # replace the receiver queue before sending each resolved URL.
                await self.call("clear_playlist", self.heos_leader(route.entity_id))
            await self.call("play_media", route.entity_id, media_content_id=url, media_content_type="music",
                            extra={"title": track.get("title", ""), "thumb": track.get("cover", ""),
                                   "metadata": {"metadataType": 3, "title": track.get("title", ""),
                                                "artist": track.get("artists", "")}})
        except Exception:
            route.tracks, route.index, route.radio, route.url, route.observed, route.active, route.transport_state = previous
            route.error = "Не удалось отправить трек внешнему плееру"
            raise

    async def playlist(self, station, tracks, index):
        async with self.lock(station):
            await self.service.radio.control(station, "detach")
            route = self.routes.get(station)
            if not route:
                raise YandexMusicError("Прямой внешний source не выбран")
            await self.play(route, tracks, index)

    async def play_radio(self, station, track):
        route = self.routes.get(station)
        if route is None:
            return False
        await self.play(route, [track], 0, radio=True)
        return True

    async def start_radio(self, station, seed):
        async with self.lock(station):
            route = self.routes[station]
            active = route.active
            route.active = False
            try:
                await self.service.radio.start(station, seed)
            except Exception:
                route.active = active
                raise

    async def command(self, station, action, body):
        route = self.routes.get(station)
        if not route:
            raise YandexMusicError("Прямой внешний source не выбран")
        if route.radio and action in ("next", "previous", "stop"):
            if action == "stop":
                route.active = False
                await self.service.radio.control(station, "detach")
                await self.call("media_stop", route.entity_id)
            else:
                await self.service.radio.control(station, action)
            return
        async with self.lock(station):
            if action in ("play", "toggle") and not route.active and route.current:
                await self.play(route, route.tracks, route.index)
                return
            if action in ("next", "previous"):
                target = route.index + (1 if action == "next" else -1)
                if not 0 <= target < len(route.tracks):
                    return
                await self.play(route, route.tracks, target)
                return
            if action == "stop":
                route.active = False
            actions = {"play":"media_play", "pause":"media_pause", "toggle":"media_play_pause",
                       "stop":"media_stop", "seek":"media_seek", "volume_set":"volume_set", "mute":"volume_mute"}
            if action not in actions:
                raise YandexMusicError("Неизвестная команда внешнего плеера")
            data = {}
            if action == "seek":
                data["seek_position"] = max(0, float(body.get("position", 0)))
            elif action == "volume_set":
                data["volume_level"] = max(0, min(1, float(body.get("level", .5))))
            elif action == "mute":
                data["is_volume_muted"] = bool(body.get("muted", True))
            await self.call(actions[action], route.entity_id, **data)

    def project(self, station, row):
        route = self.routes.get(station)
        if not route:
            return row
        state = self.hass.states.get(route.entity_id)
        owned = self.matches(route, state)
        if owned and self.is_heos(route.entity_id):
            state = route.transport_state
        attrs = state.attributes if state else {}
        pending = route.active and not route.observed and time.monotonic() - route.started_at <= 30
        track = route.current if owned or pending else None
        error = route.error
        if route.active and not route.observed and time.monotonic() - route.started_at > 30:
            error = error or "Получатель не подтвердил поток. Проверьте поддержку воспроизведения и состояние устройства"
        return {**row, "state": "buffering" if pending and not owned else state.state if state else "unavailable", "direct_output": True,
                "transport_polling": self.is_heos(route.entity_id),
                "output_entity": route.entity_id, "input_source": route.source,
                "source_list": list(dict.fromkeys([*getattr(self.station_entity(station), "source_list", []), route.source])),
                "title": (track or {}).get("title") or attrs.get("media_title"),
                "artist": (track or {}).get("artists") or attrs.get("media_artist"),
                "image": (track or {}).get("cover") or attrs.get("entity_picture"),
                "media_id": str(track["id"]) if track and owned else "",
                "position": 0 if pending and not owned else position(state) if state else None,
                "position_updated_at": datetime.now(timezone.utc).isoformat(),
                "duration": (track or {}).get("duration") if pending and not owned else attrs.get("media_duration") or (track or {}).get("duration"),
                "volume": attrs.get("volume_level"), "muted": attrs.get("is_volume_muted"),
                "output_error": error}

    async def handle_event(self, event):
        for station, route in list(self.routes.items()):
            if event.data.get("entity_id") != route.entity_id or not route.active:
                continue
            if self.is_heos(route.entity_id) and not event.data.get("verified_transport"):
                continue
            # Receiver events only. The Station may finish minutes earlier or
            # later; its progress/paused state has no authority here.
            old, new = event.data.get("old_state"), event.data.get("new_state")
            if not new or new.state in ("unknown", "unavailable", "buffering"):
                continue
            if self.matches(route, new) and new.state in ("playing", "paused"):
                if new.state == "playing":
                    route.observed = True
                if route.radio:
                    await self.radio_event(route, old, new)
                return
            if not route.observed:
                return  # Startup idle/old-track events are not EOF.
            if old and not self.matches(route, old):
                return  # Late event from a previous track.
            if new.state in ("idle", "off") or new.attributes.get("media_content_id"):
                duration = float((route.current or {}).get("duration") or (old.attributes.get("media_duration") if old else 0) or 0)
                ended = new.state == "idle" and old and old.state == "playing" and self.matches(route, old)
                # Avoid treating an early external stop/replacement as natural
                # completion. Never advance merely because a duration elapsed.
                ended = ended and duration > 0 and position(old) >= duration - 3
                if not ended:
                    route.active = False
                    if route.radio:
                        await self.service.radio.control(station, "detach")
                    return
                if route.radio:
                    await self.radio_event(route, old, new)
                else:
                    async with self.lock(station):
                        if self.routes.get(station) is route and route.active:
                            if route.index + 1 >= len(route.tracks):
                                route.active = False
                            else:
                                try:
                                    await self.play(route, route.tracks, route.index + 1)
                                except Exception:
                                    route.active = False
                                    route.error = "Не удалось продолжить очередь внешнего плеера"

    async def radio_event(self, route, old, new):
        def convert(state):
            if state is None:
                return None
            attrs = dict(state.attributes)
            attrs["media_content_id"] = str(route.current["id"]) if self.matches(route, state) else ""
            attrs.setdefault("media_duration", (route.current or {}).get("duration"))
            return SimpleNamespace(state=state.state, attributes=attrs)
        await self.service.radio.handle_event(SimpleNamespace(data={
            "entity_id": route.station, "old_state": convert(old), "new_state": convert(new), "direct_output": True}))

    def close(self):
        self._closed = True
        self.routes.clear()
