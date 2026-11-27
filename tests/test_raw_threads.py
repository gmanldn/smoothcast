"""Ratchet (ARCH-08, #696): no new raw ``threading.Thread(`` outside the task runtime.

New background work goes through ``task_runtime.Runtime``. Counts only go down;
lower or delete an entry when you migrate that module.
"""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
ALLOWED = {
    "async_jobs.py": 1,
    "audio_monitor.py": 1,
    "cast_av.py": 1,
    "cast_control.py": 1,
    "cast_lifecycle.py": 1,
    "cast_mesh.py": 4,
    "cast_portal.py": 1,
    "castctl.py": 1,
    "config_control.py": 1,
    "dlna.py": 1,
    "jank_ui.py": 1,
    "library_index_v2.py": 1,
    "link_acquisition.py": 2,
    "link_egress.py": 2,
    "link_sandbox_probe.py": 1,
    "link_setup.py": 1,
    "low_end_policy.py": 1,
    "mesh_acquisition_bridge.py": 1,
    "mesh_acquisition_executor.py": 1,
    "mesh_acquisition_transfer.py": 1,
    "mesh_heartbeat.py": 1,
    "mesh_http.py": 1,
    "mesh_service.py": 2,
    "mesh_udp.py": 1,
    "portal.py": 1,
    "portal_update_http.py": 1,
    "replica_manager.py": 1,
    "sc_core.py": 1,
    "server.py": 3,
    "shutdown_plan.py": 1,
    "streamer.py": 1,
    "supervisor.py": 1,
    "update_button.py": 3,
    "update_facts.py": 1,
}


def test_no_new_raw_threads():
    found = {p.name: p.read_text(encoding="utf-8").count("threading.Thread(")
             for p in SRC.glob("*.py") if p.name != "task_runtime.py"}
    worse = {n: (c, ALLOWED.get(n, 0)) for n, c in found.items() if c > ALLOWED.get(n, 0)}
    assert not worse, f"use task_runtime.Runtime instead of a new raw thread (found, allowed): {worse}"
