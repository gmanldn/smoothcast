"""#413/#414 (local slice): the Find tab contract and queue_add_key."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import library_folders as lf
import library_index_v2 as li
import portal
from cast_portal_queue import PortalQueueMixin
from test_room_conformance import RoomHarness


def page() -> str:
    return portal._page().decode("utf-8")


def test_find_section_is_labelled_and_announces_results():
    html = page()
    assert 'id="findInput"' in html and 'for="findInput"' in html
    assert 'id="findStatus" class="muted" role="status" aria-live="polite"' in html
    assert 'href="#findPanel"' in html and 'id="findResults"' in html
    # actions go through the existing authenticated, CSRF-protected post helper
    assert 'post("/api/action",{action:"queue_add_key",key:it.id})' in html
    # stale searches are cancelled and typing is debounced
    assert "source.close()" in html and "controller.abort()" in html and "setTimeout(run,120)" in html
    # all result text is inserted with textContent, never innerHTML
    find_js = html[html.index("const input=$(\"findInput\")"):]
    assert "innerHTML" not in find_js


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_script_is_valid_javascript(tmp_path):
    html = page()
    script = html[html.rindex("<script>") + len("<script>"):html.rindex("</script>")]
    path = tmp_path / "page.js"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


class Host(PortalQueueMixin):
    def __init__(self, tmp_path):
        self.lib = tmp_path / "lib"
        self.lib.mkdir()
        (self.lib / "Alien (1979).mkv").write_bytes(b"x" * 64)
        self._library_indexer = li.LibraryIndexer(tmp_path / "i.sqlite3", probe=lambda p: {})
        self._library_indexer.set_folders([lf.LibraryFolder("f_1", str(self.lib), "Films")])
        self._library_indexer.scan_all()
        self.key = next(iter(self._library_indexer.snapshot_page(None)[0]))["content_key"]
        self.queue, self.queue_durations, self.busy = [], {}, False
        self.enqueued = []

    def _enqueue(self, paths):
        self.enqueued += paths


def test_queue_add_key_resolves_inside_the_library_and_enqueues(tmp_path):
    host = Host(tmp_path)
    assert host._portal_queue_action("queue_add_key", {"key": host.key}) == "Added to the queue."
    assert host.enqueued == [str((host.lib / "Alien (1979).mkv").resolve())]


def test_queue_add_key_refuses_unknown_remote_and_escaped_paths(tmp_path):
    host = Host(tmp_path)
    with pytest.raises(portal.PortalRequestError) as unknown:
        host._portal_queue_action("queue_add_key", {"key": "qh:" + "0" * 32})
    assert unknown.value.status == 404 and "asleep" in unknown.value.message
    # a changed index row pointing outside the folder must be refused
    host._library_indexer._conn.execute(
        "UPDATE entries SET rel_path='../../../etc/passwd' WHERE content_key=?", (host.key,))
    host._library_indexer._conn.commit()
    with pytest.raises(portal.PortalRequestError) as escaped:
        host._portal_queue_action("queue_add_key", {"key": host.key})
    assert escaped.value.status == 404 and host.enqueued == []
    host.busy = True
    host._library_indexer._conn.execute(
        "UPDATE entries SET rel_path='Alien (1979).mkv' WHERE content_key=?", (host.key,))
    host._library_indexer._conn.commit()
    with pytest.raises(portal.PortalRequestError) as busy:
        host._portal_queue_action("queue_add_key", {"key": host.key})
    assert busy.value.status == 409


def test_queue_add_key_over_http_validates_key_and_requires_session():
    harness = RoomHarness(count=1)
    try:
        body = {"action": "queue_add_key", "key": "qh:" + "a" * 32}
        status, _, _ = harness.request("POST", "/api/action", body)
        assert status in (401, 403)
        guest = harness.login("Alice")
        for bad in ("../etc/passwd", "qh:short", 5, None, "qh:" + "G" * 32):
            status, reply, _ = guest.action({"action": "queue_add_key", "key": bad})
            assert status == 400, bad
        status, reply, _ = guest.action(body)
        assert status == 202
        assert harness.calls[-1][0] == "queue_add_key" and harness.calls[-1][1]["key"] == body["key"]
    finally:
        harness.close()


def test_add_button_is_enabled_for_any_online_copy_and_disabled_when_all_are_offline():
    html = page()
    assert 'if(!(it.copies||[]).some(c=>c.online)){add.disabled=true;add.title="Its computer is offline"}' in html
    assert "coming soon" not in html.split('const input=$("findInput")')[1]


def test_find_has_explicit_sources_and_recovery_controls():
    html = page()
    for ident in ("findForm", "findSubmit", "findClear", "findReset", "findEmpty", "findBrowse"):
        assert html.count(f'id="{ident}"') == 1
    assert 'role="search" aria-label="Search shared libraries"' in html
    assert 'id="youtubeSearch" type="button"' in html
    assert 'Searches your house as you type' in html
    assert 'input.dispatchEvent(new Event("input"));run()' in html
    assert 'if(ul.children.length)out.append(h,ul)' in html
    assert 'if(current!==generation||csrf!==session)return;' in html
    assert 'No currently available matches. Turn off Available now' in html



def test_find_open_torrents_are_explicit_and_use_existing_acquisition():
    html = page()
    for ident in ("magnetSearch", "magnetAuto", "magnetResultsPanel", "magnetAuthorised"):
        assert html.count(f'id="{ident}"') == 1
    assert 'type="checkbox"><span>Search open torrents as I type' in html
    assert 'setTimeout(()=>request(),850)' in html
    assert 'post("/api/search/magnets",{q:job.q})' in html
    assert 'url:"magnet:?xt=urn:btih:"+result.id' in html
    assert 'job.generation===generation&&csrf===job.session' in html
