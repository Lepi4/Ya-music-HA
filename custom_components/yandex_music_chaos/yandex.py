from __future__ import annotations

import asyncio
import gc
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Iterable

import aiohttp
from homeassistant.core import HomeAssistant
from yandex_music import Client

from .const import API_PREFIX, DATA_PLAY_KEY

_LOGGER = logging.getLogger(__name__)


class YandexMusicError(RuntimeError):
    pass


async def music_token_from_x_token(x_token: str) -> str:
    payload = {
        "client_secret": "53bc75238f0c4d08a118e51fe9203300",
        "client_id": "23cabbbdc6cd418abb4b39c32c41195d",
        "grant_type": "x-token",
        "access_token": x_token,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://oauth.mobile.yandex.net/1/token", data=payload
        ) as response:
            data = await response.json(content_type=None)
    token = data.get("access_token")
    if not token:
        raise YandexMusicError("Yandex Station did not return a music token")
    return str(token)


def _find_token(value: Any, key: str, seen: set[int] | None = None) -> str | None:
    """Find a token in the varying yandex_station hass.data layouts."""
    if value is None:
        return None
    seen = seen or set()
    if isinstance(value, str):
        return value if key == "_value" else None
    if id(value) in seen:
        return None
    seen.add(id(value))
    if isinstance(value, dict):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
        for child in value.values():
            found = _find_token(child, key, seen)
            if found:
                return found
        return None
    for attr in (key,):
        try:
            candidate = getattr(value, attr, None)
        except Exception:
            candidate = None
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


async def resolve_music_token(hass: HomeAssistant, source_entity: str) -> str:
    """Resolve the music token from the configured Yandex Station integration."""
    try:
        from custom_components.yandex_station.media_player import YandexStation
    except ImportError:
        YandexStation = None

    if YandexStation is not None:
        try:
            for entity in gc.get_objects():
                if not isinstance(entity, YandexStation):
                    continue
                if source_entity and getattr(entity, "entity_id", "") != source_entity:
                    continue
                session = getattr(getattr(entity, "quasar", None), "session", None)
                if session is None:
                    continue
                token = getattr(session, "music_token", None)
                if token:
                    return str(token)
                x_token = getattr(session, "x_token", None)
                if x_token:
                    token = await music_token_from_x_token(str(x_token))
                    try:
                        session.music_token = token
                    except Exception:
                        pass
                    return token
        except Exception as err:
            _LOGGER.debug("Could not inspect Yandex Station entity: %s", err)

    station_data = hass.data.get("yandex_station")
    for key in ("music_token", "token"):
        token = _find_token(station_data, key)
        if token:
            return token
    x_token = _find_token(station_data, "x_token")
    if x_token:
        return await music_token_from_x_token(x_token)

    raise YandexMusicError(
        "Не удалось получить music token из Yandex Station. "
        "Проверьте авторизацию колонки и выбранную сущность."
    )


def _artists(track: Any) -> str:
    return ", ".join(
        str(getattr(artist, "name", ""))
        for artist in (getattr(track, "artists", None) or [])
        if getattr(artist, "name", None)
    )


def _cover(track: Any, size: str = "400x400") -> str | None:
    if isinstance(track, dict):
        value = track.get("cover_uri") or track.get("uri") or track.get("og_image")
    else:
        value = getattr(track, "cover_uri", None) or getattr(track, "uri", None) or getattr(track, "og_image", None)
    if not value:
        return None
    value = str(value).replace("%%", size)
    return value if value.startswith("http") else "https://" + value


def normalize_track(track: Any) -> dict[str, Any] | None:
    if track is None:
        return None
    if isinstance(track, dict):
        track_id = track.get("id")
        if not track_id:
            return None
        return {
            "id": str(track_id),
            "title": str(track.get("title", "")),
            "version": str(track.get("version", "") or ""),
            "artists": str(track.get("artists", "")),
            "album": str(track.get("album", "") or ""),
            "album_id": str(track.get("album_id", "") or ""),
            "cover": track.get("cover"),
            "duration": int(track.get("duration", 0) or 0),
            "available": bool(track.get("available", True)),
        }
    track = getattr(track, "track", track)
    track_id = getattr(track, "id", None)
    if track_id is None:
        return None
    albums = getattr(track, "albums", None) or []
    album = albums[0] if albums else None
    duration = getattr(track, "duration_ms", None)
    if duration is None:
        duration = getattr(track, "durationMs", 0)
    return {
        "id": str(track_id),
        "title": str(getattr(track, "title", "")),
        "version": str(getattr(track, "version", "") or ""),
        "artists": _artists(track),
        "album": str(getattr(album, "title", "") or ""),
        "album_id": str(getattr(album, "id", "") or ""),
        "cover": _cover(track),
        "duration": int((duration or 0) / 1000),
        "available": bool(getattr(track, "available", True)),
    }


def normalize_playlist(playlist: Any, uid: str) -> dict[str, Any]:
    owner = getattr(getattr(playlist, "owner", None), "uid", None) or uid
    kind = getattr(playlist, "kind", None) or getattr(playlist, "playlist_id", None)
    return {
        "uid": str(owner),
        "kind": str(kind),
        "title": str(getattr(playlist, "title", "Без названия")),
        "count": int(getattr(playlist, "track_count", 0) or 0),
        "cover": _cover(getattr(playlist, "cover", None)) if getattr(playlist, "cover", None) else None,
    }


def is_audiobook(album: Any) -> bool:
    """A book can have meta_type=podcast; the specific audiobook type wins."""
    return any("audiobook" in str(getattr(album, field, "") or "").lower()
               for field in ("type", "meta_type"))


def normalize_book(album: Any) -> dict[str, Any]:
    return {"id": str(album.id), "type": "album", "media_kind": "audiobook",
            "title": str(album.title), "artist": _artists(album), "cover": _cover(album),
            "count": int(getattr(album, "track_count", 0) or 0)}


@dataclass
class PlaybackState:
    queue: list[dict[str, Any]]
    index: int


class YandexMusicService:
    def __init__(self, hass: HomeAssistant, source_entity: str) -> None:
        self.hass = hass
        self.source_entity = source_entity
        self._client: Client | None = None
        self._client_lock = asyncio.Lock()
        self.playback = PlaybackState([], -1)
        self._recommendations_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._recommendations_lock = asyncio.Lock()

    async def client(self) -> Client:
        async with self._client_lock:
            if self._client is not None:
                return self._client
            token = await resolve_music_token(self.hass, self.source_entity)
            try:
                self._client = await self.hass.async_add_executor_job(
                    lambda: Client(token).init()
                )
            except Exception as err:
                raise YandexMusicError(f"Не удалось открыть Яндекс Музыку: {err}") from err
            return self._client

    async def reset_client(self) -> None:
        async with self._client_lock:
            self._client = None

    async def account(self) -> dict[str, Any]:
        client = await self.client()
        status = await self.hass.async_add_executor_job(client.account_status)
        account = getattr(status, "account", None)
        plus = getattr(getattr(status, "plus", None), "has_plus", False)
        return {
            "uid": str(getattr(account, "uid", "")),
            "login": str(getattr(account, "login", "") or ""),
            "plus": bool(plus),
        }

    async def playlists(self) -> list[dict[str, Any]]:
        client = await self.client()
        account = await self.account()
        rows = await self.hass.async_add_executor_job(
            lambda: client.users_playlists_list(user_id=account["uid"])
        )
        return [normalize_playlist(row, account["uid"]) for row in rows or []]

    async def recommendations(self) -> list[dict[str, Any]]:
        """Return playable shelves from this account's Yandex Music landing."""
        async with self._recommendations_lock:
            if self._recommendations_cache and time.monotonic() - self._recommendations_cache[0] < 600:
                return self._recommendations_cache[1]
            client = await self.client()
            # Query without eitherUserId: recommendations must belong to the token owner.
            landing = await self.hass.async_add_executor_job(
                lambda: client.request.get(
                    f"{client.base_url}/landing3",
                    {"blocks": "personalplaylists,new-playlists,new-releases,mixes"},
                )
            )
            shelves = []
            for block in (landing or {}).get("blocks", []):
                items = []
                for entity in block.get("entities", []):
                    kind, data = entity.get("type"), entity.get("data") or {}
                    if kind == "personal-playlist":
                        data = data.get("data") or data.get("playlist") or {}
                        kind = "playlist"
                    if kind == "playlist" and data.get("kind") is not None:
                        owner = data.get("owner") or {}
                        cover = data.get("cover") or {}
                        uri = cover.get("uri") or next(iter(cover.get("itemsUri") or []), None)
                        items.append({
                            "type": "playlist", "uid": str(owner.get("uid") or data.get("uid") or ""),
                            "kind": str(data["kind"]), "title": data.get("title") or "Плейлист",
                            "count": data.get("trackCount", 0), "cover": _cover({"uri": uri}),
                        })
                    elif kind == "album" and data.get("id"):
                        items.append({
                            "type": "album", "id": str(data["id"]), "title": data.get("title") or "Альбом",
                            "artist": ", ".join(a.get("name", "") for a in data.get("artists", [])),
                            "count": data.get("trackCount", 0), "cover": _cover({"uri": data.get("coverUri")}),
                        })
                if items:
                    shelves.append({"id": block.get("id"), "title": block.get("title") or "Подборки для вас", "items": items})
            if not shelves:
                raise YandexMusicError("Яндекс Музыка не вернула подборки для этого аккаунта")
            self._recommendations_cache = (time.monotonic(), shelves)
            return shelves

    async def album_tracks(self, album_id: str) -> dict[str, Any]:
        client = await self.client()
        album = await self.hass.async_add_executor_job(lambda: client.albums_with_tracks(album_id))
        return {
            "title": getattr(album, "title", "Альбом"),
            "media_kind": "audiobook" if is_audiobook(album) else "album",
            "tracks": [track for volume in (getattr(album, "volumes", None) or [])
                       for row in volume if (track := normalize_track(row))],
        }

    async def playlist_tracks(self, uid: str, kind: str) -> list[dict[str, Any]]:
        client = await self.client()
        playlist = await self.hass.async_add_executor_job(
            lambda: client.users_playlists(kind=kind, user_id=uid)
        )
        if isinstance(playlist, list):
            playlist = playlist[0] if playlist else None
        if playlist is None:
            return []
        rows = await self.hass.async_add_executor_job(playlist.fetch_tracks)
        return [track for track in (normalize_track(row) for row in rows or []) if track]

    async def liked_tracks(self) -> list[dict[str, Any]]:
        client = await self.client()
        account = await self.account()
        likes = await self.hass.async_add_executor_job(
            lambda: client.users_likes_tracks(user_id=account["uid"])
        )
        ids = list(getattr(likes, "tracks_ids", []) or [])
        if not ids:
            return []
        tracks = await self.hass.async_add_executor_job(
            lambda: client.tracks(track_ids=ids[:500])
        )
        return [track for track in (normalize_track(row) for row in tracks or []) if track]

    async def search(self, text: str, page: int = 0) -> dict[str, Any]:
        client = await self.client()
        result = await self.hass.async_add_executor_job(
            lambda: client.search(text, type_="all", page=page, playlist_in_best=True)
        )
        tracks = getattr(getattr(result, "tracks", None), "results", []) or []
        albums = getattr(getattr(result, "albums", None), "results", []) or []
        artists = getattr(getattr(result, "artists", None), "results", []) or []
        playlists = getattr(getattr(result, "playlists", None), "results", []) or []
        podcasts = getattr(getattr(result, "podcasts", None), "results", []) or []
        episodes = getattr(getattr(result, "podcast_episodes", None), "results", []) or []
        return {
            "tracks": [track for track in (normalize_track(row) for row in tracks) if track],
            "albums": [
                {
                    "id": str(getattr(row, "id", "")),
                    "title": str(getattr(row, "title", "")),
                    "artist": _artists(row),
                    "cover": _cover(row),
                }
                for row in albums
            ],
            "artists": [
                {"id": str(getattr(row, "id", "")), "name": str(getattr(row, "name", ""))}
                for row in artists
            ],
            "playlists": [normalize_playlist(row, str(getattr(getattr(row, "owner", None), "uid", ""))) for row in playlists],
            "podcasts": [{"id": str(getattr(row, "id", "")), "type": "album",
                          "title": str(getattr(row, "title", "")), "artist": _artists(row),
                          "cover": _cover(row)} for row in podcasts],
            "podcast_episodes": [track for row in episodes if (track := normalize_track(row))],
            "has_more": bool(getattr(getattr(result, "tracks", None), "available", 0) > (page + 1) * 20),
        }

    async def podcasts(self) -> dict[str, Any]:
        client = await self.client()
        landing = await self.hass.async_add_executor_job(client.podcasts)
        ids = list(getattr(landing, "podcasts", None) or [])
        albums = await self.hass.async_add_executor_job(lambda: client.albums(ids[:24])) if ids else []
        return {
            "title": str(getattr(landing, "title", "") or "Подкасты"),
            "items": [{"type": "album", "id": str(row.id), "title": row.title,
                       "artist": _artists(row), "cover": _cover(row)} for row in albums or []],
        }

    async def audiobooks(self, query: str = "", page: int = 0) -> dict[str, Any]:
        client = await self.client()
        account = await self.account()
        query = query.strip()[:200]
        def fetch():
            shelves = []
            if page == 0 and not query:
                likes = client.users_likes_albums(user_id=account["uid"], rich=True) or []
                books = [normalize_book(album) for row in likes
                         if (album := getattr(row, "album", None)) and is_audiobook(album)]
                if books:
                    shelves.append({"id": "library", "title": "Ваши аудиокниги", "items": books})
            items, seen, next_page, has_more = [], set(), page, False
            # Books share the podcast search endpoint. Filter by content type,
            # never by a title containing "audiobook" (which includes soundtracks).
            for current in range(page, page + 3):
                result = client.search(query or "Аудиокниги", type_="podcast", page=current)
                block = getattr(result, "podcasts", None)
                rows = getattr(block, "results", None) or []
                for album in rows:
                    if is_audiobook(album) and str(album.id) not in seen:
                        seen.add(str(album.id))
                        items.append(normalize_book(album))
                next_page = current + 1
                has_more = bool(rows) and next_page * int(getattr(block, "per_page", 20) or 20) < int(getattr(block, "total", 0) or 0)
                if not has_more:
                    break
            shelves.append({"id": "catalog", "title": "Результаты поиска" if query else "Аудиокниги Яндекс Музыки", "items": items})
            return {"title": "Аудиокниги", "shelves": shelves, "query": query,
                    "next_page": next_page if has_more else None}
        return await self.hass.async_add_executor_job(fetch)

    async def wave(self, station: str = "user:onyourwave", queue: str | None = None) -> list[dict[str, Any]]:
        client = await self.client()
        result = await self.hass.async_add_executor_job(
            lambda: client.rotor_station_tracks(station, settings2=queue is None, queue=queue)
        )
        sequence = getattr(result, "sequence", []) or []
        return [track for track in (normalize_track(getattr(row, "track", row)) for row in sequence) if track]

    async def chart(self) -> list[dict[str, Any]]:
        client = await self.client()
        info = await self.hass.async_add_executor_job(client.chart)
        playlist = getattr(info, "chart", None) if info else None
        rows = getattr(playlist, "tracks", None) if playlist else None
        if rows is None and playlist is not None:
            rows = await self.hass.async_add_executor_job(playlist.fetch_tracks)
        return [track for track in (normalize_track(row) for row in rows or []) if track]

    async def set_like(self, track_id: str, liked: bool) -> None:
        client = await self.client()
        account = await self.account()
        fn = client.users_likes_tracks_add if liked else client.users_likes_tracks_remove
        await self.hass.async_add_executor_job(
            lambda: fn(track_id, user_id=account["uid"])
        )

    async def direct_url(self, track_id: str) -> str:
        client = await self.client()
        infos = await self.hass.async_add_executor_job(
            lambda: client.tracks_download_info(track_id, get_direct_links=True)
        )
        candidates = list(infos or [])
        if not candidates:
            raise YandexMusicError("Для трека не получена ссылка на поток")
        order = {"flac": 3, "aac": 2, "mp3": 1}
        selected = max(
            candidates,
            key=lambda row: (order.get(str(getattr(row, "codec", "")).lower(), 0), int(getattr(row, "bitrate_in_kbps", 0) or 0)),
        )
        direct = getattr(selected, "direct_link", None)
        if not direct:
            direct = await self.hass.async_add_executor_job(selected.get_direct_link)
        if not direct:
            raise YandexMusicError("Для трека не получена ссылка на поток")
        return str(direct)

    def playback_key(self) -> str:
        key = self.hass.data.get(DATA_PLAY_KEY)
        if not key:
            key = secrets.token_urlsafe(32)
            self.hass.data[DATA_PLAY_KEY] = key
        return key

    def stream_url(self, track_id: str, base_url: str) -> str:
        configured = getattr(self.hass.config, "internal_url", None) or getattr(
            self.hass.config, "external_url", None
        )
        origin = str(configured or base_url).rstrip("/")
        return f"{origin}{API_PREFIX}/stream/{track_id}?key={self.playback_key()}"
