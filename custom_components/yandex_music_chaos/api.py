from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    API_PREFIX,
    CONF_SOURCE_ENTITY,
    CONF_TARGET_ENTITIES,
    DATA_PLAY_KEY,
    DOMAIN,
)
from .yandex import YandexMusicError, YandexMusicService, normalize_track

_LOGGER = logging.getLogger(__name__)
_VIEWS_REGISTERED = f"{DOMAIN}_views_registered"


def _json(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def _entry(hass: HomeAssistant):
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _targets(hass: HomeAssistant, requested: Any = None) -> list[str]:
    values = requested
    if not isinstance(values, list):
        entry = _entry(hass)
        values = (entry.options or {}).get(CONF_TARGET_ENTITIES, []) if entry else []
    if not values:
        entry = _entry(hass)
        source = (entry.options or {}).get(CONF_SOURCE_ENTITY) if entry else None
        source = source or (entry.data or {}).get(CONF_SOURCE_ENTITY) if entry else source
        values = [source] if source else []
    valid = []
    for entity_id in values:
        entity_id = str(entity_id or "")
        if entity_id.startswith("media_player.") and entity_id not in valid:
            valid.append(entity_id)
    return valid


def _players(hass: HomeAssistant, service: YandexMusicService) -> list[dict[str, Any]]:
    entry = _entry(hass)
    selected = set((entry.options or {}).get(CONF_TARGET_ENTITIES, []) if entry else [])
    result = []
    station_ids = {service.source_entity}
    # Quasar keeps the actual station entities here, including renamed entities.
    station_data = hass.data.get("yandex_station", {})
    if isinstance(station_data, dict):
        for quasar in station_data.values():
            for speaker in getattr(quasar, "speakers", None) or []:
                entity = speaker.get("entity") if isinstance(speaker, dict) else None
                if entity and getattr(entity, "entity_id", None):
                    station_ids.add(entity.entity_id)
    for state in hass.states.async_all("media_player"):
        attrs = state.attributes
        result.append(
            {
                "entity_id": state.entity_id,
                "name": attrs.get("friendly_name", state.entity_id),
                "state": state.state,
                "source": state.entity_id == service.source_entity,
                "is_yandex_station": state.entity_id in station_ids or state.entity_id.startswith("media_player.yandex_station_"),
                "selected": state.entity_id in selected,
                "title": attrs.get("media_title"),
                "artist": attrs.get("media_artist") or attrs.get("media_artist_name"),
                "album": attrs.get("media_album_name"),
                "image": attrs.get("entity_picture") or attrs.get("media_image_url"),
                "volume": attrs.get("volume_level"),
                "muted": attrs.get("is_volume_muted"),
                "position": attrs.get("media_position"),
                "duration": attrs.get("media_duration"),
                "media_id": attrs.get("media_content_id"),
            }
        )
    return sorted(result, key=lambda row: (not row["source"], row["name"].lower()))


def _playback(service: YandexMusicService) -> dict[str, Any]:
    return {
        "queue": service.playback.queue,
        "index": service.playback.index,
        "track": (
            service.playback.queue[service.playback.index]
            if 0 <= service.playback.index < len(service.playback.queue)
            else None
        ),
    }


def _base_url(request: web.Request) -> str:
    marker = API_PREFIX
    path = request.path
    prefix = path.split(marker, 1)[0] if marker in path else ""
    return f"{request.scheme}://{request.host}{prefix}"


async def _call_media(
    hass: HomeAssistant,
    service: str,
    targets: list[str],
    data: dict[str, Any] | None = None,
) -> None:
    if not targets:
        raise YandexMusicError("Не выбрана ни одна колонка для воспроизведения")
    payload = {"entity_id": targets}
    payload.update(data or {})
    await hass.services.async_call("media_player", service, payload, blocking=True)


async def _play_current(
    request: web.Request,
    service: YandexMusicService,
    targets: list[str],
) -> dict[str, Any]:
    if not service.playback.queue or not (0 <= service.playback.index < len(service.playback.queue)):
        raise YandexMusicError("Очередь пуста")
    track = service.playback.queue[service.playback.index]
    track_id = str(track.get("id", ""))
    if not track_id:
        raise YandexMusicError("У текущего трека нет идентификатора")
    url = service.stream_url(track_id, _base_url(request))
    await _call_media(
        service.hass,
        "play_media",
        targets,
        {
            "media_content_id": url,
            "media_content_type": "music",
        },
    )
    return {"track": track, "index": service.playback.index, "targets": targets}


class _BaseView(HomeAssistantView):
    requires_auth = True

    @staticmethod
    def service(request: web.Request) -> YandexMusicService:
        return request.app["hass"].data[DOMAIN]

    @staticmethod
    def error(err: Exception) -> web.Response:
        if isinstance(err, YandexMusicError):
            _LOGGER.error("Yandex Music panel request failed: %s", err)
            return _json({"error": str(err), "code": "yandex_music"}, 502)
        _LOGGER.exception("Yandex Music panel request failed")
        return _json({"error": "Внутренняя ошибка Яндекс Музыки"}, 500)


class StatusView(_BaseView):
    url = f"{API_PREFIX}/status"
    name = f"api:{DOMAIN}:status"

    async def get(self, request: web.Request):
        service = self.service(request)
        try:
            account = await service.account()
            return _json({"authorized": True, "account": account, "players": _players(request.app["hass"], service), "playback": _playback(service)})
        except Exception as err:
            _LOGGER.error("Yandex Music status unavailable: %s", err)
            return _json({
                "authorized": False,
                "account": None,
                "players": _players(request.app["hass"], service),
                "playback": _playback(service),
                "error": str(err),
            })


class ConfigView(_BaseView):
    url = f"{API_PREFIX}/config"
    name = f"api:{DOMAIN}:config"

    async def get(self, request: web.Request):
        entry = _entry(request.app["hass"])
        return _json(
            {
                "source_entity": (entry.options or {}).get(CONF_SOURCE_ENTITY, entry.data.get(CONF_SOURCE_ENTITY)) if entry else "",
                "target_entities": (entry.options or {}).get(CONF_TARGET_ENTITIES, []) if entry else [],
            }
        )

    async def post(self, request: web.Request):
        hass = request.app["hass"]
        entry = _entry(hass)
        if entry is None:
            return _json({"error": "Интеграция ещё не настроена"}, 409)
        try:
            body = await request.json()
            targets = _targets(hass, body.get("target_entities"))
            options = dict(entry.options)
            options[CONF_TARGET_ENTITIES] = targets
            hass.config_entries.async_update_entry(entry, options=options)
            return _json({"ok": True, "target_entities": targets})
        except Exception as err:
            return self.error(err)


class PlayersView(_BaseView):
    url = f"{API_PREFIX}/players"
    name = f"api:{DOMAIN}:players"

    async def get(self, request: web.Request):
        service = self.service(request)
        return _json({"players": _players(request.app["hass"], service), "playback": _playback(service)})


class PlaylistsView(_BaseView):
    url = f"{API_PREFIX}/playlists"
    name = f"api:{DOMAIN}:playlists"

    async def get(self, request: web.Request):
        try:
            return _json({"playlists": await self.service(request).playlists()})
        except Exception as err:
            return self.error(err)


class PlaylistTracksView(_BaseView):
    url = f"{API_PREFIX}/playlists/{{uid}}/{{kind}}"
    name = f"api:{DOMAIN}:playlist"

    async def get(self, request: web.Request, uid: str, kind: str):
        try:
            tracks = await self.service(request).playlist_tracks(uid, kind)
            return _json({"tracks": tracks, "title": f"Плейлист {kind}"})
        except Exception as err:
            return self.error(err)


class LikesView(_BaseView):
    url = f"{API_PREFIX}/likes"
    name = f"api:{DOMAIN}:likes"

    async def get(self, request: web.Request):
        try:
            return _json({"tracks": await self.service(request).liked_tracks()})
        except Exception as err:
            return self.error(err)


class SearchView(_BaseView):
    url = f"{API_PREFIX}/search"
    name = f"api:{DOMAIN}:search"

    async def get(self, request: web.Request):
        try:
            text = (request.query.get("q") or "").strip()
            if not text:
                return _json({"tracks": [], "albums": [], "artists": [], "playlists": []})
            page = max(0, int(request.query.get("page", "0")))
            return _json(await self.service(request).search(text, page))
        except Exception as err:
            return self.error(err)


class WaveView(_BaseView):
    url = f"{API_PREFIX}/wave"
    name = f"api:{DOMAIN}:wave"

    async def get(self, request: web.Request):
        try:
            return _json({"tracks": await self.service(request).wave()})
        except Exception as err:
            return self.error(err)


class ChartView(_BaseView):
    url = f"{API_PREFIX}/chart"
    name = f"api:{DOMAIN}:chart"

    async def get(self, request: web.Request):
        try:
            return _json({"tracks": await self.service(request).chart()})
        except Exception as err:
            return self.error(err)


class RecommendationsView(_BaseView):
    url = f"{API_PREFIX}/recommendations"
    name = f"api:{DOMAIN}:recommendations"

    async def get(self, request: web.Request):
        try:
            return _json({"shelves": await self.service(request).recommendations()})
        except Exception as err:
            return self.error(err)


class PodcastsView(_BaseView):
    url = f"{API_PREFIX}/podcasts"
    name = f"api:{DOMAIN}:podcasts"

    async def get(self, request: web.Request):
        try:
            return _json(await self.service(request).podcasts())
        except Exception as err:
            return self.error(err)


class AlbumView(_BaseView):
    url = f"{API_PREFIX}/albums/{{album_id}}"
    name = f"api:{DOMAIN}:album"

    async def get(self, request: web.Request, album_id: str):
        try:
            return _json(await self.service(request).album_tracks(album_id))
        except Exception as err:
            return self.error(err)


class AudiobooksView(_BaseView):
    url = f"{API_PREFIX}/audiobooks"
    name = f"api:{DOMAIN}:audiobooks"

    async def get(self, request: web.Request):
        try:
            page = max(0, min(500, int(request.query.get("page", 0))))
            return _json(await self.service(request).audiobooks(request.query.get("q", ""), page))
        except ValueError:
            return _json({"error": "Некорректный номер страницы"}, 400)
        except Exception as err:
            return self.error(err)


class PlayView(_BaseView):
    url = f"{API_PREFIX}/play"
    name = f"api:{DOMAIN}:play"

    async def post(self, request: web.Request):
        service = self.service(request)
        try:
            body = await request.json()
            raw_queue = body.get("queue") or []
            queue = [track for track in (normalize_track(item) for item in raw_queue) if track]
            track = normalize_track(body.get("track"))
            if track and not queue:
                queue = [track]
            if not queue:
                raise YandexMusicError("Пустая очередь")
            selected_id = str((track or {}).get("id", ""))
            index = next((i for i, row in enumerate(queue) if row["id"] == selected_id), 0)
            service.playback.queue = queue
            service.playback.index = int(body.get("index", index))
            service.playback.index = max(0, min(service.playback.index, len(queue) - 1))
            result = await _play_current(request, service, _targets(request.app["hass"], body.get("targets")))
            return _json(result)
        except Exception as err:
            return self.error(err)


class CommandView(_BaseView):
    url = f"{API_PREFIX}/command"
    name = f"api:{DOMAIN}:command"

    async def post(self, request: web.Request):
        service = self.service(request)
        hass = request.app["hass"]
        try:
            body = await request.json()
            action = str(body.get("action", ""))
            targets = _targets(hass, body.get("targets"))
            if action in {"next", "previous"} and service.playback.queue:
                delta = 1 if action == "next" else -1
                service.playback.index = (service.playback.index + delta) % len(service.playback.queue)
                return _json(await _play_current(request, service, targets))
            if action in {"next", "previous"}:
                await _call_media(hass, "media_next_track" if action == "next" else "media_previous_track", targets)
                return _json({"ok": True, "action": action, "players": _players(hass, service)})
            allowed = {
                "play": "media_play",
                "pause": "media_pause",
                "stop": "media_stop",
                "toggle": "media_play_pause",
                "volume_up": "volume_up",
                "volume_down": "volume_down",
            }
            if action == "volume_set":
                level = max(0.0, min(1.0, float(body.get("level", 0.5))))
                await _call_media(hass, "volume_set", targets, {"volume_level": level})
            elif action == "seek":
                position = max(0.0, float(body.get("position", 0)))
                await _call_media(hass, "media_seek", targets, {"seek_position": position})
            elif action == "mute":
                await _call_media(hass, "volume_mute", targets, {"is_volume_muted": bool(body.get("muted", True))})
            elif action in allowed:
                await _call_media(hass, allowed[action], targets)
            else:
                raise YandexMusicError(f"Неизвестная команда: {action}")
            return _json({"ok": True, "action": action, "players": _players(hass, service)})
        except Exception as err:
            return self.error(err)


class LikeView(_BaseView):
    url = f"{API_PREFIX}/like"
    name = f"api:{DOMAIN}:like"

    async def post(self, request: web.Request):
        try:
            body = await request.json()
            await self.service(request).set_like(str(body.get("track_id", "")), bool(body.get("liked", True)))
            return _json({"ok": True})
        except Exception as err:
            return self.error(err)


class StreamView(HomeAssistantView):
    url = f"{API_PREFIX}/stream/{{track_id}}"
    name = f"api:{DOMAIN}:stream"
    requires_auth = False

    async def get(self, request: web.Request, track_id: str):
        hass = request.app["hass"]
        service = hass.data.get(DOMAIN)
        key = hass.data.get(DATA_PLAY_KEY)
        if not service or not key or request.query.get("key") != key:
            return web.Response(status=401, text="invalid playback key")
        try:
            direct = await service.direct_url(track_id)
            raise web.HTTPFound(direct)
        except web.HTTPException:
            raise
        except Exception as err:
            _LOGGER.warning("Could not resolve stream %s: %s", track_id, err)
            return web.Response(status=404, text="stream unavailable")


def register_views(hass: HomeAssistant, service: YandexMusicService) -> None:
    if hass.data.get(_VIEWS_REGISTERED):
        hass.data[DOMAIN] = service
        return
    for view in (
        StatusView,
        ConfigView,
        PlayersView,
        PlaylistsView,
        PlaylistTracksView,
        LikesView,
        SearchView,
        WaveView,
        ChartView,
        RecommendationsView,
        PodcastsView,
        AlbumView,
        AudiobooksView,
        PlayView,
        CommandView,
        LikeView,
        StreamView,
    ):
        hass.http.register_view(view())
    hass.data[_VIEWS_REGISTERED] = True
    hass.data[DOMAIN] = service
