from aimp_obs.devices import DeviceManager


def test_register_starts_pending_and_approve_issues_token(tmp_path):
    dm = DeviceManager(tmp_path / "devices.json")
    assert dm.enabled is False
    r = dm.register("dev-1", "iPhone")
    assert r["pending"] is True and r["approved"] is False
    assert dm.check_token(r["token"]) is None  # no token before approval

    assert dm.approve("dev-1") is True
    st = dm.status("dev-1")
    assert st["approved"] is True
    assert st["token"]
    assert dm.check_token(st["token"]) == "dev-1"
    assert dm.check_token("bad-token") is None


def test_reject_and_remove(tmp_path):
    dm = DeviceManager(tmp_path / "devices.json")
    dm.register("dev-2", "iPad")
    assert dm.reject("dev-2") is True
    assert dm.status("dev-2")["rejected"] is True
    assert dm.remove("dev-2") is True
    assert dm.status("dev-2")["known"] is False


def test_persistence(tmp_path):
    path = tmp_path / "devices.json"
    dm = DeviceManager(path)
    dm.register("dev-3", "Phone")
    dm.approve("dev-3")
    dm2 = DeviceManager(path)
    assert dm2.status("dev-3")["approved"] is True
    assert dm2.check_token(dm2.status("dev-3")["token"]) == "dev-3"
