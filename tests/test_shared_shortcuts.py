"""Desktop and web share the same shortcuts; keyboard changes are guarded."""
from pathlib import Path
import json
import shutil
import subprocess

import portal
import portal_commands
import shortcut_map


ROOT = Path(__file__).resolve().parents[1]


def test_single_source_maps_all_required_keys_to_both_surfaces():
    required = {" ", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "m", "n", "p", "?"}
    entries = json.loads(shortcut_map.browser_json())
    assert {entry["key"] for entry in entries} == required
    assert len({entry["action"] for entry in entries}) == len(entries)
    assert {item[0] for item in shortcut_map.desktop_labels()} == {
        "space", "Left", "Right", "Up", "Down", "m", "n", "p", "question",
    }
    gtk = (ROOT / "src" / "cast_ui.py").read_text()
    for item in shortcut_map.SHARED:
        assert 'add("' + item.desktop + '"' in gtk, item.desktop
    # The shortcuts action lives in the lifecycle-actions mixin after the
    # #634 split.
    lifecycle = (ROOT / "src" / "cast_lifecycle_actions.py").read_text()
    assert "shortcut_map.desktop_labels()" in lifecycle
    html = portal._page().decode("utf-8")
    assert "__SC_SHORTCUTS__" not in html
    assert '"key":"ArrowLeft"' in html
    assert 'id="shortcutsHelp"' in html
    assert "showShortcutHelp()" in html


def test_web_key_handler_protects_inputs_focus_permissions_and_busy_state():
    html = portal._HTML
    assert 'event.target.closest("input,textarea,select,button,[contenteditable],[role=textbox],[role=slider]")' in html
    for guard in ("event.defaultPrevented", "event.repeat", "event.isComposing",
                  "event.ctrlKey", "event.metaKey", "event.altKey", "stalePage"):
        assert guard in html
    assert "if(!state||state.busy||!state.active)return null;" in html
    assert 'if(!state.can_seek||!Number.isFinite(state.duration)' in html
    assert 'if(state.volume==null||!Number.isFinite(volume))return null;' in html
    assert "event.preventDefault()" in html
    assert 'if(shortcut.action==="help")' in html
    assert "shortcutMap.get(key)" in html
    assert "typeof __SC_SHORTCUTS__" in html
    if shutil.which("node"):
        start = html.index("function shortcutCommand(")
        # Stop before the extra-transport wiring, which runs at page load and
        # needs the page scope; this harness exercises the pure function only.
        end = html.index("const extraTransportClient", start)
        function = html[start:end]
        runner = function + """
const good={active:true,busy:false,can_seek:true,duration:7500,volume:50};
const outputs=[
  shortcutCommand("seek_back",good,4,50),
  shortcutCommand("seek_forward",good,7495,50),
  shortcutCommand("volume_up",good,4,98),
  shortcutCommand("volume_down",good,4,1),
  shortcutCommand("mute",{...good,volume:null},4,50),
  shortcutCommand("seek_back",{...good,can_seek:false},4,50),
  shortcutCommand("next",{...good,busy:true},4,50),
  shortcutCommand("play_pause",good,4,50)
];
console.log(JSON.stringify(outputs));
"""
        x = subprocess.run(["node", "-e", runner], capture_output=True,
                           text=True, check=True, timeout=5)
        assert json.loads(x.stdout) == [
            {"action": "seek", "value": 0},
            {"action": "seek", "value": 7500},
            {"action": "volume", "value": 100},
            {"action": "volume", "value": 0},
            None, None, None, {"action": "play_pause"},
        ]


def test_browser_js_has_no_syntax_errors_when_node_is_available():
    if not shutil.which("node"):
        return
    html = portal._page().decode("utf-8")
    source = html.rsplit("<script>", 1)[1].split("</script>", 1)[0]
    subprocess.run(["node", "--check"], input=source, capture_output=True,
                   text=True, check=True, timeout=5)


def test_mute_is_authorized_and_rejected_when_receiver_offline():
    from types import SimpleNamespace
    fence = portal_commands.CommandFence()
    session, revision, _ = fence.snapshot()
    call = []
    controller = SimpleNamespace(
        _closing=False, busy=False, device_state="PLAYING",
        _volume_control_available=lambda: True,
        _device=lambda: "", toggle_mute=lambda: call.append("mute"),
    )
    command = portal_commands.MutationEnvelope(
        client_id="guest", command_id="mute-1",
        expected_session_id=session, expected_revision=revision,
        action="mute", payload={},
    )
    result = portal_commands.run_mutation(controller, fence, command)
    assert result.command_id == "mute-1"
    assert call == ["mute"]
    controller.device_state = "OFFLINE"
    try:
        portal_commands.run_mutation(controller, fence, command)
    except portal_commands.CommandError as error:
        assert error.status == 409
    else:
        raise AssertionError("Offline receiver accepted mute")
    assert call == ["mute"]
    assert "mute" in portal_commands.ACTIONS
