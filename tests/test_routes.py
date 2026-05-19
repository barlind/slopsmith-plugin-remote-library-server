from __future__ import annotations

import importlib
import sys
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
        "extract_meta": lambda path: {
            "title": "Clean Tone",
            "artist": "The Fixtures",
            "album": "Bench",
            "year": 2026,
            "duration": 123.4,
            "format": "sloppak" if Path(path).suffix == ".sloppak" else "psarc",
            "arrangements": [{"name": "Lead"}],
        },
    })
    management_client = TestClient(app)
    management_client.post("/api/plugins/remote_library_server/settings", json={
        "enabled": False,
        "host": "127.0.0.1",
        "port": 9876,
        "sourceName": "Studio Source",
        "publicUrl": "https://studio.example.test",
    })
    direct_client = TestClient(routes._create_direct_app())
    return management_client, direct_client, package_path


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
    assert song["artworkUrl"].startswith("/songs/")
    assert song["packageUrl"].startswith("/songs/")
    assert str(package_path) not in str(song)


def test_direct_package_download_returns_original_file(tmp_path):
    _management_client, direct_client, package_path = _client(
        tmp_path, package_name="song.psarc", package_content=b"small-package"
    )
    song = direct_client.get("/songs").json()["songs"][0]

    response = direct_client.get(
        f"/songs/{song['remoteSongId']}/package",
        params={"packageHash": song["packageHash"]},
    )

    assert response.status_code == 200
    assert response.content == package_path.read_bytes()
    assert response.headers["x-slopsmith-package-hash"] == song["packageHash"]


def test_direct_artwork_returns_zip_cover(tmp_path):
    _management_client, direct_client, _package_path = _client(tmp_path)
    song = direct_client.get("/songs").json()["songs"][0]

    response = direct_client.get(f"/songs/{song['remoteSongId']}/art")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"cover-bytes"


def test_direct_package_hash_mismatch_404s(tmp_path):
    _management_client, direct_client, _package_path = _client(
        tmp_path, package_name="song.psarc", package_content=b"small-package"
    )
    song = direct_client.get("/songs").json()["songs"][0]

    response = direct_client.get(
        f"/songs/{song['remoteSongId']}/package",
        params={"packageHash": "sha256:not-the-package"},
    )

    assert response.status_code == 404