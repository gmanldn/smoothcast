"""The self-hosted screen page and dashboard panel stay valid and offline."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal
import portal_screen_page
import portal_screens


def _scripts(html: str) -> list[str]:
    return re.findall(r"<script>(.*?)</script>", html, flags=re.S)


def test_pages_are_self_contained_and_never_use_innerhtml():
    pages = {
        "screen": portal_screen_page.screen_page().decode(),
        "panel": portal_screen_page.panel_html(),
        "dashboard": portal._page().decode(),
    }
    for name, html in pages.items():
        # Only markup can pull in a subresource; scripts may build links at runtime.
        markup = re.sub(r"<script>.*?</script>", "", html, flags=re.S)
        assert not re.search(r"(?:src|href)=[\"']https?://", markup), name
        assert "innerHTML" not in html and "document.write" not in html, name
        assert "eval(" not in html, name
    assert "__MIMES__" not in pages["screen"]


def test_dashboard_embeds_the_panel_once_before_the_scripts_it_hooks():
    html = portal._page().decode()
    assert html.count('id="screensPanel"') == 1
    assert "window.scRenderScreens&&window.scRenderScreens(s)" in html
    assert html.index("</main>") > html.index('id="screensPanel"')


def test_every_capability_the_page_probes_is_known_to_the_server():
    html = portal_screen_page.screen_page().decode()
    listed = re.search(r"const MIMES=(\[.*?\]);", html).group(1)
    mimes = set(re.findall(r'"([a-z]+/[a-z0-9.+-]+)"', listed))
    assert mimes == set(portal_screens.KNOWN_MIMES)


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
@pytest.mark.parametrize("name", ["screen", "panel"])
def test_page_scripts_parse(name, tmp_path):
    html = (portal_screen_page.screen_page().decode() if name == "screen"
            else portal_screen_page.panel_html())
    for index, script in enumerate(_scripts(html)):
        target = tmp_path / f"{name}{index}.js"
        target.write_text(script, encoding="utf-8")
        result = subprocess.run(["node", "--check", str(target)],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr


def test_wake_lock_pip_and_dim_hint_contract():
    html = portal_screen_page.screen_page().decode()
    assert 'navigator.wakeLock.request("screen")' in html
    assert 'addEventListener("visibilitychange"' in html and "keepAwake()" in html
    assert 'id="pipButton"' in html and "document.pictureInPictureEnabled" in html
    assert "For an iPad on a stand, turn on Guided Access" in html


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_direct_decode_fallback_route_survives_seek_recovery_and_next_item(tmp_path):
    html = portal_screen_page.screen_page().decode()
    script = _scripts(html)[0]
    signatures = ("let transcoded=false,baseStart=0,activeUrl=null;", "function load(",
                  "function position(", "function seekTo(", "function stopPlayback(",
                  "function recover()")
    lines = script.splitlines()
    load_start = script.index("function load(")
    load_end = script.index("async function tryPlay(", load_start)
    load_code = script[load_start:load_end].strip()
    state_line = next(line for line in lines if line.startswith(signatures[0]))
    helpers = [line for line in lines if line.startswith(signatures[2:])]
    assert len(helpers) == len(signatures) - 2
    route_code = "\n".join([state_line, load_code, *helpers])
    harness = f'''\
let requests=[];
let current={{url:"https://host/play?id=first&mode=direct",fallback:"https://host/play?id=first&mode=transcode"}};
let recoverAt=0,stallTimer=null;
const READY="Ready",video={{src:"",currentTime:0,paused:false,
  load(){{requests.push(this.src)}},play(){{}},pause(){{this.paused=true}},
  removeAttribute(){{this.src=""}},addEventListener(){{}}}};
function clearTimeout(){{}}
function tryPlay(){{}}
function safe(fn){{try{{return fn()}}catch(_){{}}}}
function show(){{}}
function setSlate(){{}}
{route_code}
load(current.url,0,false);video.currentTime=38;
load(current.fallback,position(),true);
seekTo(90);video.currentTime=5;recover();
current={{url:"https://host/play?id=second&mode=direct",fallback:"https://host/play?id=second&mode=transcode"}};
load(current.url,0,false);
console.log(JSON.stringify(requests));
'''
    result = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    import json
    requests = json.loads(result.stdout)
    assert requests[0] == "https://host/play?id=first&mode=direct"
    assert requests[1:4] == [
        "https://host/play?id=first&mode=transcode&start=38",
        "https://host/play?id=first&mode=transcode&start=90",
        "https://host/play?id=first&mode=transcode&start=95",
    ]
    assert requests[4] == "https://host/play?id=second&mode=direct"


def test_idle_screen_shows_self_hosted_join_qr_and_safe_short_address():
    html = portal_screen_page.screen_page().decode()
    assert '<div class="stage" id="slate" hidden>' in html
    assert 'src="/join-qr.png"' in html
    assert 'id="joinAddress"' in html
    assert '$("joinAddress").textContent=location.host' in html
    assert "joinAddress\").innerHTML" not in html
    # Playing view and login remain independent from the idle QR slate.
    assert '<div id="player" hidden>' in html
    assert 'id="loginView" hidden' in html


def test_idle_join_code_is_a_corner_badge_when_queued_and_large_when_queue_empty():
    html = portal_screen_page.screen_page().decode()
    assert "#slate.corner .join-qr{position:fixed" in html
    assert "#slate.empty .join-qr img{width:min(320px" in html
    assert "function slateLayout(queueEmpty)" in html
    # False => something is queued (corner); true => nothing queued (large);
    # absent => keep the default centred layout.
    assert 'toggle("corner",queueEmpty===false)' in html
    assert 'toggle("empty",queueEmpty===true)' in html
    assert "slateLayout(d.queue_empty)" in html


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_poll_loop_resyncs_before_applying_orders_after_a_mailbox_gap():
    script = _scripts(portal_screen_page.screen_page().decode())[0]
    start = script.index("async function loop(){")
    loop_code = script[start:script.index("function banner(", start)]
    harness = f"""
const log=[];let seq=1,screenId="s1",started=true,stopped=false,polling=false,failures=0,current={{item:"aaa"}};
const POLL_TIMEOUT=1,READY="Ready";
const answers=[
  {{seq:20,queue_empty:false,resync:{{from:17}},
    orders:[{{kind:"play",seq:18,item:"bbb"}},{{kind:"pause",seq:19}}]}},
  {{seq:21,queue_empty:false,orders:[{{kind:"seek",seq:21,value:5}}]}}];
async function api(method,path){{log.push("poll "+path.split("?")[1].split("&")[0]);
  const d=answers.shift();if(!answers.length)stopped=true;return d}}
function stopPlayback(){{log.push("stop-local");current=null}}
function apply(o){{log.push("apply "+o.kind+"@"+o.seq)}}
function banner(){{}}function setSlate(){{}}function slateLayout(){{}}
function relogin(){{}}async function register(){{}}
{loop_code}
loop().then(()=>console.log(JSON.stringify({{log,seq}})));
"""
    result = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    import json
    got = json.loads(result.stdout)
    # Stale playback is torn down once, before B's order; nothing is applied to A.
    assert got["log"] == [
        "poll since=1", "stop-local", "apply play@18", "apply pause@19",
        "poll since=19", "apply seek@21",
    ]
    assert got["seq"] == 21

