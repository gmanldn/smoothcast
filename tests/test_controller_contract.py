"""Contract for every extracted MainWindow controller (#691), checked on source (no GTK import).

Each ``<X>Controller`` takes the window, exposes ``install``, and its ``*_METHODS`` tuple
names only methods it (or its listed base) really defines, with no duplicates."""
import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
CONTROLLERS = {  # module -> (class, methods tuple)
    "cast_av": ("AvController", "AV_CONTROLLER_METHODS"),
    "cast_queue": ("QueueController", "QUEUE_CONTROLLER_METHODS"),
    "cast_lifecycle": ("LifecycleController", "LIFECYCLE_METHODS"),
    "cast_discovery": ("DeviceDiscoveryController", "DEVICE_DISCOVERY_CONTROLLER_METHODS"),
    "cast_portal_queue": ("PortalQueueController", "PORTAL_QUEUE_METHODS"),
    "playlist_ui": ("PlaylistController", "PLAYLIST_CONTROLLER_METHODS"),
    "music_import_ui": ("MusicImportController", "MUSIC_IMPORT_CONTROLLER_METHODS"),
    "queue_row_ui": ("QueueRowController", "QUEUE_ROW_CONTROLLER_METHODS"),
    "queue_prewarm_ui": ("QueuePrewarmController", "QUEUE_PREWARM_CONTROLLER_METHODS"),
}
BASE_MODULES = {"LifecycleController": "cast_lifecycle_actions"}


def _methods(tree, cls_name):
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
    return cls, {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}


@pytest.mark.parametrize("module", sorted(CONTROLLERS))
def test_controller_contract(module):
    cls_name, tuple_name = CONTROLLERS[module]
    tree = ast.parse((SRC / f"{module}.py").read_text(encoding="utf-8"))
    cls, defined = _methods(tree, cls_name)
    for base in cls.bases:
        base_name = getattr(base, "id", "")
        if base_name.endswith("Controller"):
            base_tree = ast.parse((SRC / f"{BASE_MODULES[cls_name]}.py").read_text(encoding="utf-8"))
            defined |= _methods(base_tree, base_name)[1]
    assert "__init__" in defined and "install" in defined
    assign = next(n for n in tree.body if isinstance(n, ast.Assign)
                  and any(getattr(t, "id", "") == tuple_name for t in n.targets))
    names = list(ast.literal_eval(assign.value))
    assert names and len(names) == len(set(names)), "empty or duplicated method list"
    assert not [n for n in names if n not in defined], "lists methods the controller lacks"
