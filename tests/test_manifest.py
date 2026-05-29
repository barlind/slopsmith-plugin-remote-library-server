import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _manifest() -> dict:
    return json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))


def test_manifest_declares_library_capability_relationship():
    manifest = _manifest()

    assert "capability-pipelines.v1" in manifest["standards"]
    assert "plugin-runtime-idempotent.v1" in manifest["standards"]
    library = manifest["capabilities"]["library"]
    assert library["roles"] == ["requester", "observer"]
    assert library["requests"] == ["list-providers", "get-current", "inspect"]
    assert library["observes"] == ["providers-refreshed", "source-changed"]
    assert "commands" not in library
    assert "events" not in library
    assert library["compatibility"] == "none"
    assert library["ownership"] == "requester-only"
    assert library["safety"] == "safe"


def test_manifest_does_not_declare_canonical_library_provider_role():
    manifest = _manifest()

    assert "provider" not in manifest["capabilities"]["library"]["roles"]
    assert "owner" not in manifest["capabilities"]["library"]["roles"]


def test_manifest_does_not_declare_server_management_domain():
    manifest = _manifest()

    assert "remote-library-server" not in manifest.get("capabilities", {})


def test_screen_does_not_register_runtime_capability_handlers():
    screen = (ROOT / "screen.js").read_text(encoding="utf-8")

    assert "registerParticipant(" not in screen
    assert "emitEvent(" not in screen
