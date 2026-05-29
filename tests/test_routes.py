from __future__ import annotations

import importlib
import hashlib
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeLocalProvider:
    def __init__(self, package_name: str):
        self.package_name = package_name

    def _song(self) -> dict:
        return {
            "filename": self.package_name,
            "title": "Clean Tone",
            "artist": "The Fixtures",
            "album": "Bench",
            "year": 2026,
            "duration": 123.4,
            "format": "sloppak" if Path(self.package_name).suffix == ".sloppak" else "psarc",
            "stem_count": 4 if Path(self.package_name).suffix == ".sloppak" else 0,
            "stem_ids": ["drums", "bass", "guitar", "vocals"] if Path(self.package_name).suffix == ".sloppak" else [],
            "arrangements": [{"name": "Lead"}],
            "has_lyrics": True,
            "tuning": "E Standard",
        }

    def query_page(self, **kwargs):
        q = str(kwargs.get("q") or "").lower()
        song = self._song()
        songs = [song] if q in song["title"].lower() else []
        return songs, len(songs)

    def query_artists(self, **kwargs):
        song = self._song()
        return [{
            "name": song["artist"],
            "album_count": 1,
            "song_count": 1,
            "albums": [{"name": song["album"], "songs": [song]}],
        }], 1

    def query_stats(self, **kwargs):
        return {"total_songs": 1, "total_artists": 1, "letters": {"T": 1}}

    def tuning_names(self):
        return {"tunings": [{"name": "E Standard", "sort_key": 0, "count": 1}]}

    async def get_art(self, song_id: str):
        assert song_id == self.package_name
        return Response(content=b"cover-bytes", media_type="image/png")


class FakeLibraryProviders:
    def __init__(self, provider):
        self.provider = provider

    def get(self, provider_id: str):
        return self.provider if provider_id == "local" else None

    def provider_method(self, provider, method_name: str):
        return getattr(provider, method_name, None)


def _client(tmp_path, package_name="song.sloppak", package_content: bytes | None = None):
    routes = importlib.import_module("routes")
    routes = importlib.reload(routes)

    dlc_dir = tmp_path / "dlc"
    dlc_dir.mkdir()
    package_path = dlc_dir / package_name
    if package_name.endswith(".sloppak") and package_content is None:
        with zipfile.ZipFile(package_path, "w") as archive:
            archive.writestr("manifest.json", "{}")
            archive.writestr("cover.png", b"cover-bytes")
            archive.writestr("song.bin", b"audio")
    else:
        package_path.write_bytes(package_content or b"package-bytes")

    app = FastAPI()
    routes.setup(app, {
        "config_dir": tmp_path / "config",
        "get_dlc_dir": lambda: dlc_dir,
        "library_providers": FakeLibraryProviders(FakeLocalProvider(package_name)),
    })
    management_client = TestClient(app)
    management_client.post("/api/plugins/remote_library_server/settings", json={
        "enabled": False,
        "host": "127.0.0.1",
        "port": 9876,
        "sourceName": "Studio Source",
    })
    direct_client = TestClient(routes._create_direct_app())
    return management_client, direct_client, package_path


def _enable_nam_tone_sharing(management_client):
    response = management_client.post("/api/plugins/remote_library_server/settings", json={
        "enabled": False,
        "host": "127.0.0.1",
        "port": 9876,
        "sourceName": "Studio Source",
        "shareNamToneAssets": True,
    })
    assert response.status_code == 200


def _write_nam_tone_fixture(config_dir: Path, filename: str = "song.psarc") -> dict:
    config_dir.mkdir(parents=True, exist_ok=True)
    models_dir = config_dir / "nam_models"
    irs_dir = config_dir / "nam_irs"
    models_dir.mkdir()
    irs_dir.mkdir()
    model_bytes = b'{"version": "test model"}'
    ir_bytes = b"RIFF-test-ir"
    (models_dir / "clean.nam").write_bytes(model_bytes)
    (irs_dir / "room.wav").write_bytes(ir_bytes)
    conn = sqlite3.connect(config_dir / "nam_tone.db")
    conn.executescript("""
        CREATE TABLE presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            model_file TEXT,
            ir_file TEXT,
            input_gain REAL NOT NULL DEFAULT 1.0,
            output_gain REAL NOT NULL DEFAULT 0.5,
            gate_threshold REAL NOT NULL DEFAULT -60.0,
            settings_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE tone_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            tone_key TEXT NOT NULL,
            preset_id INTEGER NOT NULL,
            UNIQUE(filename, tone_key),
            FOREIGN KEY (preset_id) REFERENCES presets(id)
        );
    """)
    conn.execute(
        "INSERT INTO presets (name, model_file, ir_file, input_gain, output_gain, gate_threshold, settings_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Clean NAM", "clean.nam", "room.wav", 1.25, 0.75, -55.0, json.dumps({"cab": "open"})),
    )
    preset_id = conn.execute("SELECT id FROM presets WHERE name = ?", ("Clean NAM",)).fetchone()[0]
    conn.execute(
        "INSERT INTO tone_mappings (filename, tone_key, preset_id) VALUES (?, ?, ?)",
        (filename, "Clean", preset_id),
    )
    conn.commit()
    conn.close()
    return {
        "modelSha": "sha256:" + hashlib.sha256(model_bytes).hexdigest(),
        "irSha": "sha256:" + hashlib.sha256(ir_bytes).hexdigest(),
    }


def test_management_status_uses_direct_server_shape(tmp_path):
    management_client, _direct_client, _package_path = _client(tmp_path)

    response = management_client.get("/api/plugins/remote_library_server/status")

    assert response.status_code == 200
    data = response.json()
    assert data["source"]["sourceName"] == "Studio Source"
    assert data["source"]["songCount"] == 1
    assert data["server"]["port"] == 9876
    assert data["server"]["protocol"] == "slopsmith-direct-library.v1"
    assert "relay" not in data
    assert management_client.get("/api/plugins/remote_library_server/pairing/requests").status_code == 404


def test_shutdown_stops_direct_server(tmp_path, monkeypatch):
    routes = importlib.import_module("routes")
    routes = importlib.reload(routes)
    stopped = []

    monkeypatch.setattr(routes, "_stop_direct_server", lambda: stopped.append(True) or {})

    app = FastAPI()
    routes.setup(app, {
        "config_dir": tmp_path / "config",
        "get_dlc_dir": lambda: tmp_path / "dlc",
        "library_providers": FakeLibraryProviders(FakeLocalProvider("song.sloppak")),
        "get_scan_status": lambda: {"running": False, "stage": "complete"},
    })

    assert routes._shutdown in app.router.on_shutdown
    routes._shutdown()
    assert stopped == [True]


def test_direct_source_and_song_search_do_not_expose_paths(tmp_path):
    _management_client, direct_client, package_path = _client(tmp_path)

    source = direct_client.get("/source")
    songs = direct_client.get("/songs?q=clean&pageSize=10")

    assert source.status_code == 200
    assert source.json()["sourceName"] == "Studio Source"
    assert source.json()["server"]["url"] == "http://127.0.0.1:9876"
    assert songs.status_code == 200
    song = songs.json()["songs"][0]
    assert song["title"] == "Clean Tone"
    assert song["artist"] == "The Fixtures"
    assert song["stem_count"] == 4
    assert song["stem_ids"] == ["drums", "bass", "guitar", "vocals"]
    assert song["artworkUrl"].startswith("/songs/")
    assert song["packageUrl"].startswith("/songs/")
    assert str(package_path) not in str(song)


def test_direct_songs_use_local_provider_paged_query_without_package_hashing(tmp_path):
    _management_client, direct_client, _package_path = _client(tmp_path)

    response = direct_client.get("/songs?q=clean&page=0&pageSize=1&sort=title&direction=desc")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["nextCursor"] is None
    assert data["query"]["filtersApplied"] is True
    song = data["songs"][0]
    assert song["title"] == "Clean Tone"
    assert song["remoteSongId"].startswith("song_")
    assert "packageHash" not in song


def test_nam_tone_sync_is_disabled_by_default(tmp_path):
    _management_client, direct_client, _package_path = _client(
        tmp_path, package_name="song.psarc", package_content=b"small-package"
    )
    song = direct_client.get("/songs").json()["songs"][0]

    response = direct_client.get(f"/songs/{song['remoteSongId']}/nam-tone-sync")

    assert response.status_code == 403
    assert "disabled" in response.json()["detail"]


def test_nam_tone_sync_exports_song_mappings_and_referenced_assets(tmp_path):
    management_client, direct_client, _package_path = _client(
        tmp_path, package_name="song.psarc", package_content=b"small-package"
    )
    expected = _write_nam_tone_fixture(tmp_path / "config", "song.psarc")
    _enable_nam_tone_sharing(management_client)
    song = direct_client.get("/songs").json()["songs"][0]

    response = direct_client.get(f"/songs/{song['remoteSongId']}/nam-tone-sync")

    assert response.status_code == 200
    data = response.json()
    assert data["schema"] == "slopsmith.nam-tone-sync.v1"
    assert data["sourceFilename"] == "song.psarc"
    assert data["mappings"] == [{"toneKey": "Clean", "presetRef": "preset:1"}]
    preset = data["presets"][0]
    assert preset["name"] == "Clean NAM"
    assert preset["inputGain"] == 1.25
    assert preset["outputGain"] == 0.75
    assert preset["gateThreshold"] == -55.0
    assert preset["settings"] == {"cab": "open"}
    assert preset["modelFile"]["name"] == "clean.nam"
    assert preset["modelFile"]["sha256"] == expected["modelSha"]
    assert preset["irFile"]["name"] == "room.wav"
    assert preset["irFile"]["sha256"] == expected["irSha"]

    model = direct_client.get(preset["modelFile"]["url"])
    ir = direct_client.get(preset["irFile"]["url"])

    assert model.status_code == 200
    assert model.content == b'{"version": "test model"}'
    assert model.headers["content-type"].startswith("application/json")
    assert ir.status_code == 200
    assert ir.content == b"RIFF-test-ir"
    assert ir.headers["content-type"].startswith("audio/wav")


def test_nam_tone_asset_endpoint_only_serves_referenced_song_assets(tmp_path):
    management_client, direct_client, _package_path = _client(
        tmp_path, package_name="song.psarc", package_content=b"small-package"
    )
    _write_nam_tone_fixture(tmp_path / "config", "song.psarc")
    (tmp_path / "config" / "nam_models" / "other.nam").write_bytes(b"other")
    _enable_nam_tone_sharing(management_client)
    song = direct_client.get("/songs").json()["songs"][0]

    response = direct_client.get(f"/songs/{song['remoteSongId']}/nam-tone-assets/model/other.nam")

    assert response.status_code == 404


def test_direct_package_download_returns_original_file(tmp_path):
    _management_client, direct_client, package_path = _client(
        tmp_path, package_name="song.psarc", package_content=b"small-package"
    )
    song = direct_client.get("/songs").json()["songs"][0]

    response = direct_client.get(f"/songs/{song['remoteSongId']}/package")

    assert response.status_code == 200
    assert response.content == package_path.read_bytes()


def test_direct_artwork_returns_zip_cover(tmp_path):
    _management_client, direct_client, _package_path = _client(tmp_path)
    song = direct_client.get("/songs").json()["songs"][0]

    response = direct_client.get(f"/songs/{song['remoteSongId']}/art")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"cover-bytes"


def test_direct_unknown_package_404s(tmp_path):
    _management_client, direct_client, _package_path = _client(
        tmp_path, package_name="song.psarc", package_content=b"small-package"
    )

    response = direct_client.get("/songs/song_not-real/package")

    assert response.status_code == 404