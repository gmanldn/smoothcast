"""Web remote SSE client (#526): stream first, polling fallback, bounded reconnects."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal


def _factory() -> str:
    start = portal._HTML.index("function makeRoomEvents(env){")
    end = portal._HTML.index("const roomEvents=makeRoomEvents({", start)
    return portal._HTML[start:end]


HARNESS = """
const assert = require("node:assert/strict");
let clock = 0, timerId = 0, fallbacks = 0, applied = [], canRun = true, sources = [];
const timers = new Map(), intervals = new Map();
class FakeSource {
  constructor(url){this.url=url;this.closed=false;this.listeners={};sources.push(this)}
  addEventListener(name, fn){this.listeners[name]=fn}
  close(){this.closed=true}
  emit(data){this.listeners.state({data:typeof data==="string"?data:JSON.stringify(data)})}
}
const env = {
  EventSource: FakeSource, now: () => clock, canRun: () => canRun,
  apply: d => applied.push(d), fallback: () => { fallbacks++; },
  setTimeout: (f, ms) => { timers.set(++timerId, {f, ms}); return timerId; },
  clearTimeout: id => timers.delete(id),
  setInterval: (f, ms) => { intervals.set(++timerId, {f, ms}); return timerId; },
  clearInterval: id => intervals.delete(id),
};
"""


def run(scenario: str) -> None:
    subprocess.run(["node", "-"], input=HARNESS + _factory() + scenario, text=True, check=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_stream_renders_events_and_stops_polling():
    run("""
const ev = makeRoomEvents(env);
assert.equal(ev.healthy(), false);
ev.start(); ev.start();
assert.equal(sources.length, 1, "start is idempotent");
assert.equal(sources[0].url, "/api/events");
assert.equal(ev.healthy(), false, "healthy only after the first event");
sources[0].emit({ok:true,state:{title:"A"}});
assert.equal(ev.healthy(), true);
assert.deepEqual(applied, [{ok:true,state:{title:"A"}}]);
sources[0].emit("not json");
assert.equal(applied.length, 1, "malformed events are ignored");
assert.equal(fallbacks, 0);
""")


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_error_falls_back_to_polling_and_retries_with_capped_backoff():
    run("""
const ev = makeRoomEvents(env);
ev.start(); sources[0].emit({n:1});
sources[0].onerror();
assert.equal(sources[0].closed, true); assert.equal(ev.healthy(), false);
assert.equal(fallbacks, 1);
const delays = [];
for (let i = 0; i < 7; i++) {
  const [[id, t]] = [...timers.entries()];
  delays.push(t.ms); timers.delete(id); t.f();
  sources[sources.length - 1].onerror();
}
assert.deepEqual(delays, [1000, 2000, 4000, 8000, 15000, 15000, 15000]);
sources[sources.length - 1].emit({n:2});
sources[sources.length - 1].onerror();
assert.equal([...timers.values()][0].ms, 1000, "a healthy event resets the backoff");
""")


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_silent_stream_is_replaced_by_polling_after_30_seconds():
    run("""
const ev = makeRoomEvents(env);
ev.start(); sources[0].emit({n:1});
const [watch] = [...intervals.values()];
clock = 29000; watch.f(); assert.equal(ev.healthy(), true);
clock = 31001; watch.f(); assert.equal(ev.healthy(), false);
assert.equal(fallbacks, 1); assert.equal(sources[0].closed, true);
assert.equal(intervals.size, 0, "watchdog is cleared");
""")


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_hidden_tab_or_expired_session_closes_the_stream_and_blocks_restart():
    run("""
const ev = makeRoomEvents(env);
ev.start(); sources[0].emit({n:1});
ev.stop();
assert.equal(sources[0].closed, true); assert.equal(ev.healthy(), false);
assert.equal(timers.size, 0); assert.equal(intervals.size, 0);
canRun = false; ev.start();
assert.equal(sources.length, 1, "no stream while hidden or signed out");
ev.start && (canRun = true, ev.start());
assert.equal(sources.length, 2);
sources[1].emit({n:3}); canRun = false; sources[1].onerror();
assert.equal(fallbacks, 0, "no polling fallback when the page may not run");
assert.equal(timers.size, 0);
""")


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_without_event_source_support_nothing_starts():
    run("""
const ev = makeRoomEvents({...env, EventSource: null});
ev.start();
assert.equal(sources.length, 0); assert.equal(ev.healthy(), false);
""")


def test_page_wires_the_stream_into_the_existing_poll_and_lifecycle():
    html = portal._HTML
    assert "function applyStatus(d){" in html and "if(applyStatus(d)===false)return;" in html
    assert "roomEvents.healthy())return;" in html  # polling pauses while the stream is healthy
    assert 'statusRequest?.abort("superseded");roomEvents.stop();return}' in html
    assert "function expireSession(){" in html
    expired = html.split("function expireSession(){", 1)[1].split("function clock(s){", 1)[0]
    assert 'csrf="";' in expired and "roomEvents.stop();" in expired
    assert "apply:d=>{if(!busy)applyStatus(d)}" in html
