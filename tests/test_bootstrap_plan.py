import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import bootstrap_plan as bp

OK = {"python": (3, 12), "manager": "linux-apt", "have": {"ffmpeg", "gtk4", "adwaita", "gst"},
      "venv_ok": True, "imports_ok": True, "online": False, "dest": "/home/u/SmoothCast"}


def ids(p):
    return [s["id"] for s in p["steps"]]


def test_fully_provisioned_machine_only_registers_and_needs_no_network():
    p = bp.plan(OK)
    assert p["ready"] and ids(p) == ["register"] and not p["needs_admin"]


def test_virgin_machine_orders_python_native_venv_deps_register():
    p = bp.plan({"python": None, "manager": "linux-apt", "have": set(), "dest": "/home/u/App", "online": True})
    assert ids(p) == ["python", "native", "venv", "deps", "register"] and p["needs_admin"] and p["ready"]


def test_old_python_and_offline_and_no_manager_block_clearly():
    p = bp.plan({**OK, "python": (3, 8), "manager": None})
    assert not p["ready"] and any("package manager" in b for b in p["blockers"])
    q = bp.plan({**OK, "python": (3, 8), "online": False})
    assert not q["ready"] and any("No network" in b for b in q["blockers"])
    assert bp.python_ok((3, 10, 1)) and not bp.python_ok(None)


def test_destination_safety_and_spaces_allowed():
    assert bp.safe_destination("/home/me/My Apps/SmoothCast")[0]
    for bad in ("", "/", "/usr/lib/x", "/etc", "C:\\Windows\\x", "C:\\Program Files\\y"):
        assert not bp.safe_destination(bad)[0], bad
    assert not bp.safe_destination("/home/u/x", existing_foreign=True)[0]
    assert not bp.plan({**OK, "dest": "/usr"})["ready"]


def test_windows_user_scope_needs_no_admin():
    p = bp.plan({"python": None, "manager": "windows-winget", "have": set(), "dest": "C:\\Users\\a\\SmoothCast", "online": True})
    assert not p["needs_admin"]
