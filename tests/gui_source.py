"""Source/AST access for tests that assert on the GUI module set.

``cast_control.py`` was split into ``cast_widgets.py`` (shared constants, config
helpers, custom widgets) plus one mixin module per concern (``cast_ui``,
``cast_queue``, ``cast_session``, ``cast_av``, ``cast_lifecycle`` and focused
UI mixins). ``MainWindow``
now inherits those mixins, so the GUI source a test cares about is spread across
files.

This helper keeps the existing source-text and AST assertions working without
each test knowing the module layout:

* :func:`combined_source` - every GUI module concatenated, for substring checks.
* :func:`main_window_source` - a synthetic ``class MainWindow`` reassembling
  ``MainWindow`` plus every mixin method, so AST lookups still find them.
* :func:`main_window_methods` - ``{method name: source}`` for that synthetic class.

Pure text/AST only: never imports GTK or starts a window.
"""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Order matters only for readability; combined_source() joins them in this order.
GUI_MODULES = (
    "cast_widgets.py",
    "bookmark_ui.py",
    "cast_ui.py",
    "panel_ui.py",
    "cast_settings.py",
    "preferences_ui.py",
    "library_folders_ui.py",
    "cast_queue.py",
    "queue_row_ui.py",
    "cast_session.py",
    "cast_av.py",
    "cast_subtitle_files.py",
    "cast_lifecycle.py",
    "room_checkpoint_ui.py",
    "cast_portal_queue.py",
    "cast_portal_host.py",
    "portal_upload_recovery.py",
    "cast_portal.py",
    "cast_subtitles.py",
    "cast_audio_sync.py",
    "cast_control.py",
)

# Mixin classes that contribute MainWindow methods.
MIXIN_CLASSES = ("UiMixin", "BookmarkUiMixin", "SettingsCardMixin", "QueueMixin", "QueueRowMixin", "SessionMixin", "AvMixin", "SubtitleFileMixin", "LifecycleMixin", "RoomCheckpointUiMixin", "PortalUploadRecoveryMixin", "PortalMixin", "PortalHostMixin", "PortalQueueMixin", "SubtitleMixin", "AudioSyncMixin")


def gui_paths() -> tuple[Path, ...]:
    return tuple(ROOT / "src" / name for name in GUI_MODULES)


def module_sources() -> list[str]:
    return list(_module_sources())


@lru_cache(maxsize=1)
def _module_sources() -> tuple[str, ...]:
    """Read the fixed GUI source snapshot once per pytest process."""
    return tuple(path.read_text(encoding="utf-8") for path in gui_paths())


def combined_source() -> str:
    """All GUI module source concatenated (valid Python when parsed)."""
    return "\n\n\n".join(module_sources())


def _main_window_method_nodes():
    yield from _cached_main_window_method_nodes()


@lru_cache(maxsize=1)
def _cached_main_window_method_nodes():
    """Yield (source, node, segment) for MainWindow and every mixin method.

    ``segment`` keeps the original indentation, unlike ``ast.get_source_segment``
    which strips the first line's leading whitespace.
    """
    methods = []
    for path, source in zip(gui_paths(), _module_sources()):
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines(keepends=True)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != "MainWindow" and node.name not in MIXIN_CLASSES:
                continue
            for method in node.body:
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    segment = "".join(lines[method.lineno - 1:method.end_lineno])
                    methods.append((source, method, segment))
    return tuple(methods)


def main_window_source() -> str:
    """Synthetic ``class MainWindow`` holding every GUI method body."""
    return _cached_main_window_source()


@lru_cache(maxsize=1)
def _cached_main_window_source() -> str:
    parts = ["class MainWindow:"]
    for _source, _node, segment in _main_window_method_nodes():
        parts.append(segment.rstrip("\n"))
    return "\n".join(parts) + "\n"


def main_window_tree() -> ast.Module:
    return ast.parse(main_window_source())


def main_window_methods() -> dict[str, str]:
    """``{method name: exact source segment}`` for the reassembled MainWindow."""
    return dict(_cached_main_window_methods())


@lru_cache(maxsize=1)
def _cached_main_window_methods() -> dict[str, str]:
    source = main_window_source()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
            return {
                method.name: ast.get_source_segment(source, method)
                for method in node.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return {}
