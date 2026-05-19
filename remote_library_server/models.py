from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PackageForm(str, Enum):
    PSARC_FILE = "psarc-file"
    SLOPPAK_ZIP = "sloppak-zip"
    SLOPPAK_DIRECTORY = "sloppak-directory"
    UNSUPPORTED = "unsupported"


class SyncSupport(str, Enum):
    SYNCABLE = "syncable"
    NOT_SYNCABLE = "not-syncable"


class RemoteSongStatus(str, Enum):
    REMOTE_ONLY = "remote-only"
    NOT_SYNCABLE = "not-syncable"


@dataclass
class RemoteSongSummary:
    source_id: str
    remote_song_id: str
    title: str
    artist: str = ""
    album: str = ""
    year: int | None = None
    duration: float | None = None
    format: str = "unsupported"
    package_form: PackageForm = PackageForm.UNSUPPORTED
    manifest_hash: str = ""
    package_hash: str = ""
    size_bytes: int = 0
    artwork_thumb_hash: str | None = None
    arrangements: list[dict] = field(default_factory=list)
    has_lyrics: bool = False
    stem_count: int = 0
    stem_ids: list[str] = field(default_factory=list)
    tuning: str = ""
    capabilities: list[str] = field(default_factory=list)
    sync_support: SyncSupport = SyncSupport.NOT_SYNCABLE
    status: RemoteSongStatus = RemoteSongStatus.NOT_SYNCABLE

    def to_dict(self) -> dict:
        return {
            "sourceId": self.source_id,
            "remoteSongId": self.remote_song_id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "year": self.year,
            "duration": self.duration,
            "format": self.format,
            "packageForm": self.package_form.value,
            "manifestHash": self.manifest_hash,
            "packageHash": self.package_hash,
            "sizeBytes": self.size_bytes,
            "artworkThumbHash": self.artwork_thumb_hash,
            "arrangements": self.arrangements,
            "has_lyrics": self.has_lyrics,
            "stem_count": self.stem_count,
            "stem_ids": self.stem_ids,
            "tuning": self.tuning,
            "capabilities": self.capabilities,
            "syncSupport": self.sync_support.value,
            "status": self.status.value,
        }