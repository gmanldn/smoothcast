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
<section id="meshPanel" hidden aria-labelledby="meshTitle"><h2 id="meshTitle">Network</h2>
<p id="meshSum" class="mesh-sum" role="status">Looking for devices…</p><p id="meshConn" class="conn" role="status" aria-live="polite"></p>
<p id="meshHint" class="muted"></p>
<h3>Devices</h3><ul id="meshNodes" aria-label="Devices"></ul>
<h3>Targets</h3><ul id="meshTargets" aria-label="Playback targets"></ul>

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
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
  const TEXT={self:"This device",alive:"Online",ready:"Ready",busy:"In use",stale:"Not seen lately",unreachable:"Can't be reached"};
  const RANK={ready:0,busy:1,stale:2,unreachable:3};
  const plural=(n,w)=>n+" "+w+(n===1?"":"s");
  function model(){
    const list=[...nodes.values()].sort((a,b)=>(a.node_id===local?-1:b.node_id===local?1:a.name.localeCompare(b.name)||a.node_id.localeCompare(b.node_id)));
    const rows=list.map(n=>({key:"n:"+n.node_id,title:n.name,sub:plural((n.targets||[]).length,"target")+" · "+plural(n.client_count||0,"client"),
      badges:[n.node_id===local?"This device":null,n.node_id===primary?"Primary":null,n.status==="draining"?"Leaving":null].filter(Boolean),
      state:n.node_id===local?"self":"alive",why:""}));
    const by=new Map();
    for(const n of list)for(const t of (n.targets||[])){const e=by.get(t.id)||{id:t.id,name:t.name,kind:t.kind,model:t.model,obs:[]};e.obs.push({node:n.name,state:t.state,age:t.age_ms||0,owner:t.owner});by.set(t.id,e)}
    const trows=[...by.values()].map(e=>{
      e.obs.sort((a,b)=>RANK[a.state]-RANK[b.state]);const best=e.obs[0].state;
      const ready=e.obs.filter(o=>o.state==="ready").map(o=>o.node);
      let why="";
      if(best==="busy")why="Another room is using this receiver.";
      else if(best==="stale")why="Not seen for "+Math.max(1,Math.round(Math.min(...e.obs.map(o=>o.age))/60000))+" min.";
      else if(best==="unreachable")why="No device can reach it right now.";
      const kind={cast:"Chromecast",dlna:"DLNA",screen:"Browser screen",smoothcast:"SmoothCast"}[e.kind]||"Receiver";
      return {key:"t:"+e.id,title:e.name,sub:kind+(e.model&&e.model!==kind?" · "+e.model:"")+" — seen by "+(ready.length?ready:e.obs.map(o=>o.node)).slice(0,2).join(", "),badges:[],state:best,why}});
    trows.sort((a,b)=>RANK[a.state]-RANK[b.state]||a.title.localeCompare(b.title)||a.key.localeCompare(b.key));
    return {rows,trows};
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
    const {rows,trows}=model();
    const keyFocus=document.activeElement&&panel.contains(document.activeElement)?document.activeElement:null;
    sync($("meshNodes"),rows);sync($("meshTargets"),trows);
    const live=rows.length,ready=trows.filter(t=>t.state==="ready").length;
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
    render();
  }
  function conn(text){$("meshConn").textContent=text}
  function open(){
    close();
    es=new EventSource("/api/mesh/events");
    es.addEventListener("mesh",e=>{conn("");backoff=3000;try{apply(JSON.parse(e.data))}catch(_){}});
    es.onerror=()=>{conn("Reconnecting to the room…");if(es&&es.readyState===2){close();schedule()}};
  }
  function close(){if(es){es.close();es=null}}
  function cancelMeshRetry(){if(retry!==null){clearTimeout(retry);retry=null}}
  function schedule(){cancelMeshRetry();retry=setTimeout(boot,backoff);backoff=Math.min(30000,backoff*2)}
  async function boot(){
    if(document.hidden||!dash||dash.hidden||typeof csrf==="undefined"||!csrf)return schedule();
    try{
      const r=await fetch("/api/mesh",{credentials:"same-origin",cache:"no-store"});
      if(r.status===503||r.status===404){panel.hidden=true;showNetworkNavigation(false);return schedule()}
      if(!r.ok)return schedule();
      const d=await r.json();nodes=new Map((d.mesh.nodes||[]).map(n=>[n.node_id,n]));local=d.mesh.local;primary=d.mesh.primary||"";
      panel.hidden=false;showNetworkNavigation(true);started=true;backoff=3000;render();open();
    }catch(_){schedule()}
  }
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden){hiddenTimer=setTimeout(()=>{close()},30000)}
    else{clearTimeout(hiddenTimer);if(!es){cancelMeshRetry();boot()}}
  });
  const anchor=()=>{const s=document.getElementById("screensPanel")||document.getElementById("queuePanel");if(s&&s.parentElement&&panel.previousElementSibling!==s)s.after(panel)};
  setInterval(()=>{anchor();if(dash&&dash.hidden){panel.hidden=true;showNetworkNavigation(false);cancelMeshRetry();backoff=3000;close();started=false;prev=null}else if(!started&&!retry)boot()},1500);
})();
</script>
"""
