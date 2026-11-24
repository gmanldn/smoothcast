// Connector-only, develop-only progress transport (#598). No version allocation or closure.
// versionBlob MUST come from offline canonical AST validation of exact pinned bytes.
function check(ok,why){if(!ok)throw Error(why)}

function isSha(x){return typeof x==="string"&&/^[0-9a-f]{40}$/.test(x)}

function validate(p){
  check(Number.isSafeInteger(p.issue)&&p.issue>0&&/^[A-Za-z0-9-]{1,80}$/.test(p.agent),"invalid issue/agent");
  check(isSha(p.base)&&isSha(p.versionBlob),"invalid base or version proof");
  check(Array.isArray(p.changes)&&p.changes.length>0&&p.changes.length<=30,"invalid change count");
  const paths=new Set();
  for(const c of p.changes){
    check(typeof c.path==="string"&&/^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/.test(c.path)&&!c.path.split("/").some(x=>[".","..",".git"].includes(x)),"invalid path");
    check(c.path!=="src/version.py"&&!paths.has(c.path),"version edit or duplicate path");
    check(c.old===null||isSha(c.old),"invalid old blob");
    check(typeof c.content==="string"&&c.content.length<=500000,"bounded text only");
    paths.add(c.path);
  }
  for(const k of ["message","verification","next"]){
    check(typeof p[k]==="string"&&p[k].trim()&&!/[\x00-\x1f\x7f]/.test(p[k]),"missing or multiline "+k);
    check(!/<!--\s*sc-/i.test(p[k]),"reserved protocol marker in "+k);
  }
  check(!["none","complete","no remaining work"].includes(p.next.trim().toLowerCase()),"progress only; no closure");
}

function leaseCheck(rows,p,now){
  const live=new Map();
  for(const c of [...rows].sort((a,b)=>a.id-b.id)){
    const body=c.body||"", m=body.match(/<!--\s*sc-(claim|release)\s+v1\s+([^>]*?)\s*-->/);
    const legacyClaim=/^\s*(?:\*\*)?claim\b/i.test(body)&&!/releas/i.test(body.slice(0,200));
    const legacyRelease=/claim released|releasing the claim|release the claim|releasing my claim/i.test(body);
    if(!m&&!legacyClaim&&!legacyRelease)continue;
    const issue=Number((c.issue_url||"").split("/").pop()), at=Date.parse(c.created_at), updated=Date.parse(c.updated_at||c.created_at);
    check(Number.isSafeInteger(c.id)&&Number.isSafeInteger(issue)&&issue>0&&Number.isFinite(at)&&Number.isFinite(updated),"incomplete claim metadata");
    const f=m?Object.fromEntries(m[2].split(/\s+/).filter(x=>x.includes("=")).map(x=>{const i=x.indexOf("=");return [x.slice(0,i),x.slice(i+1)]})):null;
    const agent=f?f.agent:"legacy", key=issue+"/"+agent;
    check(typeof agent==="string"&&agent,"invalid agent marker");
    if(m?m[1]==="release":legacyRelease){live.delete(key);continue}
    const ttl=f?(f.ttl===undefined?90:/^\d+$/.test(f.ttl)?Math.min(180,Math.max(30,Number(f.ttl))):180):45;
    const files=f?(f.files||"").split(",").filter(Boolean):(body.match(/(?:src|scripts|setup|packaging|fakecast|\.github)\/[\w./-]+\.[\w]+/g)||[]);
    live.set(key,{issue,agent,files,until:(f?Math.max(at,updated):at)+ttl*60000});
  }
  const mine=live.get(p.issue+"/"+p.agent);
  check(mine&&mine.until>now,"own lease missing or expired");
  const shared=new Set(["pyproject.toml","docs/complexity-baseline.json",".github/workflows/verify.yml","docs/a11y-baseline.json","docs/silent-except-baseline.json"]);
  const production=p.changes.map(c=>c.path).filter(x=>!shared.has(x)&&!x.startsWith("docs/")&&!x.startsWith("tests/"));
  check(production.every(x=>mine.files.includes(x)),"lease scope incomplete");
  for(const c of live.values())if(c.until>now&&c.agent!==p.agent)check(c.issue!==p.issue&&!production.some(x=>c.files.includes(x)),"conflicting active lease");
}

async function pages(api,path,cap){
  const out=[], seen=new Set();
  for(let i=1;i<=cap;i++){
    const page=await api.get(path+(path.includes("?")?"&":"?")+"per_page=100&page="+i);
    check(Array.isArray(page)&&page.length<=100,"invalid page");
    for(const row of page){
      check(row&&Number.isSafeInteger(row.id)&&row.id>0,"invalid comment ID");
      // A shifting/repeated page may omit a competing lease. Never silently
      // deduplicate a paginated feed and treat the resulting view as complete.
      check(!seen.has(row.id),"duplicate comment ID; incomplete comment feed");
      seen.add(row.id);out.push(row);
    }
    if(page.length<100)return out;
  }
  throw Error("incomplete comment feed");
}

async function checkClaims(api,p){
  const now=api.now(), issue=await api.get("/issues/"+p.issue);
  check(Number.isFinite(now)&&issue.number===p.issue&&issue.state==="open"&&!issue.pull_request,"issue or clock invalid");
  const since=new Date(now-3.5*3600000).toISOString();
  const global=await pages(api,"/issues/comments?since="+since+"&sort=created",6), local=await pages(api,"/issues/"+p.issue+"/comments",10);
  // The global and issue feeds are independent snapshots. Never let a stale
  // issue page silently overwrite a newer claim/release from the global feed.
  const rows=new Map();
  for(const c of [...global,...local]){
    check(typeof c.body==="string"&&typeof c.issue_url==="string"&&/\/issues\/\d+$/.test(c.issue_url)&&
          Number.isFinite(Date.parse(c.created_at))&&Number.isFinite(Date.parse(c.updated_at)),"incomplete comment metadata");
    const previous=rows.get(c.id);
    check(!previous||["body","issue_url","created_at","updated_at"].every(k=>previous[k]===c[k]),"inconsistent comment snapshots; retry");
    rows.set(c.id,c);
  }
  check(local.every(c=>Number(c.issue_url.split("/").pop())===p.issue),"wrong issue comment feed");
  leaseCheck([...rows.values()],p,now);
  return local;
}

async function tip(api){
  const h=await api.get("/git/ref/heads/develop");
  check(h.ref==="refs/heads/develop"&&h.object?.type==="commit"&&isSha(h.object.sha),"bad develop ref");
  return h.object.sha;
}

async function treeSnapshot(api,root){
  const t=await api.get("/git/trees/"+root+"?recursive=1");
  check(t.sha===root&&t.truncated===false&&Array.isArray(t.tree),"incomplete tree");
  const entries=new Map();
  for(const e of t.tree){
    check(typeof e.path==="string"&&e.path&&!entries.has(e.path)&&isSha(e.sha),"invalid tree entry");
    check(["blob","tree","commit"].includes(e.type)&&typeof e.mode==="string","invalid tree entry type/mode");
    entries.set(e.path,e);
  }
  return entries;
}

function verifyTreeDelta(before,after,changes){
  // Directory IDs naturally change with their contents. Compare all leaf
  // identities, including symlinks and submodules, not a paginated diff.
  const leaves=map=>new Map([...map].filter(([,e])=>e.type!=="tree"));
  const a=leaves(before), b=leaves(after), changed=[];
  for(const path of new Set([...a.keys(),...b.keys()])){
    const x=a.get(path), y=b.get(path);
    if(x?.sha!==y?.sha||x?.type!==y?.type||x?.mode!==y?.mode)changed.push(path);
  }
  check(JSON.stringify(changed.sort())===JSON.stringify(changes.map(x=>x.path).sort()),"unexpected candidate tree changes");
  for(const x of changes){
    const e=b.get(x.path);
    check(e?.type==="blob"&&e.mode==="100644","candidate missing or invalid mode: "+x.path);
  }
}

async function checkBase(api,p){
  const b=await api.get("/git/commits/"+p.base);
  check(b.sha===p.base&&isSha(b.tree?.sha),"invalid base");
  const entries=await treeSnapshot(api,b.tree.sha);
  const v=entries.get("src/version.py");
  check(v?.sha===p.versionBlob&&v.mode==="100644","version does not match offline AST proof");
  for(const c of p.changes){
    const x=entries.get(c.path)??null;
    check(c.old===null?x===null:x?.sha===c.old&&x.type==="blob"&&x.mode==="100644","stale base blob or mode: "+c.path);
  }
  return {sha:b.tree.sha,entries};
}

function candidateMessage(p){return p.message+" (Refs #"+p.issue+")"}

async function verifyCandidate(api,p,candidate){
  validate(p);
  check(isSha(candidate),"invalid candidate");
  const before=await checkBase(api,p);
  const c=await api.get("/git/commits/"+candidate);
  check(c.sha===candidate&&isSha(c.tree?.sha)&&c.parents?.length===1&&c.parents[0].sha===p.base,"candidate parent/tree mismatch");
  check(c.message===candidateMessage(p),"candidate message/issue mismatch");
  const after=await treeSnapshot(api,c.tree.sha);
  const v=after.get("src/version.py");
  check(v?.sha===p.versionBlob&&v.mode==="100644","candidate version changed");
  verifyTreeDelta(before.entries,after,p.changes);
  for(const x of p.changes){
    const t=after.get(x.path), file=await api.file(candidate,x.path);
    check(t?.mode==="100644"&&t.type==="blob"&&t.sha===file.sha&&file.content===x.content,"candidate content/mode mismatch: "+x.path);
  }
}

async function landed(api,candidate){
  const h=await tip(api);
  if(h===candidate)return true;
  const d=await api.get("/compare/"+candidate+"..."+h);
  // A status string alone is not proof of ancestry. Bind the comparison
  // to the exact candidate and require a strictly newer descendant.
  return d.base_commit?.sha===candidate&&d.merge_base_commit?.sha===candidate&&
    d.behind_by===0&&d.status==="ahead"&&Number.isSafeInteger(d.ahead_by)&&d.ahead_by>0;
}

// A pending receipt belongs to the issue, not a disposable agent identity.
// Successors must reconcile its exact candidate before preparing another.
function checkPending(comments,candidate=null){
  const pending=new Map(), resolved=new Set();
  for(const c of [...comments].sort((a,b)=>a.id-b.id)){
    const body=c.body||"";
    const m=body.match(/<!-- sc-connector-pending v1 sha=([0-9a-f]{40}) base=([0-9a-f]{40}) agent=([A-Za-z0-9-]+) -->/);
    if(m)pending.set(m[1],m[2]);
    for(const r of body.matchAll(/<!-- sc-(?:ship|connector-abandoned) v1 sha=([0-9a-f]{40}) -->/g)){
      if(pending.has(r[1]))resolved.add(r[1]);
    }
  }
  for(const sha of pending.keys())
    check(resolved.has(sha)||sha===candidate,"recover pending candidate "+sha+" first");
}

// Create immutable objects only. No branch update occurs until the later
// publication stage independently verifies the candidate and durable receipt.
async function createCandidate(api,p){
  validate(p);const comments=await checkClaims(api,p);
  checkPending(comments);
  check(await tip(api)===p.base,"stale base");
  const baseTree=await checkBase(api,p);
  const tree=await api.tree(baseTree.sha,p.changes.map(x=>({path:x.path,mode:"100644",type:"blob",content:x.content})));
  check(isSha(tree),"invalid tree");
  const candidate=await api.commit(tree,p.base,candidateMessage(p));
  check(isSha(candidate),"invalid candidate");
  return candidate;
}

async function prepare(api,p){
  const candidate=await createCandidate(api,p);
  await verifyCandidate(api,p,candidate);
  return candidate;
}

function pendingMarker(p,candidate){
  return "<!-- sc-connector-pending v1 sha="+candidate+" base="+p.base+" agent="+p.agent+" -->";
}

// Each stage independently revalidates its immutable candidate. Runners with
// a bounded tool-call budget can resume between stages without keeping a
// mutable in-memory assertion or weakening the original ship checks.
async function recordPending(api,p,candidate){
  validate(p);await verifyCandidate(api,p,candidate);
  const marker=pendingMarker(p,candidate);
  if(await landed(api,candidate))return candidate;
  const initial=await checkClaims(api,p);checkPending(initial,candidate);
  check(await tip(api)===p.base,"base moved; do not overwrite");
  if(!initial.some(c=>(c.body||"").includes(marker))){
    const id=await api.comment(p.issue,"Pending connector shipment; reconcile exact SHA before retry.\n"+marker);
    check(Number.isSafeInteger(id),"pending receipt not acknowledged");
    const confirmed=await pages(api,"/issues/"+p.issue+"/comments",10);
    check(confirmed.some(c=>c.id===id&&(c.body||"").includes(marker)),"pending receipt not visible");
  }
  return candidate;
}

async function publishPending(api,p,candidate){
  validate(p);await verifyCandidate(api,p,candidate);
  if(await landed(api,candidate))return candidate;
  const latest=await checkClaims(api,p);checkPending(latest,candidate);
  check(latest.some(c=>(c.body||"").includes(pendingMarker(p,candidate))),"pending receipt disappeared or missing");
  check(!latest.some(c=>(c.body||"").includes("<!-- sc-connector-abandoned v1 sha="+candidate+" -->")),"candidate abandoned");
  check(await tip(api)===p.base,"base moved before ref update");
  try{await api.update(p.base,candidate)}catch(e){/* acknowledgement may be lost; reconcile */}
  // A connector may briefly serve the old ref after accepting the update.
  // Reconcile with bounded read-only probes; never repeat the write here.
  for(let attempt=0;attempt<3;attempt++){
    try{if(await landed(api,candidate))return candidate}catch(e){/* retry read only */}
  }
  throw Error("shipment unconfirmed; preserve pending candidate");
}

async function recordHandover(api,p,candidate){
  validate(p);await verifyCandidate(api,p,candidate);
  check(await landed(api,candidate),"shipment unconfirmed; cannot record handover");
  const shipped="<!-- sc-ship v1 sha="+candidate+" -->";
  const comments=await pages(api,"/issues/"+p.issue+"/comments",10);
  if(!comments.some(c=>(c.body||"").includes(shipped))){
    // A successor may finish a landed shipment with its own identity, but
    // the original issue must contain the exact SHA/base delivery intent.
    const prefix="<!-- sc-connector-pending v1 sha="+candidate+" base="+p.base+" agent=";
    check(comments.some(c=>(c.body||"").includes(prefix)),"missing pending receipt for landed candidate");
    const id=await api.comment(p.issue,"Progress: connector progress slice\nHandover: "+p.next+"\nCommit: "+candidate+"\nVerification: "+p.verification+"\nFiles: "+p.changes.map(x=>x.path).join(", ")+"\n"+shipped);
    check(Number.isSafeInteger(id),"handover not acknowledged; retry exact candidate");
    const confirmed=await pages(api,"/issues/"+p.issue+"/comments",10);
    check(confirmed.some(c=>c.id===id&&(c.body||"").includes(shipped)),"handover not visible");
  }
  return candidate;
}

async function ship(api,p,candidate){
  await recordPending(api,p,candidate);
  await publishPending(api,p,candidate);
  return recordHandover(api,p,candidate);
}

function connectorAdapter(tools){
  const repo="gmanldn/smoothcast",url="https://api.github.com/repos/"+repo;
  return {
    now:()=>Date.now(),
    get:async path=>JSON.parse((await tools.mcp__GitHub__fetch({url:url+path})).result.content),
    file:async(ref,path)=>(await tools.mcp__GitHub__fetch_file({repository_full_name:repo,path,ref})).result,
    tree:async(base,entries)=>(await tools.mcp__GitHub__create_tree({repository_full_name:repo,base_tree_sha:base,tree_elements:entries})).result.sha,
    commit:async(tree,parent,message)=>(await tools.mcp__GitHub__create_commit({repository_full_name:repo,tree_sha:tree,parent_sha:parent,message})).result.sha,
    update:async(base,candidate)=>{const x=await tools.mcp__GitHub__update_ref({repository_full_name:repo,branch_name:"develop",sha:candidate,expected_sha:base,force:false});check(x.result.success===true,"ref update rejected")},
    comment:async(issue,comment)=>(await tools.mcp__GitHub__add_comment_to_issue({repo_full_name:repo,pr_number:issue,comment})).result.id
  };
}

export {validate,leaseCheck,pages,createCandidate,verifyCandidate,prepare,ship,recordPending,publishPending,recordHandover,connectorAdapter,treeSnapshot,verifyTreeDelta};
