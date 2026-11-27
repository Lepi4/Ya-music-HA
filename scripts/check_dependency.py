"""Smoke-test the real installed library in a fresh process, without credentials."""
import inspect
from importlib.metadata import version

from yandex_music import Client, RotorSessionTracks, SessionEvent


for name in ("rotor_session_new", "rotor_session_tracks", "rotor_session_feedback",
             "users_likes_tracks_add", "users_likes_tracks_remove", "tracks_download_info"):
    assert callable(getattr(Client, name, None)), f"Missing client method: {name}"

batch = RotorSessionTracks(batch_id="test-batch", sequence=[], unknown_session=False)
assert batch.batch_id == "test-batch"
assert not getattr(batch, "radio_session_id", None)
event = SessionEvent("trackFinished", "2026-01-01T00:00:00Z", track_id="1", total_played_seconds=60)
assert event.track_id == "1"
assert "user_id" in inspect.signature(Client.users_likes_tracks_add).parameters
print(f"yandex-music {version('yandex-music')}: real imports and required contracts passed")
