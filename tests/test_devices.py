from aimp_obs.devices import DeviceManager


def test_register_starts_pending_and_approve_issues_token(tmp_path):
    dm = DeviceManager(tmp_path / "devices.json")
    assert dm.enabled is False
    r = dm.register("dev-1", "iPhone", "secret-1")
    assert r["pending"] is True and r["approved"] is False
    assert r.get("secret") == "secret-1"
    assert dm.check_token(r["token"]) is None  # no token before approval

    assert dm.approve("dev-1") is True
    st = dm.status("dev-1", "secret-1")
    assert st["approved"] is True
    assert st["token"]
    assert dm.check_token(st["token"]) == "dev-1"
    assert dm.check_token("bad-token") is None


def test_status_without_secret_does_not_leak_token(tmp_path):
    dm = DeviceManager(tmp_path / "devices.json")
    dm.register("dev-1", "iPhone", "secret-1")
    dm.approve("dev-1")

    st = dm.status("dev-1")
    assert st["approved"] is True
    assert st["token"] == ""

    st_wrong = dm.status("dev-1", "wrong-secret")
    assert st_wrong["approved"] is True
    assert st_wrong["token"] == ""

    # register of an existing approved device also requires the secret
    r = dm.register("dev-1", "iPhone")
    assert r["approved"] is True
    assert r["token"] == ""
    r2 = dm.register("dev-1", "iPhone", "secret-1")
    assert r2["token"]


def test_reject_and_remove(tmp_path):
    dm = DeviceManager(tmp_path / "devices.json")
    dm.register("dev-2", "iPad", "secret-2")
    assert dm.reject("dev-2") is True
    assert dm.status("dev-2", "secret-2")["rejected"] is True
    assert dm.remove("dev-2") is True
    assert dm.status("dev-2", "secret-2")["known"] is False


def test_persistence(tmp_path):
    path = tmp_path / "devices.json"
    dm = DeviceManager(path)
    dm.register("dev-3", "Phone", "secret-3")
    dm.approve("dev-3")
    dm2 = DeviceManager(path)
    st = dm2.status("dev-3", "secret-3")
    assert st["approved"] is True
    assert dm2.check_token(st["token"]) == "dev-3"
    assert dm2.status("dev-3")["token"] == ""


def test_legacy_device_without_secret_can_claim_one(tmp_path):
    path = tmp_path / "devices.json"
    # Simulate a pre-upgrade record that has a token but no secret.
    path.write_text(
        '{"dev-old": {"id": "dev-old", "name": "Phone", "token": "tok-old", '
        '"status": "approved", "created_at": 0, "approved_at": 1}}',
        encoding="utf-8",
    )
    dm = DeviceManager(path)
    # Claiming a legacy approved device must NOT hand out the old token;
    # it resets to pending and rotates the token, requiring re-approval.
    r = dm.register("dev-old", "Phone", "claimed-secret")
    assert r["approved"] is False
    assert r["pending"] is True
    assert r["token"] == ""

    st = dm.status("dev-old", "claimed-secret")
    assert st["pending"] is True
    assert st["token"] == ""

    dm.approve("dev-old")
    st2 = dm.status("dev-old", "claimed-secret")
    assert st2["approved"] is True
    assert st2["token"] and st2["token"] != "tok-old"
    assert dm.status("dev-old")["token"] == ""


def test_legacy_pending_device_claim_keeps_pending(tmp_path):
    path = tmp_path / "devices.json"
    path.write_text(
        '{"dev-p": {"id": "dev-p", "name": "Phone", "token": "tok-p", '
        '"status": "pending", "created_at": 0, "approved_at": null}}',
        encoding="utf-8",
    )
    dm = DeviceManager(path)
    r = dm.register("dev-p", "Phone", "s-p")
    assert r["pending"] is True
    assert r["token"] == ""
    dm.approve("dev-p")
    assert dm.status("dev-p", "s-p")["token"]


def test_list_helpers_strip_token_and_secret(tmp_path):
    dm = DeviceManager(tmp_path / "devices.json")
    dm.register("dev-4", "Phone", "secret-4")
    dm.approve("dev-4")
    for row in dm.approved() + dm.pending() + dm.all():
        assert "token" not in row
        assert "secret" not in row
        assert row["id"]
