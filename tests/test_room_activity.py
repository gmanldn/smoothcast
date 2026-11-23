"""Room activity feed (#332): safe titles on events and human sentences in the page."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal
import portal_room


def room_with(titles):
    room = portal_room.PortalRoom()
    sam = room.join("Sam")
    room.remember(titles)
    return room, sam


def last(room):
    return room.events[-1]


def test_actions_and_votes_carry_the_remembered_title():
    room, sam = room_with({"a1": "Heat"})
    room.record(sam.id, "action", {"action": "queue_remove", "id": "a1"})
    assert last(room)["data"]["title"] == "Heat"
    room.vote(sam.id, "a1", True)
    assert last(room)["data"]["title"] == "Heat" and last(room)["data"]["voted"] is True
    room.record(sam.id, "action", {"action": "queue_remove", "id": "unknown"})
    assert "title" not in last(room)["data"]


def test_titles_survive_removal_from_the_queue_but_votes_are_pruned():
    room, sam = room_with({"a1": "Heat"})
    room.vote(sam.id, "a1", True)
    room.prune(set())
    assert room.votes == {} and room.titles == {"a1": "Heat"}


def test_paths_are_never_remembered_and_titles_are_clean_and_bounded():
    room, _ = room_with({"p": "/home/sam/Videos/heat.mkv", "w": "C:\\Users\\sam\\heat.mkv",
                         "h": "~/heat.mkv", "ok": "  Heat \n (1995)\t", "long": "x" * 500, "empty": "  "})
    assert set(room.titles) == {"ok", "long"}
    assert room.titles["ok"] == "Heat (1995)" and len(room.titles["long"]) == portal_room.MAX_TITLE


def test_title_memory_is_bounded_and_forgets_oldest():
    room = portal_room.PortalRoom()
    room.remember({f"i{n}": f"Film {n}" for n in range(portal_room.MAX_TITLES + 50)})
    assert len(room.titles) == portal_room.MAX_TITLES
    assert "i0" not in room.titles and f"i{portal_room.MAX_TITLES + 49}" in room.titles


def _line(prefix):
    return next(line for line in portal._HTML.splitlines() if line.startswith(prefix))


def test_page_renders_the_feed_incrementally_in_a_polite_live_region():
    html = portal._HTML
    assert 'role="log" aria-live="polite" aria-relevant="additions"' in html
    assert "const activityLines=new Map()" in html
    assert 'activity.replaceChildren()' not in html  # replacing would re-announce every line


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_sentences_and_relative_times_in_node():
    script = (_line("function describe(event){") + "\n" + _line("function ago(at){") + "\n"
              "const ev=(type,data)=>({type,data});"
              "const out=[describe(ev('action',{name:'Sam',action:'queue_remove',title:'Heat'})),"
              "describe(ev('action',{name:'Sam',action:'queue_clear'})),"
              "describe(ev('action',{name:'Ana',action:'weird_thing'})),"
              "describe(ev('voted',{name:'Ana',title:'Heat',voted:true})),"
              "describe(ev('voted',{name:'Ana',voted:false})),"
              "describe(ev('joined',{name:'Bo'})),describe(ev('mystery',{})),describe({type:'action'})];"
              "const now=Date.now();Date.now=()=>now;"
              "out.push(ago(now/1000-5),ago(now/1000-300),ago(NaN));console.log(JSON.stringify(out));")
    got = json.loads(subprocess.run(["node", "-e", script], check=True, capture_output=True,
                                    text=True, timeout=8).stdout)
    assert got[:8] == [
        "Sam removed \u201cHeat\u201d", "Sam cleared Up Next", "Ana used weird thing",
        "Ana voted for \u201cHeat\u201d", "Ana removed a vote from an item", "Bo joined",
        "Someone updated the room", "Someone used a control"]
    assert got[8:] == ["just now", "5 min ago", ""]


def test_page_offers_a_category_filter_for_the_activity_feed():
    html = portal._HTML
    assert 'id="activityFilter"' in html and 'aria-controls="activity"' in html
    for value in ("all", "playback", "queue", "people", "problems"):
        assert f'<option value="{value}">' in html
    assert 'id="activityEmpty"' in html


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_activity_filter_categories_in_node():
    script = (_line("function activityMatches(event,filter){") + "\n"
              "const ev=(type,data)=>({type,data});"
              "const events={pause:ev('action',{action:'play_pause',outcome:'confirmed'}),"
              "add:ev('action',{action:'queue_add_key'}),vote:ev('voted',{voted:true}),"
              "join:ev('joined',{}),refused:ev('action',{action:'seek',outcome:'rejected'}),"
              "timeout:ev('action',{action:'queue_play',outcome:'uncertain'}),odd:ev('mystery',{})};"
              "const out={};for(const f of ['all','playback','queue','people','problems','bogus'])"
              "out[f]=Object.keys(events).filter(k=>activityMatches(events[k],f));"
              "out.noFilter=activityMatches(events.odd);console.log(JSON.stringify(out));")
    got = json.loads(subprocess.run(["node", "-e", script], check=True, capture_output=True,
                                    text=True, timeout=8).stdout)
    assert got["all"] == ["pause", "add", "vote", "join", "refused", "timeout", "odd"]
    assert got["playback"] == ["pause", "refused"]
    assert got["queue"] == ["add", "vote", "timeout"]
    assert got["people"] == ["join"]
    assert got["problems"] == ["refused", "timeout"]
    assert got["bogus"] == [] and got["noFilter"] is True
