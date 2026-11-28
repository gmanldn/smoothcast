"""Self-hosted HTML for room screens: the ``/screen`` page and the dashboard panel.

No external assets, fonts or CDNs: both pages are served by the room itself.
Text reaches the DOM only through ``textContent``/attributes, never ``innerHTML``.
"""
from __future__ import annotations

import design_tokens
import version

KNOWN_MIMES_JS = (
    '["video/mp4","video/webm","video/x-matroska","video/ogg","audio/mpeg",'
    '"audio/mp4","audio/aac","audio/flac","audio/ogg","audio/wav"]'
)


def screen_page() -> bytes:
    return (_SCREEN_HTML.replace("__MIMES__", KNOWN_MIMES_JS)
            .replace("__SC_VERSION__", version.identity_label())
            .replace("/*TOKENS*/", design_tokens.css())).encode("utf-8")


def panel_html() -> str:
    """Dashboard section + script, composed inside the joined room grid."""
    return _PANEL_HTML


_SCREEN_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark light"><meta name="theme-color" content="#101722" media="(prefers-color-scheme: dark)"><meta name="theme-color" content="#f4f7fb" media="(prefers-color-scheme: light)">
<title>SmoothCast Screen</title>
<style>/*TOKENS*/
:root{font:16px system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);overflow:hidden;-webkit-tap-highlight-color:transparent}
[hidden]{display:none!important}
.stage{position:fixed;inset:0;display:grid;justify-items:center;align-items:start;align-items:safe center;overflow:auto;padding:max(20px,env(safe-area-inset-top)) max(20px,env(safe-area-inset-right)) max(20px,env(safe-area-inset-bottom)) max(20px,env(safe-area-inset-left))}
.card{width:min(30rem,100%);background:var(--card);border:1px solid var(--line);border-radius:22px;padding:28px;box-shadow:0 24px 60px rgba(0,0,0,.5)}
.brand{display:flex;align-items:center;gap:12px;margin-bottom:6px}
.logo{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,var(--accent),var(--vote-on));display:grid;place-items:center;font-weight:800;color:var(--on-accent);font-size:1.25rem}
h1{font-size:1.35rem;margin:0;letter-spacing:-.02em}p{color:var(--muted);line-height:1.5;margin:.5rem 0}
label{display:block;margin:16px 0 6px;font-size:.9rem;color:var(--muted)}
input{width:100%;min-height:52px;font:inherit;color:var(--text);background:var(--input);border:1px solid var(--border);border-radius:14px;padding:10px 14px}
#pin{letter-spacing:.3em;font-size:1.3rem;text-align:center}
button{font:inherit;font-weight:700;min-height:52px;border:0;border-radius:14px;padding:0 22px;color:var(--on-accent);background:var(--accent);cursor:pointer;width:100%;margin-top:18px}
button:disabled{opacity:.65;cursor:wait}
button.ghost{background:var(--nav);color:var(--on-nav);width:auto;margin:0;min-height:44px;padding:0 16px}
button:focus-visible,input:focus-visible{outline:3px solid var(--focus);outline-offset:3px}
.err{color:var(--danger);min-height:1.4em;margin:.6rem 0 0}
.big{font-size:clamp(1.6rem,5vw,2.6rem);font-weight:750;letter-spacing:-.03em;margin:0;display:flex;align-items:center;justify-content:center;gap:.6rem}
.slate{text-align:center;max-width:44rem}
.join-qr{margin:24px auto 0;max-width:min(26rem,90vw);display:grid;justify-items:center;gap:4px}
.join-qr img{display:block;width:min(180px,36vw);height:auto;aspect-ratio:1;background:var(--qr-paper);border:8px solid var(--qr-paper);border-radius:10px}
.join-qr strong{color:var(--text);overflow-wrap:anywhere}
/* Idle with items still queued: small corner code. Queue empty: large centred code (#420). */
#slate.corner .join-qr{position:fixed;right:max(16px,env(safe-area-inset-right));bottom:max(16px,env(safe-area-inset-bottom));margin:0;max-width:11rem;font-size:.8rem;text-align:center}
#slate.corner .join-qr img{width:min(96px,24vw);border-width:5px}
#slate.corner .join-qr p{margin:0}
#slate.empty .join-qr{max-width:min(40rem,94vw)}
#slate.empty .join-qr img{width:min(320px,42vh,70vw)}
#slate.empty .join-qr p{font-size:clamp(1.1rem,2.4vw,1.6rem)}
.dot{display:inline-block;flex:none;width:.7rem;height:.7rem;border-radius:50%;background:var(--accent);box-shadow:0 0 0 0 color-mix(in srgb,var(--accent) 40%,transparent);animation:pulse 2.4s infinite}
.dot.bad{background:var(--danger);animation:none}.dot.warn{background:var(--focus);animation:none}
@keyframes pulse{70%{box-shadow:0 0 0 12px transparent}100%{box-shadow:0 0 0 0 transparent}}
#player{position:fixed;inset:0;background:rgb(0,0,0)}
video{width:100%;height:100%;object-fit:contain;background:rgb(0,0,0)}
#audioArt{position:absolute;inset:0;display:grid;place-items:center;align-content:center;gap:18px;background:radial-gradient(circle at 50% 35%,var(--vote),var(--bg) 70%);padding:24px;text-align:center}
.bars{display:flex;gap:7px;align-items:flex-end;height:64px}.bars i{width:9px;border-radius:5px;background:var(--accent);height:20%;animation:eq 1.1s ease-in-out infinite}
.bars i:nth-child(2){animation-delay:.15s}.bars i:nth-child(3){animation-delay:.3s}.bars i:nth-child(4){animation-delay:.45s}.bars i:nth-child(5){animation-delay:.6s}
.paused .bars i{animation-play-state:paused}
@keyframes eq{50%{height:100%}}
@media(prefers-reduced-motion:reduce){.bars i,.dot{animation:none}}
#hud{position:absolute;left:0;right:0;bottom:0;padding:16px max(22px,env(safe-area-inset-right)) max(20px,env(safe-area-inset-bottom)) max(22px,env(safe-area-inset-left));background:var(--media-surface);color:var(--media-text);transition:opacity .3s}
#hud.hide{opacity:0;pointer-events:none}
#hud .title{font-size:1.15rem;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#hud .meta{display:flex;justify-content:space-between;gap:12px;color:var(--media-text);font-size:.9rem;margin-top:6px}
.bar{height:6px;border-radius:3px;background:rgba(255,255,255,.2);margin-top:10px;overflow:hidden}.bar>i{display:block;height:100%;width:0;background:var(--accent)}
#banner{position:absolute;top:max(76px,calc(env(safe-area-inset-top) + 62px));left:50%;transform:translateX(-50%);background:var(--media-surface);color:var(--media-text);border:1px solid var(--media-text);border-radius:999px;padding:8px 16px;font-size:.9rem;max-width:90vw;text-align:center}
#tools{position:absolute;top:max(14px,env(safe-area-inset-top));right:max(14px,env(safe-area-inset-right));display:flex;gap:8px;transition:opacity .3s}
#tools.hide{opacity:0;pointer-events:none}#tools.hide:focus-within{opacity:1;pointer-events:auto}
/* #591: Home back to the room on every view; during untouched video it fades
   with the other tools and returns on any pointer, key or focus. */
.home-link{position:fixed;z-index:40;top:max(14px,env(safe-area-inset-top));left:max(14px,env(safe-area-inset-left));display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:0 18px 0 13px;border-radius:999px;background:var(--accent);color:var(--on-accent);font-weight:750;text-decoration:none;box-shadow:0 8px 22px rgba(0,0,0,.35);transition:opacity .3s}
.home-link svg{width:22px;height:22px;fill:currentColor}
.home-link.hide{opacity:0;pointer-events:none}.home-link:focus-visible{opacity:1;pointer-events:auto;outline:3px solid var(--focus);outline-offset:3px}
.screen-version{position:fixed;z-index:40;top:max(24px,calc(env(safe-area-inset-top) + 10px));left:calc(max(14px,env(safe-area-inset-left)) + 118px);max-width:calc(100vw - 150px);font-size:.74rem;font-weight:650;color:var(--muted);background:var(--card);border:1px solid var(--line);border-radius:999px;padding:3px 9px;white-space:normal;line-height:1.2;text-align:center;transition:opacity .3s}
.screen-version.hide{opacity:0}
/* Reserve the corner so Home and the version never cover a card or the slate. */
.stage{padding-top:max(80px,calc(env(safe-area-inset-top) + 70px))}
/* On a phone, keep video tools clear of the Home/version strip. */
@media(max-width:600px){
  #tools{top:max(68px,calc(env(safe-area-inset-top) + 54px));flex-wrap:wrap;justify-content:flex-end;max-width:calc(100% - 28px)}
  #banner{top:max(172px,calc(env(safe-area-inset-top) + 158px));width:max-content;max-width:calc(100% - 28px);overflow-wrap:anywhere;border-radius:14px}
  .card{padding:20px}
}
@media(prefers-reduced-motion:reduce){#hud,#tools,.home-link,.screen-version{transition:none}}
@media(forced-colors:active){.home-link{border:2px solid ButtonText}}
</style></head><body>
<a class="home-link" id="homeLink" href="/" title="Back to the SmoothCast room"><svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M12 3.2 2.6 11a1 1 0 0 0 1.3 1.5l.8-.7V20a1 1 0 0 0 1 1h4.3v-5.5h4v5.5h4.3a1 1 0 0 0 1-1v-8.2l.8.7a1 1 0 1 0 1.3-1.5z"/></svg><span>Home</span></a><span class="sc-version screen-version" id="scVersion" aria-label="Host version __SC_VERSION__">__SC_VERSION__</span>
<div class="stage" id="loginView" hidden><form class="card" id="loginForm" autocomplete="off">
<div class="brand"><div class="logo" aria-hidden="true">S</div><h1>Make this a SmoothCast screen</h1></div>
<p>Play movies and music from the room on this device. Nothing to install.</p>
<label for="name">Name this screen</label><input id="name" maxlength="32" placeholder="Living room TV" required>
<label for="pin">House PIN shown in SmoothCast</label><input id="pin" inputmode="numeric" maxlength="6" pattern="[0-9]{6}" autocomplete="one-time-code" required>
<p class="err" id="loginError" role="alert"></p><button id="loginSubmit" type="submit">Join the room</button></form></div>

<div class="stage" id="startView" hidden><div class="card">
<div class="brand"><div class="logo" aria-hidden="true">S</div><h1 id="startName">Screen</h1></div>
<p>One tap lets this browser play sound and video when the room sends it something. You can leave it running; it reconnects by itself.</p>
<p class="err" id="startError" role="alert"></p><button id="startButton" type="button">Start screen</button></div></div>

<div class="stage" id="slate" hidden><div class="slate">
<p class="big"><span class="dot" id="dot"></span><span id="slateName">Screen</span></p>
<p id="slateText" role="status" aria-live="polite">Ready. Pick something in the room to play it here.</p>
<div class="join-qr" aria-label="Join this SmoothCast room">
<img src="/join-qr.png" width="180" height="180" alt="Scan this QR code to join the room on your phone">
<p>Or open <strong id="joinAddress"></strong> on the same Wi-Fi network.</p>
</div>
<p><button class="ghost" id="fsSlate" type="button">Full screen</button></p></div></div>

<div id="player" hidden><video id="video" playsinline preload="auto"></video>
<div id="audioArt" hidden><div class="bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div><p class="big" id="audioTitle"></p></div>
<div id="banner" role="status" aria-live="polite" hidden></div>
<div id="tools"><button class="ghost" id="fsButton" type="button">Full screen</button><button class="ghost" id="pipButton" type="button" hidden>Picture in picture</button></div>
<div id="hud"><div class="title" id="hudTitle"></div><div class="bar"><i id="hudBar"></i></div>
<div class="meta"><span id="hudState"></span><span id="hudTime"></span></div></div></div>

<script>
const MIMES=__MIMES__;
const READY="Ready. Pick something in the room to play it here.";
const $=id=>document.getElementById(id);
// Short address is text, never HTML; the QR contains the bound numeric endpoint.
$("joinAddress").textContent=location.host;
let csrf="",screenId="",seq=0,playSeq=0,current=null,started=false,polling=false,stopped=false;
let joining=false,starting=false;
let failures=0,lastReport=0,lastState="",hideTimer=null,wakeLock=null,fallbackTried=false,recoverAt=0,stallTimer=null;
const video=$("video");
const safe=(fn)=>{try{return fn()}catch(_){return undefined}};
const store={get:k=>safe(()=>localStorage.getItem(k))||"",set:(k,v)=>safe(()=>localStorage.setItem(k,v))};
function show(...ids){for(const id of["loginView","startView","slate","player"])$(id).hidden=!ids.includes(id)}
function clock(s){s=Math.max(0,Math.floor(Number(s)||0));const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return(h?h+":"+String(m).padStart(2,"0"):m)+":"+String(s%60).padStart(2,"0")}
function capabilities(){return MIMES.filter(m=>{const el=m.startsWith("video")?video:document.createElement("audio");return !!safe(()=>el.canPlayType(m))})}
const REQUEST_TIMEOUT=8000,POLL_TIMEOUT=12000;
async function requestJSON(path,options,timeout=REQUEST_TIMEOUT){
  const controller=new AbortController();
  let timer;
  const deadline=new Promise((_,reject)=>{
    timer=setTimeout(()=>{
      reject(Error("The room did not respond. Check your connection and try again."));
      controller.abort();
    },timeout);
  });
  try{return await Promise.race([deadline,(async()=>{
    const r=await fetch(path,{...options,signal:controller.signal});
    let d={};try{d=await r.json()}catch(err){if(r.ok)throw err}
    if(!r.ok)throw Object.assign(Error(d.error||"Request failed"),{status:r.status});
    return d;
  })()])}
  finally{clearTimeout(timer)}
}
async function api(method,path,body,timeout=REQUEST_TIMEOUT){
  const headers={};if(body!==undefined)headers["Content-Type"]="application/json";if(method!=="GET")headers["X-CSRF-Token"]=csrf;
  return requestJSON(path,{method,credentials:"same-origin",cache:"no-store",headers,body:body===undefined?undefined:JSON.stringify(body)},timeout)
}
async function login(e){
  e.preventDefault();if(joining)return;joining=true;
  const button=$("loginSubmit");button.disabled=true;button.textContent="Joining…";
  $("loginError").textContent="";const name=$("name").value.trim(),pin=$("pin").value.trim();
  try{const d=await requestJSON("/api/login",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({pin,name})});
    if(!d.csrf)throw Error("Invalid room response. Please try again.");csrf=d.csrf;store.set("sc_screen_name",name);$("pin").value="";await enter(name)}
  catch(err){$("loginError").textContent=err.message||"Could not join. Please try again."}
  finally{joining=false;button.disabled=false;button.textContent="Join the room"}}
async function enter(name){
  $("startName").textContent=name;$("slateName").textContent=name;$("startError").textContent="";show("startView");
  if(started)await begin();}
async function register(){
  const name=$("slateName").textContent||"Screen";
  const d=await api("POST","/api/screens",{name,capabilities:capabilities(),claim:safe(()=>sessionStorage.getItem("sc_screen_id"))||undefined});
  screenId=d.screen.id;seq=d.screen.seq;playSeq=d.screen.play_seq;$("slateName").textContent=d.screen.name;
  safe(()=>sessionStorage.setItem("sc_screen_id",screenId))}
async function begin(){
  if(starting||started)return;
  starting=true;const button=$("startButton");button.disabled=true;button.textContent="Connecting…";
  $("startError").textContent="";
  try{await register()}
  catch(err){if(err.status===401||err.status===403){relogin();return}
    $("startError").textContent="Could not start this screen. Check your connection and try again.";
    return}
  finally{starting=false;button.disabled=false;button.textContent="Start screen"}
  started=true;stopped=false;show("slate");setSlate(READY,"ok");keepAwake();loop();heartbeat()}
function relogin(){csrf="";screenId="";started=false;show("loginView");$("loginError").textContent="Your session ended. Enter the room PIN again."}
function slateLayout(queueEmpty){$("slate").classList.toggle("corner",queueEmpty===false);$("slate").classList.toggle("empty",queueEmpty===true)}
function setSlate(text,tone){$("slateText").textContent=text;$("dot").className="dot"+(tone==="bad"?" bad":tone==="warn"?" warn":"")}
const DIM_HINT="Your browser may still dim the screen. For an iPad on a stand, turn on Guided Access in its Settings to keep it awake.";
function dimHint(){if(store.get("sc_dim_hint"))return;store.set("sc_dim_hint","1");banner(DIM_HINT);setTimeout(()=>{if($("banner").textContent===DIM_HINT)banner("")},9000)}
async function keepAwake(){if(!("wakeLock"in navigator)){dimHint();return}try{wakeLock=await navigator.wakeLock.request("screen");wakeLock.addEventListener("release",()=>{wakeLock=null})}catch(_){dimHint()}}
if(safe(()=>document.pictureInPictureEnabled&&video.requestPictureInPicture)){$("pipButton").hidden=false;$("pipButton").addEventListener("click",e=>{e.stopPropagation();safe(()=>document.pictureInPictureElement?document.exitPictureInPicture():video.requestPictureInPicture())})}
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&started&&!wakeLock)keepAwake()});
async function loop(){
  if(polling)return;polling=true;
  while(started&&!stopped){
    try{const d=await api("GET",`/api/screens/${screenId}/poll?since=${seq}&wait=8`,undefined,POLL_TIMEOUT);
      if(failures){failures=0;banner("");if(!current)setSlate(READY,"ok")}
      if(d.resync){seq=d.resync.from;stopPlayback()}
      for(const o of d.orders){if(o.seq>seq){seq=o.seq;apply(o)}}
      slateLayout(d.queue_empty)
    }catch(err){
      if(err.status===401||err.status===403){polling=false;return relogin()}
      if(err.status===404){try{await register();continue}catch(registerError){if(registerError.status===401||registerError.status===403){polling=false;return relogin()}}}
      failures++;banner("Reconnecting to the room…");if(!current)setSlate("Reconnecting to the room…","warn");
      await new Promise(r=>setTimeout(r,Math.min(10000,500*2**Math.min(failures,5))))}}
  polling=false}
function banner(text){const b=$("banner");b.textContent=text;b.hidden=!text}
function apply(o){
  if(o.kind==="play"){playSeq=o.seq;current={...o,fell:false};fallbackTried=false;recoverBudget=2;lastPosition=0;load(o.url,o.start||0,o.route&&o.route.mode==="transcode");
    $("hudTitle").textContent=o.title;$("audioTitle").textContent=o.title;
    const audio=o.route&&o.route.kind==="audio";video.style.visibility=audio?"hidden":"visible";$("audioArt").hidden=!audio;
    show("player");banner("");wake()}
  else if(o.kind==="pause"){video.pause()}
  else if(o.kind==="resume"){tryPlay()}
  else if(o.kind==="seek"&&current){seekTo(o.value)}
  else if(o.kind==="volume"){video.volume=o.value/100}
  else if(o.kind==="stop"){playSeq=o.seq;stopPlayback()}
  report(true,o.seq)}
let transcoded=false,baseStart=0,activeUrl=null,recoverBudget=2,lastPosition=0;
function load(url,start,convert){
  activeUrl=url;transcoded=!!convert;baseStart=start||0;clearTimeout(stallTimer);
  const src=convert?url+(url.includes("?")?"&":"?")+"start="+encodeURIComponent(baseStart):url;
  video.src=src;video.load();
  if(!convert&&baseStart){video.addEventListener("loadedmetadata",()=>{safe(()=>{video.currentTime=baseStart})},{once:true})}
  tryPlay()}
async function tryPlay(){try{await video.play()}catch(err){if(err&&err.name==="NotAllowedError"){banner("Tap the screen to start playback")}}}
function position(){return transcoded?baseStart+(video.currentTime||0):(video.currentTime||0)}
function seekTo(t){t=Math.max(0,Number(t)||0);if(transcoded){load(activeUrl,t,true)}else{safe(()=>{video.currentTime=t})}}
function stopPlayback(){current=null;activeUrl=null;transcoded=false;baseStart=0;clearTimeout(stallTimer);recoverBudget=0;video.pause();video.removeAttribute("src");video.load();show("slate");setSlate(READY,"ok")}
document.addEventListener("click",()=>{if(current&&video.paused&&!$("banner").hidden)tryPlay();wake()});
function state(){
  if(!current)return"idle";if(video.error)return"error";if(video.ended)return"ended";
  if(video.paused)return video.readyState<3&&video.currentTime===0?"loading":"paused";
  return video.readyState<3?"buffering":"playing"}
async function report(force,ack){
  if(!screenId||!csrf)return;const s=state(),now=Date.now();
  if(!force&&s===lastState&&now-lastReport<2000)return;lastReport=now;lastState=s;
  const body={state:s,position:position(),duration:(current&&current.duration)||(isFinite(video.duration)&&!transcoded?video.duration:0),volume:Math.round(video.volume*100),play_seq:playSeq};
  if(ack!==undefined)body.ack=ack;
  if(s==="error")body.error=errorText();
  const session=csrf;try{await api("POST",`/api/screens/${screenId}/report`,body)}catch(err){if(csrf===session&&(err.status===401||err.status===403))relogin()}}
function errorText(){const c=video.error&&video.error.code;return c===3||c===4?"This device cannot decode that file":c===2?"Network problem while loading":"Playback failed"}
let beat=null;function heartbeat(){if(!beat)beat=setInterval(()=>{if(started)report(false);hud()},1000)}
function hud(){
  if(!current)return;const dur=current.duration||(isFinite(video.duration)&&!transcoded?video.duration:0),pos=position();
  $("hudBar").style.width=dur?Math.min(100,pos/dur*100)+"%":"0";
  $("hudTime").textContent=clock(pos)+(dur?" / "+clock(dur):"");
  const s=state();$("hudState").textContent=s==="playing"?"Playing":s==="paused"?"Paused":s==="buffering"||s==="loading"?"Loading…":s==="ended"?"Finished":"";
  $("audioArt").classList.toggle("paused",s!=="playing")}
video.addEventListener("playing",()=>{banner("");clearTimeout(stallTimer);const pos=position();if(pos>lastPosition){recoverBudget=2;lastPosition=pos}report(true)});
video.addEventListener("pause",()=>{clearTimeout(stallTimer);report(true)});
video.addEventListener("ended",()=>{report(true)});
video.addEventListener("waiting",()=>{report(true);if(transcoded){clearTimeout(stallTimer);stallTimer=setTimeout(recover,15000)}});
video.addEventListener("stalled",()=>{if(transcoded){clearTimeout(stallTimer);stallTimer=setTimeout(recover,15000)}});
video.addEventListener("error",()=>{
  if(!current)return;
  // Direct play failed on codecs the browser could not decode: let the host convert.
  if(!transcoded&&current.fallback&&!fallbackTried){fallbackTried=true;banner("Converting for this screen…");load(current.fallback,position(),true);return}
  // A converted stream can drop while paused or buffering: resume where we were.
  if(transcoded&&Date.now()-recoverAt>4000&&video.error&&video.error.code===2){recover();return}
  report(true)});
function recover(){if(!current||!transcoded||!activeUrl)return;if(recoverBudget<=0){banner("Playback stalled on this screen. Stop and start again.");report(true);return}recoverBudget--;recoverAt=Date.now();const at=position();load(activeUrl,at,true)}
function wake(){const hud=$("hud"),tools=$("tools"),home=$("homeLink"),ver=$("scVersion");hud.classList.remove("hide");tools.classList.remove("hide");home.classList.remove("hide");ver.classList.remove("hide");clearTimeout(hideTimer);
  hideTimer=setTimeout(()=>{if(!video.paused&&!$("player").hidden){hud.classList.add("hide");tools.classList.add("hide");home.classList.add("hide");ver.classList.add("hide")}},3500)}
document.addEventListener("pointermove",wake);document.addEventListener("keydown",e=>{wake();if(!e.repeat&&!e.altKey&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.target?.isContentEditable&&!["INPUT","TEXTAREA","SELECT","BUTTON"].includes(e.target?.tagName)&&(!$("slate").hidden||!$("player").hidden)&&(e.key==="f"||e.key==="F")){e.preventDefault();fullscreen()}});
function fullscreen(){const el=document.documentElement;if(document.fullscreenElement){document.exitFullscreen()}else if(el.requestFullscreen){el.requestFullscreen().catch(()=>{})}}
$("fsButton").addEventListener("click",e=>{e.stopPropagation();fullscreen()});$("fsSlate").addEventListener("click",fullscreen);
$("startButton").addEventListener("click",begin);
$("loginForm").addEventListener("submit",login);
window.addEventListener("pagehide",()=>{if(screenId&&csrf)safe(()=>fetch(`/api/screens/${screenId}`,{method:"DELETE",credentials:"same-origin",keepalive:true,headers:{"X-CSRF-Token":csrf}}))});
$("name").value=store.get("sc_screen_name");show("loginView");
</script></body></html>
"""

_PANEL_HTML = r"""
<style>
#screensList .queue-actions{width:100%}
#screensList select{flex:1 1 100%;min-height:44px;max-width:100%;font:inherit;color:inherit;background:var(--input);border:1px solid var(--border);border-radius:10px;padding:0 10px}
#screensList .queue-actions button{min-height:44px;min-width:44px;flex:1 1 auto}
#screensList .state-error{color:var(--danger)}
#screensList li[aria-busy="true"] button{cursor:wait}
#screensList button[aria-disabled="true"]{opacity:.65}
</style>
<section id="screensPanel" hidden aria-labelledby="screensPanelHeading"><div class="row"><h2 id="screensPanelHeading" tabindex="-1">Screens</h2><span id="screensCount" class="muted"></span></div>
<p>Any browser can be a screen or speaker for this room — no app, no account. Open <a href="/screen" target="_blank" rel="noopener">this room's screen page</a> on a TV, tablet or laptop and enter the House PIN only if one has been set. Tap Start screen once to allow sound.</p>
<ul id="screensList"><li class="empty">No screens yet. Open the screen page on a TV, tablet or laptop to add one.</li></ul>
<details class="help"><summary>How to use and control browser screens</summary><div class="help-body"><p><strong>Set up a screen:</strong> open the screen page on the device that will play sound or video, join with a name and the House PIN if required, then choose Start screen on that device.</p><p><strong>Choose from queue</strong> selects an item already in Up Next. <strong>Play</strong> starts it on that individual screen, not the main room TV. Pause, Resume and Stop affect only the named screen.</p><p>If a screen is not responding, controls remain unavailable until it reconnects. Add new media using the room's Find or Add files sections first.</p></div></details>
<p id="screensMsg" class="muted" role="status" aria-live="polite"></p></section>
<script>
(function(){
  const list=document.getElementById("screensList"),count=document.getElementById("screensCount"),msg=document.getElementById("screensMsg");
  if(!list)return;
  const panel=document.getElementById("screensPanel"),dash=document.getElementById("dashboard");
  setInterval(()=>{if(dash&&dash.hidden)panel.hidden=true},1000);
  let items=[],seq=0,queueOptionsKey="";const choice=Object.create(null);
  const pendingScreenCommands=new Map();
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
  const clock=s=>{s=Math.max(0,Math.floor(Number(s)||0));return Math.floor(s/60)+":"+String(s%60).padStart(2,"0")};
  const COMMAND_TIMEOUT=8000;
  async function send(id,body){
    const key=String(id),session=csrf;
    if(pendingScreenCommands.get(key)?.session===session)return;
    const controller=new AbortController(),command={session};let timer;
    const owns=()=>csrf===session&&pendingScreenCommands.get(key)===command;
    pendingScreenCommands.set(key,command);refreshScreenPending(key);
    const name=screenById.get(key)?.name||"Screen";
    msg.textContent="Sending command to "+name+"…";
    try{
      const deadline=new Promise((_,reject)=>{
        timer=setTimeout(()=>{
          reject(Error("No confirmation from "+name+". Check its current state before trying again."));
          controller.abort();
        },COMMAND_TIMEOUT);
      });
      await Promise.race([deadline,(async()=>{
        const r=await fetch(`/api/screens/${encodeURIComponent(key)}/command`,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":session},signal:controller.signal,
          body:JSON.stringify({...body,command_id:`s${Date.now().toString(36)}-${(++seq).toString(36)}`})});
        const d=await r.json();if(!r.ok)throw Error(d.error||"Screen command failed");
      })()]);
      if(owns())msg.textContent=name+": command received; checking its state.";
    }catch(err){if(owns())msg.textContent=err.message||"No confirmation. Check the screen state before trying again."}
    finally{clearTimeout(timer);if(pendingScreenCommands.get(key)===command){pendingScreenCommands.delete(key);refreshScreenPending(key)}}
  }
  function updateScreenPlayButton(play,pick,ready){play.disabled=!ready||!pick.value}
  const label={idle:"Ready",loading:"Loading",playing:"Playing",paused:"Paused",buffering:"Buffering",ended:"Finished",error:"Problem"};
  const screenById=new Map();
  function markScreenPending(li,id){
    const busy=pendingScreenCommands.get(id)?.session===csrf;
    li.setAttribute("aria-busy",String(busy));
    for(const button of Array.from(li.children[1]?.children||[]).slice(1))button.setAttribute("aria-disabled",String(busy||!!button.disabled));
  }
  function refreshScreenPending(id){
    const row=Array.from(list.children).find(li=>li.dataset?.screenId===id);
    if(row)markScreenPending(row,id);
  }
  function makeScreenRow(sc){
    const key=String(sc.id),li=el("li","queue-item"),box=el("div");
    li.dataset.screenId=key;
    box.append(el("strong"),el("div","muted"));
    const actions=el("div","queue-actions"),pick=el("select");
    const play=el("button","tiny","Play"),toggle=el("button","secondary tiny","Pause"),stop=el("button","secondary tiny","Stop");
    pick.addEventListener("change",()=>{
      choice[key]=pick.value;
      updateScreenPlayButton(play,pick,!!screenById.get(key)?.ready);markScreenPending(li,key);
    });
    play.type="button";play.title="Play the selected shared-queue item on this screen, not the room TV";
    play.addEventListener("click",()=>{
      const current=screenById.get(key);
      if(!current?.ready){msg.textContent="Screen is not responding.";return}
      if(pick.value&&items.some(q=>String(q.id)===pick.value))void send(key,{action:"play",item:pick.value,follow:true});
      else msg.textContent="Pick something from the queue first.";
    });
    toggle.type="button";toggle.title="Pause or resume playback on this screen only";
    toggle.addEventListener("click",()=>{
      const current=screenById.get(key);
      if(current?.ready&&current.item)void send(key,{action:current.state==="paused"?"resume":"pause"});
    });
    stop.type="button";stop.title="Stop this screen without stopping the host TV";
    stop.addEventListener("click",()=>{
      const current=screenById.get(key);
      if(current?.ready&&current.item)void send(key,{action:"stop"});
    });
    actions.append(pick,play,toggle,stop);li.append(box,actions);
    return li;
  }
  function updateScreenRow(li,sc){
    const key=String(sc.id),[box,actions]=li.children,[head,info]=box.children,[pick,play,toggle,stop]=actions.children;
    head.textContent=sc.name+(sc.video?" · screen":" · speaker");
    info.className="muted"+(sc.state==="error"?" state-error":"");
    info.textContent=!sc.ready?"Not responding":(label[sc.state]||sc.state)+(sc.title?" — "+sc.title:"")+
      (sc.duration?" ("+clock(sc.position)+" / "+clock(sc.duration)+")":"")+
      (sc.mode==="transcode"?" · converted by host":"")+
      (sc.state==="error"&&sc.error?" · "+sc.error:"");
    if(li.dataset.optionsKey!==queueOptionsKey){
      li.dataset.optionsKey=queueOptionsKey;
      const none=el("option","","Choose from queue");none.value="";
      const options=[none];
      for(const q of items){const o=el("option","",q.title);o.value=String(q.id);options.push(o)}
      pick.replaceChildren(...options);
    }
    const selection=String(choice[key]||"");
    const selected=items.some(q=>String(q.id)===selection)?selection:"";
    if(!selected)choice[key]="";
    if(pick.value!==selected)pick.value=selected;
    pick.setAttribute("aria-label","Choose what to play on "+sc.name);
    play.setAttribute("aria-label","Play selected queue item on "+sc.name);
    updateScreenPlayButton(play,pick,!!sc.ready);
    toggle.textContent=sc.state==="paused"?"Resume":"Pause";
    toggle.setAttribute("aria-label",(sc.state==="paused"?"Resume":"Pause")+" playback on "+sc.name);
    toggle.disabled=!sc.item||!sc.ready;
    stop.setAttribute("aria-label","Stop playback on "+sc.name);
    stop.disabled=!sc.item||!sc.ready;
    markScreenPending(li,key);
  }
  window.scRenderScreens=function(s){
    const homePanel=document.getElementById("homePanel");
    if(homePanel&&panel.previousElementSibling!==homePanel)homePanel.after(panel);
    panel.hidden=false;
    const screens=Array.isArray(s.screens)?s.screens:[];items=Array.isArray(s.queue)?s.queue:[];
    queueOptionsKey=JSON.stringify(items.map(q=>[q.id,q.title]));
    screenById.clear();for(const sc of screens)screenById.set(String(sc.id),sc);
    count.textContent=screens.length?screens.length+" connected":"";
    const focused=list.contains(document.activeElement)?document.activeElement:null;
    if(!screens.length){
      if(list.children.length!==1||list.firstElementChild?.className!=="empty")list.replaceChildren(el("li","empty","No screens yet. Open the screen page on a TV, tablet or laptop to add one."));
      if(focused)document.getElementById("screensPanelHeading").focus({preventScroll:true});
      for(const key of Object.keys(choice))delete choice[key];
      return;
    }
    const existing=new Map(Array.from(list.children).filter(li=>li.dataset?.screenId)
      .map(li=>[li.dataset.screenId,li]));
    const rows=[];
    for(const sc of screens){
      const key=String(sc.id),li=existing.get(key)||makeScreenRow(sc);
      updateScreenRow(li,sc);rows.push(li);
    }
    if(list.firstElementChild?.className==="empty")list.replaceChildren(...rows);
    else{
      rows.forEach((row,index)=>{
        const current=list.children[index]||null;
        if(current!==row)list.insertBefore(row,current);
      });
      for(const child of Array.from(list.children))if(!rows.includes(child))child.remove();
    }
    for(const key of Object.keys(choice))if(!screenById.has(key))delete choice[key];
    if(focused){
      if(list.contains(focused)){
        if(document.activeElement!==focused)focused.focus({preventScroll:true});
      }else document.getElementById("screensPanelHeading").focus({preventScroll:true});
    }
  };

})();
</script>
"""
