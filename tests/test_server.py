import json
import urllib.error
import urllib.request

import pytest

from aimp_obs.cover import CoverStore
from aimp_obs.devices import DeviceManager
from aimp_obs.server import OverlayServer, _MAX_BODY_BYTES
from aimp_obs.state import StateHub


class _FakeClient:
    def refresh_handle(self):
        return False

    @property
    def connected(self):
        return False

    @property
    def hwnd(self):
        return 0


class _FakeReceiver:
    hwnd = 0


@pytest.fixture
def server(tmp_path):
    cover = CoverStore()
    hub = StateHub(_FakeClient(), _FakeReceiver(), cover, export_dir=tmp_path / "export")
    devices = DeviceManager(tmp_path / "devices.json")
    devices.enabled = True
    srv = OverlayServer(hub, cover, host="127.0.0.1", port=0, devices=devices)
    assert srv.start() is True
    assert srv.port > 0
    yield srv
    srv.stop()


def _url(srv, path):
    return f"http://127.0.0.1:{srv.port}{path}"


def _get(path, headers=None):
    req = urllib.request.Request(path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _get_json(path, headers=None):
    status, body = _get(path, headers=headers)
    try:
        return status, json.loads(body.decode("utf-8") or "{}")
    except ValueError:
        return status, {}


def _post(path, payload, headers=None):
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(path, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def test_loopback_can_read_state(server):
    status, body = _get(_url(server, "/api/state"))
    assert status == 200
    assert b"connected" in body


def test_loopback_config_write(server):
    status, data = _post(_url(server, "/api/config"), {"theme": "neon", "width": 480})
    assert status == 200
    assert data["theme"] == "neon"
    assert data["width"] == 480


def test_device_register_status_does_not_leak_token(server):
    status, reg = _post(
        _url(server, "/api/device/register"),
        {"id": "dev-x", "name": "phone", "secret": "s3cret"},
    )
    assert status == 200 and reg["ok"] is True
    assert reg["token"] == ""
    assert reg.get("secret") == "s3cret"

    server.devices.approve("dev-x")

    # Without secret: knows approved, but no token.
    status, st = _get_json(_url(server, "/api/device/status?id=dev-x"))
    assert status == 200
    assert st["approved"] is True
    assert st.get("token", "") == ""

    # With secret: token is issued.
    status, st2 = _get_json(_url(server, "/api/device/status?id=dev-x&secret=s3cret"))
    assert status == 200
    assert st2["token"]


def test_control_requires_token(server):
    status, data = _post(_url(server, "/api/control"), {"action": "playpause"})
    assert status == 403
    assert data["ok"] is False

    # Approve and use a proper token
    server.devices.register("dev-c", "phone", "cs")
    server.devices.approve("dev-c")
    token = server.devices.status("dev-c", "cs")["token"]
    assert token

    called = {}

    def _cb(action):
        called["action"] = action
        return True

    # Handler reads control_cb from the HTTP server instance, not OverlayServer.
    server._httpd.control_cb = _cb
    status, data = _post(
        _url(server, "/api/control"),
        {"action": "playpause"},
        headers={"X-AIMP-Token": token},
    )
    assert status == 200
    assert data["ok"] is True
    assert called["action"] == "playpause"


def test_health_is_open(server):
    status, body = _get(_url(server, "/health"))
    assert status == 200
    assert b"ok" in body


def test_max_body_bytes_constant():
    assert _MAX_BODY_BYTES == 64 * 1024


def test_cover_endpoint_serves_downscaled_copy(server):
    """The pages display the cover at a few hundred pixels; the endpoint must not send 4 MB."""
    import io

    from PIL import Image

    img = Image.effect_noise((1500, 1500), 100).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    raw = buf.getvalue()
    server.cover_store.update(raw)

    status, body = _get(_url(server, "/cover.png"))
    assert status == 200
    assert len(body) < len(raw) / 10

    status, jpg = _get(_url(server, "/cover.jpg"))
    assert status == 200
    assert jpg[:3] == b"\xff\xd8\xff"


def test_denied_post_still_answers(server):
    """Unread request bodies must be drained: Windows resets the connection otherwise."""
    for _ in range(5):
        status, _body = _post(_url(server, "/api/control"), {"action": "playpause"})
        assert status == 403

        body = json.dumps({"action": "x" * 200}).encode()
        req = urllib.request.Request(_url(server, "/api/nope"), data=body, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=2) as resp:
                assert resp.status == 404
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
            exc.read()
