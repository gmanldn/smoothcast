"""Browser Network card for the room dashboard (ticket #403).

Self-hosted markup and script, no external assets, text via ``textContent`` only.
Reads ``/api/mesh`` and ``/api/mesh/events`` (guest tier), keeps rows updated in
place (focus and scroll are never disturbed), states always carry text and not
only colour, arrivals and departures are announced politely at most every 3 s,
and a dropped stream shows a visible reconnecting state and recovers with a fresh
snapshot. Hidden entirely when the host runs no mesh.
"""
from __future__ import annotations


def panel_html() -> str:
    return _PANEL


_PANEL = r"""
<style>
#meshPanel .mesh-sum{font-weight:650;margin:.2rem 0 .6rem}
#meshPanel .mesh-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
#meshPanel .mesh-head h2{margin-bottom:6px}
#meshPanel .mesh-feed{border:1px solid var(--line);border-radius:8px;padding:5px 9px;font-size:.75rem;color:var(--muted)}
#meshPanel .mesh-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:8px;margin:12px 0}
#meshPanel .mesh-metric{background:var(--input);border:1px solid var(--line);border-radius:11px;padding:10px;min-width:0}
#meshPanel .mesh-metric strong{display:block;font-size:1.55rem;font-variant-numeric:tabular-nums;line-height:1.2}
#meshPanel .mesh-metric span{font-size:.76rem;color:var(--muted)}
#meshPanel .mesh-room{background:var(--input);border:1px solid var(--line);border-radius:12px;padding:12px;margin:10px 0}
#meshPanel .mesh-room strong,#meshPanel .mesh-room p{overflow-wrap:anywhere;margin:.3rem 0}
#meshPanel .mesh-stream{display:grid;gap:4px;padding:9px 0;border-top:1px solid var(--line)}
#meshPanel .mesh-stream strong{font-size:.88rem}#meshPanel .mesh-stream span{font-size:.76rem}#meshPanel .mesh-stream progress{height:6px;width:100%}
#meshPanel .mesh-columns .why{color:var(--muted)}
#meshPanel .mesh-columns{display:grid;grid-template-columns:minmax(0,1fr);gap:16px}
#meshPanel .mesh-columns>div{min-width:0}
#meshPanel .mesh-columns .t{white-space:normal;overflow-wrap:anywhere}
#meshPanel .mesh-links{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}
#meshPanel .mesh-links a{display:inline-flex;align-items:center;min-height:44px;color:var(--accent);text-underline-offset:3px;font-weight:650}
#meshPanel .mesh-note{font-size:.8rem;color:var(--muted);margin:8px 0}
@media(min-width:820px){#meshPanel .mesh-columns{grid-template-columns:repeat(2,minmax(0,1fr))}}

#meshPanel ul{margin:0 0 10px;padding:0;list-style:none}
#meshPanel li.row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:4px 10px;align-items:center;border-top:1px solid var(--line);padding:9px 0;min-height:44px}
#meshPanel li.row:first-child{border-top:0}
#meshPanel .dot{width:12px;height:12px;border-radius:50%;background:var(--dim);display:inline-block}
#meshPanel .dot.ready,#meshPanel .dot.self,#meshPanel .dot.alive{background:var(--accent)}
#meshPanel .dot.busy{background:var(--focus)}#meshPanel .dot.stale{background:var(--muted)}#meshPanel .dot.unreachable{background:var(--danger)}
#meshPanel .t{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#meshPanel .s{font-size:.8rem;color:var(--muted);grid-column:2}
#meshPanel .st{font-size:.8rem;grid-column:3;grid-row:1;text-align:right}
#meshPanel .why{font-size:.78rem;color:var(--danger);grid-column:2 / 4}
#meshPanel .badge{font-size:.68rem;border:1px solid var(--border);border-radius:999px;padding:1px 7px;margin-left:6px;vertical-align:middle}
#meshPanel h3{font-size:.9rem;margin:12px 0 2px;color:var(--muted)}
#meshPanel .conn{font-size:.8rem;color:var(--danger);min-height:1.2em}
@media(prefers-reduced-motion:no-preference){#meshPanel li.row{animation:meshin .2s ease-out}}
@keyframes meshin{from{opacity:0}to{opacity:1}}
</style>
<section id="meshPanel" hidden aria-labelledby="meshTitle"><div class="mesh-head"><h2 id="meshTitle">Live mesh</h2><span id="meshFeedState" class="mesh-feed" role="status">Connecting…</span></div>
<p id="meshSum" class="mesh-sum" role="status">Looking for devices…</p><p id="meshConn" class="conn" role="status" aria-live="polite"></p>
<p id="meshHint" class="muted"></p>
<div class="mesh-metrics" aria-label="Latest reported mesh totals">
<div class="mesh-metric"><strong id="meshDeviceCount">—</strong><span>Online nodes</span></div>
<div class="mesh-metric"><strong id="meshClientCount">—</strong><span>Connected clients</span></div>
<div class="mesh-metric"><strong id="meshReadyCount">—</strong><span>Ready targets</span></div>
<div class="mesh-metric"><strong id="meshBusyCount">—</strong><span>Targets in use</span></div>
<div class="mesh-metric"><strong id="meshUnavailableCount">—</strong><span>Stale / unreachable</span></div>
</div>
<div class="mesh-room" aria-labelledby="meshRoomHeading"><h3 id="meshRoomHeading">This host · room control</h3>
<strong id="meshRoomTitle">Waiting for room state…</strong><p id="meshRoomReceiver" class="muted">Receiver status unavailable</p>
<p id="meshRoomQueue" class="muted">Waiting for queue status</p><p id="meshRoomStreams" class="muted">Waiting for network activity</p>
<p id="meshAcquisitions" class="muted">Waiting for acquisition activity</p><ul id="meshAcquisitionRows" aria-label="Room host media acquisition activity"></ul>
<h4>Other hosts · acquisition activity</h4>
<p id="meshRemoteAcquisitionSummary" class="muted">Waiting for peer acquisition observations</p>
<ul id="meshRemoteAcquisitionRows" aria-label="Reported acquisition activity on other SmoothCast hosts"></ul>
<p class="field-hint">Peer reports are read-only. A stale report does not establish that a download is still running.</p>
<ul id="meshStreamList" aria-label="Reported live receiver streams"></ul>
<div class="mesh-links"><a href="#playback">Playback controls</a><a href="#queuePanel">Up Next</a><a href="#linkAcquisition">Link acquisitions</a><a href="#uploadCard">Transfer files</a><a href="#networkActivity">Receiver activity</a></div>
</div>
<div class="mesh-columns"><div><h3>Nodes · version and capability</h3><ul id="meshNodes" aria-label="Mesh nodes"></ul></div>
<div><h3>Receivers · reachability and ownership</h3><ul id="meshTargets" aria-label="Playback targets"></ul></div></div>
<p id="meshVersionNote" class="mesh-note"></p><p id="meshFreshness" class="mesh-note">Waiting for first mesh snapshot.</p>
<p class="mesh-note">Counts reflect current mesh advertisements, not a network scan. CPU, disk, per-hop bandwidth and playback confirmation on other nodes are not reported here.</p>

<details class="help"><summary>What do the network devices and target states mean?</summary><div class="help-body">
<p><strong>Devices</strong> are SmoothCast computers cooperating on your local network. <strong>Targets</strong> are the TVs, speakers and browser screens they can reach. <strong>This device</strong> identifies this host; <strong>Primary</strong> is the node coordinating the mesh, not the receiver currently playing.</p>
<p><strong>Ready</strong> means the receiver is currently reachable, <strong>In use</strong> means another room has it, <strong>Not seen lately</strong> means discovery is out of date, and <strong>Can't be reached</strong> means no node can currently contact it.</p>
<p>This panel is a read-only view of local network activity. It does not cast, claim receivers or upload files; use Now Playing, Find or Add files for room actions. Reconnecting indicates that updates have temporarily stopped, not that your current cast has ended.</p>
</div></details>
<div id="meshLive" class="sr-only" aria-live="polite" style="position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden"></div></section>
<script>
(function(){
  const panel=document.getElementById("meshPanel");if(!panel)return;
  const navLink=document.getElementById("meshNavLink");
  function showNetworkNavigation(visible){if(navLink)navLink.hidden=!visible}
  const $=id=>document.getElementById(id);
  const dash=document.getElementById("dashboard");
  let nodes=new Map(),local="",primary="",es=null,backoff=3000,retry=null,lastSay=0,prev=null,started=false,hiddenTimer=null;
  let bootRequest=null,bootEpoch=0;
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
  const TEXT={self:"This device",alive:"Online",ready:"Ready",busy:"In use",stale:"Not seen lately",unreachable:"Can't be reached"};
  const RANK={ready:0,busy:1,stale:2,unreachable:3};
  const plural=(n,w)=>n+" "+w+(n===1?"":"s");
  const put=(id,value)=>{const target=$(id);if(target&&target.textContent!==String(value))target.textContent=String(value)};
  const semver=value=>{const m=typeof value==="string"&&value.match(/^(\d+)\.(\d+)\.(\d+)$/);return m?m.slice(1).map(Number):null};
  function versionCompare(a,b){const aa=semver(a),bb=semver(b);if(!aa||!bb)return null;for(let i=0;i<3;i++){if(aa[i]!==bb[i])return aa[i]-bb[i]}return 0}
  let lastMeshAt=0;
  function markMesh(state){put("meshFeedState",state)}
  function updateFreshness(){if(lastMeshAt)put("meshFreshness","Last mesh change / snapshot received at "+new Date(lastMeshAt).toLocaleTimeString()+". Quiet meshes may have no changes.")}
  window.scRenderMeshRoom=function(state){
    if(!state||typeof state!=="object")return;
    put("meshRoomTitle",state.title||"Nothing playing");
    put("meshRoomReceiver",(state.receiver||"No receiver selected")+" · "+(state.state_label||state.state||"State unavailable"));
    const queued=Array.isArray(state.queue)?state.queue.length:null;
    put("meshRoomQueue",queued===null?"Queue status unavailable":plural(queued,"waiting item")+(state.busy?" · Playback command pending":""));
    const streams=Array.isArray(state.network_activity)?state.network_activity.length:null;
    put("meshRoomStreams",streams===null?"Receiver activity unavailable":plural(streams,"reported active receiver stream"));
    const acquisitions=Array.isArray(state.link_jobs)?state.link_jobs:[];
    const active=acquisitions.filter(job=>!["ready","failed","cancelled","delivery_uncertain"].includes(job.stage));
    put("meshAcquisitions",active.length?plural(active.length,"active room-host acquisition"):"No active room-host acquisitions");
    const acquisitionRows=$("meshAcquisitionRows");
    if(acquisitionRows&&typeof acquisitionRows.replaceChildren==="function"){
      const fingerprint=JSON.stringify(active.map(j=>[j.id,j.title,j.stage,j.received,j.total]));
      if(acquisitionRows.dataset.sig!==fingerprint){
        acquisitionRows.dataset.sig=fingerprint;
        acquisitionRows.replaceChildren(...active.map(job=>{
          const row=el("li","mesh-stream");
          row.append(el("strong","",job.title||"Media acquisition"),el("span","muted","Room host · "+(job.stage==="pending"?"Waiting for worker":job.stage)));
          if(Number.isSafeInteger(job.received)&&Number.isSafeInteger(job.total)&&job.total>0&&job.received>=0&&job.received<=job.total){
            const meter=el("progress");meter.max=job.total;meter.value=job.received;meter.setAttribute("aria-label","Reported acquisition progress");row.append(meter);
          }
          return row;
        }));
      }
    }
    const remote=state.mesh_link_activity;
    const peers=remote&&Array.isArray(remote.nodes)?remote.nodes:[];
    const livePeers=peers.filter(peer=>peer.freshness==="live");
    const liveCount=livePeers.reduce((n,peer)=>n+(Array.isArray(peer.jobs)?peer.jobs.length:0),0);
    const missing=peers.length-livePeers.length;
    put("meshRemoteAcquisitionSummary",!remote||!remote.available?"Peer acquisition observation unavailable":
      !peers.length?"No compatible peer acquisition reports yet":
      plural(liveCount,"reported active peer acquisition")+" · "+plural(livePeers.length,"live host")+
      (missing?" · "+plural(missing,"unconfirmed host"):"")+
      (remote.omitted_jobs?" · "+plural(remote.omitted_jobs,"additional job")+" omitted":""));
    const remoteRows=$("meshRemoteAcquisitionRows");
    if(remoteRows&&typeof remoteRows.replaceChildren==="function"){
      const signature=JSON.stringify(peers);
      if(remoteRows.dataset.sig!==signature){
        remoteRows.dataset.sig=signature;
        const rows=[];
        for(const peer of peers){
          const jobs=Array.isArray(peer.jobs)?peer.jobs:[];
          const freshness=peer.freshness==="live"?"Live report":peer.freshness==="stale"?"Stale · last reported":peer.freshness==="waiting"?"Awaiting first report":"Report unavailable";
          const host=peer.name||"SmoothCast host";
          if(!jobs.length){
            const row=el("li","mesh-stream");
            row.append(el("strong","",host),el("span","muted",freshness+(peer.freshness==="live"?" · No active acquisitions reported":"")));
            rows.push(row);
          }
          for(const job of jobs){
            const row=el("li","mesh-stream");
            const label=job.kind==="youtube"?"YouTube video":"BitTorrent media";
            const stage={pending:"Waiting for worker",resolving:"Resolving metadata",downloading:"Downloading",verifying:"Verifying media",queueing:"Submitting to queue"}[job.stage]||"Unknown";
            row.append(el("strong","",host+" · "+label),el("span","muted",freshness+" · "+stage));
            if(Number.isSafeInteger(job.received)&&Number.isSafeInteger(job.total)&&job.total>0&&job.received>=0&&job.received<=job.total){
              const meter=el("progress");meter.max=job.total;meter.value=job.received;meter.setAttribute("aria-label",peer.freshness==="live"?"Reported acquisition progress":"Last reported acquisition progress");row.append(meter);
              const size=n=>(n/1048576).toFixed(1)+" MiB";
              const rate=peer.freshness==="live"&&Number.isSafeInteger(job.rate)&&job.rate>0? " · "+size(job.rate)+"/s":"";
              row.append(el("span","muted",size(job.received)+" / "+size(job.total)+rate));
            }
            rows.push(row);
          }
        }
        remoteRows.replaceChildren(...rows);
      }
    }
    const streamList=$("meshStreamList");
    if(streamList&&typeof streamList.replaceChildren==="function"){
      const observed=Array.isArray(state.network_activity)?state.network_activity.slice(0,64):[];
      const signature=JSON.stringify(observed.map(item=>[item.receiver,item.title,item.protocol,item.state,item.position,item.duration,item.is_local]));
      if(streamList.dataset.sig!==signature){
        streamList.dataset.sig=signature;
        const timing=value=>Number.isFinite(value)&&value>=0?Math.floor(value/60)+":"+String(Math.floor(value%60)).padStart(2,"0"):"";
        const rows=observed.map(item=>{
          const row=document.createElement("li");row.className="mesh-stream";
          const title=document.createElement("strong");title.textContent=item.title||"Media title unavailable";
          const detail=document.createElement("span");detail.className="muted";
          detail.textContent=[item.receiver||"Unknown receiver",item.protocol,item.state||"State unavailable",item.is_local?"This host":""].filter(Boolean).join(" · ");
          row.append(title,detail);
          if(Number.isFinite(item.duration)&&item.duration>0&&Number.isFinite(item.position)&&item.position>=0){
            const progress=document.createElement("progress");progress.max=item.duration;progress.value=Math.min(item.position,item.duration);
            progress.setAttribute("aria-label","Reported playback position");
            const time=document.createElement("span");time.className="muted";time.textContent=timing(item.position)+" / "+timing(item.duration);
            row.append(progress,time);
          }
          return row;
        });
        streamList.replaceChildren(...rows);
      }
    }
  };
  function model(){
    const list=[...nodes.values()].sort((a,b)=>(a.node_id===local?-1:b.node_id===local?1:a.name.localeCompare(b.name)||a.node_id.localeCompare(b.node_id)));
    const versions=list.map(n=>n.version).filter(v=>semver(v));
    const newest=versions.reduce((best,v)=>!best||versionCompare(v,best)>0?v:best,"");
    const rows=list.map(n=>{
      const targets=Array.isArray(n.targets)?n.targets:[];
      const caps=Array.isArray(n.capabilities)?n.capabilities.filter(c=>typeof c==="string"):[], protocols=Array.isArray(n.protocols)?n.protocols:[];
      const count=Number.isSafeInteger(n.client_count)&&n.client_count>=0?n.client_count:0;
      const older=newest&&versionCompare(n.version,newest)<0;
      const summary=(n.version?"v"+n.version:"Version unavailable")+" · "+plural(count,"client")+" · "+targets.filter(t=>t.state==="ready").length+" / "+plural(targets.length,"target")+" ready";
      const detail=[older?"Older than v"+newest+" reported by another node.":"",protocols.length?"Protocols: "+protocols.join(", "):"",caps.length?"Capabilities: "+caps.join(", "):""].filter(Boolean).join(" · ");
      return {key:"n:"+n.node_id,title:n.name,sub:summary,badges:[n.node_id===local?"This device":null,n.node_id===primary?"Primary":null,n.status==="draining"?"Leaving":null].filter(Boolean),state:n.node_id===local?"self":"alive",why:detail};
    });
    const by=new Map();
    for(const n of list)for(const t of (n.targets||[])){const e=by.get(t.id)||{id:t.id,name:t.name,kind:t.kind,model:t.model,obs:[]};e.obs.push({node:n.name,state:t.state,age:t.age_ms||0,owner:t.owner});by.set(t.id,e)}
    const trows=[...by.values()].map(e=>{
      e.obs.sort((a,b)=>RANK[a.state]-RANK[b.state]);const best=e.obs[0].state;
      const ready=e.obs.filter(o=>o.state==="ready").map(o=>o.node);
      let why="";
      if(best==="busy"){const owner=e.obs.map(o=>o.owner).find(id=>nodes.has(id));why=owner?"Reported in use via "+nodes.get(owner).name+".":"Reported in use; owner not reported."}
      else if(best==="stale")why="Not seen for "+Math.max(1,Math.round(Math.min(...e.obs.map(o=>o.age))/60000))+" min.";
      else if(best==="unreachable")why="No device can reach it right now.";
      const kind={cast:"Chromecast",dlna:"DLNA",screen:"Browser screen",smoothcast:"SmoothCast"}[e.kind]||"Receiver";
      return {key:"t:"+e.id,title:e.name,sub:kind+(e.model&&e.model!==kind?" · "+e.model:"")+" — seen by "+(ready.length?ready:e.obs.map(o=>o.node)).slice(0,2).join(", "),badges:[],state:best,why}});
    trows.sort((a,b)=>RANK[a.state]-RANK[b.state]||a.title.localeCompare(b.title)||a.key.localeCompare(b.key));
    return {rows,trows,newest,list};
  }
  function sync(listEl,rows){
    const have=new Map([...listEl.children].map(li=>[li.dataset.key,li]));
    const wanted=new Set(rows.map(r=>r.key));
    for(const [k,li] of have)if(!wanted.has(k))li.remove();
    let before=null;
    rows.forEach((r,i)=>{
      let li=have.get(r.key);
      if(!li){li=el("li","row");li.dataset.key=r.key;li.append(el("span","dot"),el("span","t"),el("span","st"),el("span","s"),el("span","why"))}
      const [dot,t,st,sub,why]=li.children;
      const sig=JSON.stringify(r);
      if(li.dataset.sig!==sig){
        li.dataset.sig=sig;dot.className="dot "+r.state;t.textContent=r.title;
        for(const b of r.badges)t.append(el("span","badge",b));
        st.textContent=TEXT[r.state]||r.state;sub.textContent=r.sub;why.textContent=r.why;why.hidden=!r.why;
      }
      const cur=listEl.children[i]||null;
      if(cur!==li)listEl.insertBefore(li,cur);
    });
  }
  function render(){
    const {rows,trows,newest,list}=model();
    const keyFocus=document.activeElement&&panel.contains(document.activeElement)?document.activeElement:null;
    sync($("meshNodes"),rows);sync($("meshTargets"),trows);
    const live=rows.length,ready=trows.filter(t=>t.state==="ready").length,busy=trows.filter(t=>t.state==="busy").length;
    const clients=list.reduce((sum,n)=>sum+(Number.isSafeInteger(n.client_count)&&n.client_count>=0?n.client_count:0),0);
    put("meshDeviceCount",live);put("meshClientCount",clients);put("meshReadyCount",ready);put("meshBusyCount",busy);put("meshUnavailableCount",trows.length-ready-busy);
    put("meshVersionNote",newest?"Newest advertised node version: v"+newest+". Version differences do not by themselves prove incompatibility.":"Node version information unavailable.");updateFreshness();
    $("meshSum").textContent=plural(live,"device")+" · "+ready+" of "+plural(trows.length,"target")+" ready";
    $("meshHint").textContent=live<=1&&!trows.length?"Searching for other SmoothCast devices…":"";
    if(keyFocus&&document.activeElement!==keyFocus)keyFocus.focus({preventScroll:true});
    announce(rows.concat(trows));
  }
  function announce(all){
    const cur=new Map(all.map(r=>[r.key,r.title]));
    if(prev){
      const joined=[...cur].filter(([k])=>!prev.has(k)).map(([,v])=>v),left=[...prev].filter(([k])=>!cur.has(k)).map(([,v])=>v);
      const now=Date.now();
      if((joined.length||left.length)&&now-lastSay>3000){
        const parts=[];if(joined.length)parts.push(joined.length<=2?joined.join(", ")+" joined":joined.length+" items joined");
        if(left.length)parts.push(left.length<=2?left.join(", ")+" left":left.length+" items left");
        $("meshLive").textContent=parts.join("; ");lastSay=now;
      }
    }
    prev=cur;
  }
  function apply(msg){
    if(msg.type==="snapshot"){nodes=new Map((msg.nodes||[]).map(n=>[n.node_id,n]));local=msg.local||local;primary=msg.primary||""}
    else if(msg.type==="delta"){for(const c of msg.changes||[]){if(c.kind==="removed")nodes.delete(c.node_id);else if(c.node)nodes.set(c.node_id,c.node)}if("primary" in msg)primary=msg.primary||""}
    lastMeshAt=Date.now();render();
  }
  function conn(text){$("meshConn").textContent=text}
  function open(){
    close();
    es=new EventSource("/api/mesh/events");
    markMesh("Connecting live feed");
    es.onopen=()=>{markMesh("Live feed connected");conn("")};
    es.addEventListener("mesh",e=>{try{apply(JSON.parse(e.data));conn("");markMesh("Live feed connected");backoff=3000}catch(_){markMesh("Invalid update · last known state")}});
    es.onerror=()=>{markMesh("Reconnecting · last known state");conn("Reconnecting to the room…");if(es&&es.readyState===2){close();schedule()}};
  }
  function close(){if(es){es.close();es=null}}
  function cancelMeshRetry(){if(retry!==null){clearTimeout(retry);retry=null}}
  function schedule(){cancelMeshRetry();retry=setTimeout(boot,backoff);backoff=Math.min(30000,backoff*2)}
  function cancelMeshBoot(){
    bootEpoch++;
    if(bootRequest){bootRequest.abort();bootRequest=null}
  }
  async function boot(){
    if(bootRequest)return;
    if(document.hidden||!dash||dash.hidden||typeof csrf==="undefined"||!csrf)return;
    cancelMeshRetry();
    const session=csrf,request=new AbortController(),epoch=++bootEpoch;
    bootRequest=request;
    const current=()=>epoch===bootEpoch&&!request.signal.aborted&&csrf===session&&!document.hidden&&!dash.hidden;
    try{
      const r=await fetch("/api/mesh",{credentials:"same-origin",cache:"no-store",signal:request.signal});
      if(!current())return;
      if(r.status===503||r.status===404){panel.hidden=true;showNetworkNavigation(false);return schedule()}
      if(!r.ok)return schedule();
      const d=await r.json();
      if(!current())return;
      nodes=new Map((d.mesh.nodes||[]).map(n=>[n.node_id,n]));local=d.mesh.local;primary=d.mesh.primary||"";
      panel.hidden=false;showNetworkNavigation(true);started=true;backoff=3000;lastMeshAt=Date.now();render();open();
    }catch(_){if(current())schedule()}
    finally{if(bootRequest===request)bootRequest=null}
  }
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden){cancelMeshBoot();cancelMeshRetry();hiddenTimer=setTimeout(()=>{close()},30000)}
    else{clearTimeout(hiddenTimer);if(!es){cancelMeshRetry();boot()}}
  });
  const anchor=()=>{const s=document.getElementById("screensPanel")||document.getElementById("queuePanel");if(s&&s.parentElement&&panel.previousElementSibling!==s)s.after(panel)};
  setInterval(()=>{anchor();if(dash&&dash.hidden){panel.hidden=true;showNetworkNavigation(false);cancelMeshBoot();cancelMeshRetry();backoff=3000;close();started=false;prev=null;lastMeshAt=0;markMesh("Connecting…")}else if(!started&&!retry)boot()},1500);
})();
</script>
"""
