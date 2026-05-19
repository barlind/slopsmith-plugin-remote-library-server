from __future__ import annotations

import io
import os
import re
import shutil
import socket
import tempfile
import threading
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from remote_library_server.crypto import sha256_hex
from remote_library_server.models import PackageForm, RemoteSongStatus, RemoteSongSummary, SyncSupport
from remote_library_server.store import RemoteLibraryServerStore

_store: RemoteLibraryServerStore | None = None
_get_dlc_dir = None
_extract_meta = None
_meta_db = None
_direct_server = None
_direct_thread: threading.Thread | None = None


def _settings() -> dict:
    return _store.load_settings() if _store else {}


def _source_id() -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", socket.gethostname()).strip("-").lower()
    return f"direct_{slug or 'source'}"


def _source_name() -> str:
    return _settings().get("sourceName") or f"Remote Library on {socket.gethostname()}"


def _bind_host() -> str:
    return str(_settings().get("host") or "127.0.0.1")


def _bind_port() -> int:
    try:
        return max(1, min(65535, int(_settings().get("port") or 8765)))
    except (TypeError, ValueError):
        return 8765


def _display_host() -> str:
    host = _bind_host()
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def _direct_url() -> str:
    return f"http://{_display_host()}:{_bind_port()}"


def _public_url() -> str:
    return str(_settings().get("publicUrl") or "").rstrip("/")


def _local_library_root() -> Path | None:
    if callable(_get_dlc_dir):
        resolved = _get_dlc_dir()
        if isinstance(resolved, (str, os.PathLike)):
            path = Path(resolved)
            return path if path.exists() else None
    dlc_dir = os.environ.get("DLC_DIR")
    if not dlc_dir:
        return None
    path = Path(dlc_dir)
    return path if path.exists() else None


def _package_form_for_path(path: Path) -> PackageForm:
    suffix = path.suffix.lower()
    if path.is_dir() and path.name.lower().endswith(".sloppak"):
        return PackageForm.SLOPPAK_DIRECTORY
    if suffix == ".psarc":
        return PackageForm.PSARC_FILE
    if suffix in {".sloppak", ".zip"}:
        return PackageForm.SLOPPAK_ZIP
    return PackageForm.UNSUPPORTED


def _iter_package_paths(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if _package_form_for_path(path) != PackageForm.UNSUPPORTED:
            candidates.append(path)
    return sorted(candidates, key=lambda item: item.relative_to(root).as_posix().lower())


def _sha256_file(path: Path) -> str:
    digest = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _coerce_int(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _coerce_float(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _metadata_for_package(package_path: Path) -> dict:
    if not callable(_extract_meta) or not package_path.exists():
        return {}
    root = _local_library_root()
    stat = package_path.stat()
    try:
        cache_key = package_path.relative_to(root).as_posix() if root else package_path.name
    except ValueError:
        cache_key = package_path.name
    if _meta_db is not None and hasattr(_meta_db, "get"):
        try:
            cached = _meta_db.get(cache_key, float(stat.st_mtime), int(stat.st_size))
            if cached:
                return cached
        except Exception:
            pass
    try:
        metadata = _extract_meta(package_path) or {}
    except Exception:
        return {}
    if _meta_db is not None and hasattr(_meta_db, "put") and metadata.get("title"):
        try:
            _meta_db.put(cache_key, float(stat.st_mtime), int(stat.st_size), metadata)
        except Exception:
            pass
    return metadata


def _song_summary(package_path: Path, root: Path) -> dict:
    package_form = _package_form_for_path(package_path)
    relative_name = package_path.relative_to(root).as_posix()
    syncable = package_form in {PackageForm.PSARC_FILE, PackageForm.SLOPPAK_ZIP}
    package_hash = _sha256_file(package_path) if syncable and package_path.is_file() else ""
    identity = f"{_source_id()}:{relative_name}".encode("utf-8")
    metadata = _metadata_for_package(package_path)
    song_format = metadata.get("format") or (
        "psarc" if package_form == PackageForm.PSARC_FILE
        else "sloppak" if "sloppak" in package_form.value
        else "unsupported"
    )
    remote_song_id = sha256_hex(identity).replace("sha256:", "song_", 1)
    artwork_hash = (
        sha256_hex(f"art:{_source_id()}:{relative_name}:{package_hash}".encode("utf-8"))
        if syncable
        else None
    )
    summary = RemoteSongSummary(
        source_id=_source_id(),
        remote_song_id=remote_song_id,
        title=metadata.get("title") or package_path.stem,
        artist=metadata.get("artist") or "",
        album=metadata.get("album") or "",
        year=_coerce_int(metadata.get("year")),
        duration=_coerce_float(metadata.get("duration")),
        format=song_format,
        package_form=package_form,
        manifest_hash=sha256_hex(identity),
        package_hash=package_hash,
        size_bytes=package_path.stat().st_size if package_path.is_file() else 0,
        artwork_thumb_hash=artwork_hash,
        arrangements=list(metadata.get("arrangements") or []),
        has_lyrics=bool(metadata.get("has_lyrics", False)),
        tuning=metadata.get("tuning") or metadata.get("tuning_name") or "",
        capabilities=["artwork", "package-download"] if syncable else [],
        sync_support=SyncSupport.SYNCABLE if syncable else SyncSupport.NOT_SYNCABLE,
        status=RemoteSongStatus.REMOTE_ONLY if syncable else RemoteSongStatus.NOT_SYNCABLE,
    ).to_dict()
    summary["artworkUrl"] = f"/songs/{remote_song_id}/art"
    if syncable:
        summary["packageUrl"] = f"/songs/{remote_song_id}/package"
    return summary


def _local_song_summaries(limit: int = 5000) -> list[dict]:
    root = _local_library_root()
    if not root:
        return []
    songs = []
    for package_path in _iter_package_paths(root):
        if len(songs) >= limit:
            break
        songs.append(_song_summary(package_path, root))
    return songs


def _search_songs(query: str = "") -> list[dict]:
    needle = (query or "").strip().lower()
    songs = _local_song_summaries()
    if not needle:
        return songs
    return [
        song for song in songs
        if needle in str(song.get("title", "")).lower()
        or needle in str(song.get("artist", "")).lower()
        or needle in str(song.get("album", "")).lower()
    ]


def _local_package_path(song_id: str, package_hash: str | None = None) -> Path | None:
    root = _local_library_root()
    if not root:
        return None
    for package_path in _iter_package_paths(root):
        summary = _song_summary(package_path, root)
        if summary["remoteSongId"] != song_id:
            continue
        if package_hash and summary.get("packageHash") != package_hash:
            continue
        return package_path
    return None


def _zip_artwork(package_path: Path) -> tuple[bytes, str] | None:
    if not zipfile.is_zipfile(package_path):
        return None
    with zipfile.ZipFile(package_path) as archive:
        for item in archive.namelist():
            name = Path(item).name.lower()
            if name in {"cover.jpg", "cover.jpeg", "cover.png", "cover.webp"}:
                suffix = Path(name).suffix
                media_type = {".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
                return archive.read(item), media_type
    return None


def _package_artwork(package_path: Path) -> tuple[bytes, str] | None:
    if package_path.is_dir() and package_path.name.lower().endswith(".sloppak"):
        for name in ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp"):
            cover = package_path / name
            if cover.exists() and cover.is_file():
                media_type = {".png": "image/png", ".webp": "image/webp"}.get(cover.suffix.lower(), "image/jpeg")
                return cover.read_bytes(), media_type
        return None
    zipped = _zip_artwork(package_path)
    if zipped:
        return zipped
    if package_path.suffix.lower() != ".psarc":
        return None
    tmp = tempfile.mkdtemp(prefix="remote_library_server_art_")
    try:
        from PIL import Image
        from psarc import unpack_psarc

        unpack_psarc(str(package_path), tmp)
        dds_files = sorted(
            Path(tmp).rglob("*.dds"), key=lambda item: item.stat().st_size, reverse=True
        )
        if not dds_files:
            return None
        image = Image.open(dds_files[0]).convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue(), "image/png"
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _source_payload() -> dict:
    songs = _local_song_summaries()
    return {
        "ok": True,
        "sourceId": _source_id(),
        "sourceName": _source_name(),
        "songCount": len(songs),
        "server": {
            "url": _direct_url(),
            "publicUrl": _public_url(),
            "protocol": "slopsmith-direct-library.v1",
        },
    }


def _create_direct_app() -> FastAPI:
    direct_app = FastAPI(title="Slopsmith Remote Library Direct Server", version="0.2.0")
    direct_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )

    @direct_app.get("/health")
    def health() -> dict:
        return {"ok": True, "sourceId": _source_id()}

    @direct_app.get("/source")
    def source() -> dict:
        return _source_payload()

    @direct_app.get("/songs")
    def songs(q: str = "", pageSize: int = Query(50, ge=1, le=500), cursor: str | None = None) -> dict:
        offset = max(0, int(cursor or 0))
        matches = _search_songs(q)
        page = matches[offset:offset + pageSize]
        next_cursor = str(offset + pageSize) if offset + pageSize < len(matches) else None
        return {
            "source": _source_payload(),
            "songs": page,
            "total": len(matches),
            "nextCursor": next_cursor,
        }

    @direct_app.get("/songs/{song_id}/art")
    def song_art(song_id: str) -> Response:
        package_path = _local_package_path(song_id)
        if not package_path:
            raise HTTPException(status_code=404, detail="song not found")
        artwork = _package_artwork(package_path)
        if not artwork:
            raise HTTPException(status_code=404, detail="artwork not found")
        content, media_type = artwork
        return Response(content=content, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})

    @direct_app.get("/songs/{song_id}/package")
    def song_package(song_id: str, packageHash: str | None = None) -> FileResponse:
        package_path = _local_package_path(song_id, packageHash)
        if not package_path or not package_path.is_file():
            raise HTTPException(status_code=404, detail="package not found")
        summary = _song_summary(package_path, _local_library_root())
        return FileResponse(
            package_path,
            media_type="application/octet-stream",
            filename=package_path.name,
            headers={
                "X-Slopsmith-Remote-Song-Id": song_id,
                "X-Slopsmith-Package-Hash": summary.get("packageHash") or "",
            },
        )

    return direct_app


def _is_direct_server_running() -> bool:
    return bool(_direct_thread and _direct_thread.is_alive())


def _ensure_bindable(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise ValueError(f"cannot bind direct server on {host}:{port}: {exc}") from exc


def _start_direct_server() -> dict:
    global _direct_server, _direct_thread
    if _is_direct_server_running():
        return _server_status()
    host = _bind_host()
    port = _bind_port()
    _ensure_bindable(host, port)
    import uvicorn

    config = uvicorn.Config(_create_direct_app(), host=host, port=port, log_level="warning")
    _direct_server = uvicorn.Server(config)
    _direct_thread = threading.Thread(target=_direct_server.run, name="remote-library-direct-server", daemon=True)
    _direct_thread.start()
    if _store:
        _store.add_activity("direct-server", "started", f"Direct server started on {host}:{port}")
    return _server_status()


def _stop_direct_server() -> dict:
    global _direct_server, _direct_thread
    if _direct_server is not None:
        _direct_server.should_exit = True
    if _direct_thread is not None and _direct_thread.is_alive():
        _direct_thread.join(timeout=3)
    _direct_server = None
    _direct_thread = None
    if _store:
        _store.add_activity("direct-server", "stopped", "Direct server stopped")
    return _server_status()


def _restart_direct_server() -> dict:
    _stop_direct_server()
    return _start_direct_server()


def _server_status() -> dict:
    return {
        "running": _is_direct_server_running(),
        "host": _bind_host(),
        "port": _bind_port(),
        "url": _direct_url(),
        "publicUrl": _public_url(),
        "protocol": "slopsmith-direct-library.v1",
    }


def setup(app, context):
    global _store, _get_dlc_dir, _extract_meta, _meta_db
    _store = RemoteLibraryServerStore(Path(context["config_dir"]))
    _get_dlc_dir = context.get("get_dlc_dir")
    _extract_meta = context.get("extract_meta")
    _meta_db = context.get("meta_db")
    if _settings().get("enabled"):
        try:
            _start_direct_server()
        except ValueError as exc:
            _store.add_activity("direct-server", "failed", str(exc))

    @app.get("/api/plugins/remote_library_server/settings")
    def get_settings():
        return _settings()

    @app.post("/api/plugins/remote_library_server/settings")
    def save_settings(data: dict):
        settings = _store.save_settings(data)
        try:
            server = _restart_direct_server() if settings.get("enabled") else _stop_direct_server()
        except ValueError as exc:
            _store.add_activity("direct-server", "failed", str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {**settings, "server": server}

    @app.get("/api/plugins/remote_library_server/status")
    def status():
        root = _local_library_root()
        songs = _local_song_summaries()
        return {
            "source": {
                "sourceId": _source_id(),
                "sourceName": _source_name(),
                "songCount": len(songs),
                "libraryRootConfigured": bool(root),
            },
            "server": _server_status(),
            "settings": _settings(),
        }

    @app.post("/api/plugins/remote_library_server/start")
    def start_server():
        _store.save_settings({"enabled": True})
        try:
            return {"server": _start_direct_server(), "settings": _settings()}
        except ValueError as exc:
            _store.add_activity("direct-server", "failed", str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/plugins/remote_library_server/stop")
    def stop_server():
        _store.save_settings({"enabled": False})
        return {"server": _stop_direct_server(), "settings": _settings()}

    @app.get("/api/plugins/remote_library_server/local-songs")
    def local_songs(q: str = "", pageSize: int = Query(50, ge=1, le=500), cursor: str | None = None):
        offset = max(0, int(cursor or 0))
        matches = _search_songs(q)
        page = matches[offset:offset + pageSize]
        next_cursor = str(offset + pageSize) if offset + pageSize < len(matches) else None
        return {"songs": page, "total": len(matches), "nextCursor": next_cursor}

    @app.get("/api/plugins/remote_library_server/activity")
    def activity():
        return {"events": _store.list_activity()}

    return app