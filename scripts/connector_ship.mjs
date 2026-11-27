// Connector-only, develop-only progress and independently authorised PATCH release transport (#598, #631).
// Every nonempty progress shipment receives a single PATCH, independent of issue closure.
// versionBlob MUST come from offline
// canonical AST validation of exact pinned bytes; the connector re-derives
// the same proof from the served bytes and refuses mismatches.
import crypto from "node:crypto";
function check(ok,why){if(!ok)throw Error(why)}

// Re-derive the pinned blob identity from served bytes: the tree ID alone is
// not proof that the bytes the API serves match the offline AST validation.
function blobSha(content){
  const body=Buffer.from(content,"utf8");
  return crypto.createHash("sha1").update("blob "+body.length+"\0").update(body).digest("hex");
}

function isSha(x){return typeof x==="string"&&/^[0-9a-f]{40}$/.test(x)}

const VERSION_PART=/^(MAJOR|MINOR|PATCH)(\s*=\s*)(\d+)(\s*)$/gm;

function parseVersion(source){
  const found={};
  for(const m of source.matchAll(VERSION_PART)){
    if(m[1] in found)return null;
    found[m[1]]=Number(m[3]);
  }
  return Object.keys(found).length===3?found:null;
}

function validateVersionBump(baseSource,newSource){
  const a=parseVersion(baseSource), b=parseVersion(newSource);
  check(a!==null&&b!==null,"non-canonical version source");
  check(a.MAJOR===b.MAJOR&&a.MINOR===b.MINOR,"version lane bumps PATCH only");
  check(a.PATCH<2147483647,"PATCH overflow; owner must choose next MINOR");
  check(b.PATCH===a.PATCH+1,"version lane must bump PATCH by exactly one");
  const expected=baseSource.replace(VERSION_PART,(whole,key,eq,num,end)=>
    key==="PATCH"?key+eq+String(a.PATCH+1)+end:whole);
  check(newSource===expected,"version lane must preserve all non-PATCH bytes");
}

function validate(p){
  check(Number.isSafeInteger(p.issue)&&p.issue>0&&/^[A-Za-z0-9-]{1,80}$/.test(p.agent),"invalid issue/agent");
  check(isSha(p.base)&&isSha(p.versionBlob),"invalid base or version proof");
  check(p.kind===undefined||p.kind==="progress"||p.kind==="release"||p.kind==="finalise","invalid plan kind");
  // Fence old manifests before they can create, publish or close anything.
  // Native finish closes verified tickets without allocating a version.
  check(p.kind!=="finalise","per-ticket PATCH finalise retired; ship progress and use native finish");
  check(Array.isArray(p.changes)&&p.changes.length>0&&p.changes.length<=30,"invalid change count");
  const paths=new Set();
  for(const c of p.changes){
    check(typeof c.path==="string"&&/^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/.test(c.path)&&!c.path.split("/").some(x=>[".","..",".git"].includes(x)),"invalid path");
    check(p.kind==="release"||c.path!=="src/version.py","version edit or duplicate path");
    check(c.old===null||isSha(c.old),"invalid old blob");
    check(typeof c.content==="string"&&c.content.length<=500000,"bounded text only");
    check(!paths.has(c.path),"version edit or duplicate path");
    paths.add(c.path);
  }
  for(const k of ["message","verification","next"]){
    check(typeof p[k]==="string"&&p[k].trim()&&!/[\x00-\x1f\x7f]/.test(p[k]),"missing or multiline "+k);
    check(!/<!--\s*sc-/i.test(p[k]),"reserved protocol marker in "+k);
  }
  if(p.kind==="release"){
    check(paths.size===1&&paths.has("src/version.py"),"release ships exactly one version.py edit");
    check(p.changes[0].old===p.versionBlob,"release must replace the pinned version blob");
    check(isSha(p.releaseBlob)&&blobSha(p.changes[0].content)===p.releaseBlob,"release bytes disagree with offline AST proof");
    const v=parseVersion(p.changes[0].content);
    check(v!==null&&p.message==="chore(version): release "+[v.MAJOR,v.MINOR,v.PATCH].join("."),"release requires exact version subject");
  }
  if(p.kind==="finalise"){
    check(paths.size===1&&paths.has("src/version.py"),"finalise ships exactly one version.py edit");
    check(p.changes[0].old!==null,"finalise must replace the current version blob");
    // The general 500000-character manifest bound covers version.py too.
    check(["none","complete","no remaining work"].includes(p.next.trim().toLowerCase()),"finalise must close");
  }else{
    check(!["none","complete","no remaining work"].includes(p.next.trim().toLowerCase()),"progress only; no closure");
  }
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

function shipmentChanges(p,source){
  if(p.kind==="release"||p.kind==="finalise")return p.changes;
  const v=parseVersion(source);
  check(v!==null,"invalid canonical version");
  if(v.PATCH>=2147483647)return p.changes; // valid unchanged version; owner chooses next MINOR
  const content=source.replace(VERSION_PART,(whole,key,eq,num,end)=>key==="PATCH"?key+eq+String(v.PATCH+1)+end:whole);
  validateVersionBump(source,content);
  return [...p.changes,{path:"src/version.py",old:p.versionBlob,content}];
}

async function checkBase(api,p){
  const b=await api.get("/git/commits/"+p.base);
  check(b.sha===p.base&&isSha(b.tree?.sha),"invalid base");
  const entries=await treeSnapshot(api,b.tree.sha);
  const v=entries.get("src/version.py");
  check(v?.sha===p.versionBlob&&v.mode==="100644","version does not match offline AST proof");
  // Canonical AST proof: re-derive the pinned blob identity from the served
  // bytes, not just the tree ID the API reports.
  const served=await api.file(p.base,"src/version.py");
  check(typeof served?.content==="string"&&blobSha(served.content)===p.versionBlob,"served version bytes disagree with the pinned proof");
  if(p.kind==="release"){
    validateVersionBump(served.content,p.changes[0].content);
  }
  if(p.kind==="finalise"){
    // Complete historical PATCH attribution: walk every commit touching
    // src/version.py back to the initial import and refuse a second PATCH
    // for the same issue (one PATCH per completed ticket).
    const attributed=await versionHistory(api,p.base);
    check(!attributed.has(String(p.issue)),"issue already has a PATCH; one PATCH per completed ticket");
  }
  for(const c of p.changes){
    const x=entries.get(c.path)??null;
    check(c.old===null?x===null:x?.sha===c.old&&x.type==="blob"&&x.mode==="100644","stale base blob or mode: "+c.path);
  }
  return {sha:b.tree.sha,entries,changes:shipmentChanges(p,served.content)};
}

async function versionHistory(api,base){
  // Bounded complete walk: the walk ends at a partial page. Saturating every
  // page means the attribution record is not proven complete; fail closed.
  const attributed=new Map(),seen=new Set();
  for(let page=1;page<=10;page++){
    const list=await api.get("/commits?path=src/version.py&sha="+base+"&per_page=100&page="+page);
    check(Array.isArray(list)&&list.length<=100,"incomplete version history");
    for(const c of list){
      check(c&&isSha(c.sha)&&typeof c.commit?.message==="string","incomplete version history");
      check(!seen.has(c.sha),"incomplete version history: repeated commit");
      seen.add(c.sha);
      const subject=c.commit.message.split("\n",1)[0];
      const m=subject.match(/^chore\(version\): PATCH(?: \d+\.\d+\.\d+)? for issue #([1-9]\d*)(?: \[sc-auto-patch\])?$/);
      if(!m){
        check(!/^chore\(version\): PATCH.* for issue #/.test(subject),"malformed PATCH attribution");
        continue;
      }
      // Historical duplicates must never be rewritten, nor should they
      // block unrelated tickets. All known assignments still fence this issue.
      if(!attributed.has(m[1]))attributed.set(m[1],c.sha);
    }
    if(list.length<100)return attributed;
  }
  throw Error("incomplete version history");
}

function candidateMessage(p){
  if(p.kind==="finalise")return "chore(version): PATCH for issue #"+p.issue+" [sc-auto-patch]";
  return p.message+" (Refs #"+p.issue+")";
}

async function verifyCandidate(api,p,candidate){
  validate(p);
  check(isSha(candidate),"invalid candidate");
  const before=await checkBase(api,p);
  const c=await api.get("/git/commits/"+candidate);
  check(c.sha===candidate&&isSha(c.tree?.sha)&&c.parents?.length===1&&c.parents[0].sha===p.base,"candidate parent/tree mismatch");
  check(c.message===candidateMessage(p),"candidate message/issue mismatch");
  const after=await treeSnapshot(api,c.tree.sha);
  const v=after.get("src/version.py");
  if(p.kind==="release"){
    const baseVersion=await api.file(p.base,"src/version.py");
    const newVersion=await api.file(candidate,"src/version.py");
    check(blobSha(baseVersion.content)===p.versionBlob,"release base bytes disagree with offline AST proof");
    validateVersionBump(baseVersion.content,newVersion.content);
    check(v?.mode==="100644"&&v.sha===p.releaseBlob&&newVersion.sha===p.releaseBlob&&
          blobSha(newVersion.content)===p.releaseBlob,"release candidate bytes disagree with offline AST proof");
  }else if(p.kind==="finalise"){
    const baseVersion=await api.file(p.base,"src/version.py");
    const newVersion=await api.file(candidate,"src/version.py");
    validateVersionBump(baseVersion.content,newVersion.content);
    check(v?.mode==="100644"&&v.sha!==p.versionBlob,"finalise must replace the version blob");
  }else{
    const expected=before.changes.find(x=>x.path==="src/version.py");
    check(v?.sha===(expected?blobSha(expected.content):p.versionBlob)&&v.mode==="100644","candidate PATCH mismatch");
  }
  verifyTreeDelta(before.entries,after,before.changes);
  for(const x of before.changes){
    const t=after.get(x.path), file=await api.file(candidate,x.path);
    check(t?.mode==="100644"&&t.type==="blob"&&t.sha===file.sha&&file.content===x.content&&(x.path!=="src/version.py"||t.sha===blobSha(file.content)),"candidate content/mode mismatch: "+x.path);
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
  const tree=await api.tree(baseTree.sha,baseTree.changes.map(x=>({path:x.path,mode:"100644",type:"blob",content:x.content})));
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
    const candidateVersion=await api.file(candidate,"src/version.py");
    const fields=parseVersion(candidateVersion.content);
    check(fields!==null,"invalid shipped version");
    const versionChanged=candidateVersion.sha!==p.versionBlob;
    const id=await api.comment(p.issue,"Progress: connector progress slice\nHandover: "+p.next+"\nCommit: "+candidate+"\nVerification: "+p.verification+"\nVersion: "+[fields.MAJOR,fields.MINOR,fields.PATCH].join(".")+(versionChanged?" (incremented)":" (unchanged; allocation deferred)")+"\nFiles: "+[...p.changes.map(x=>x.path),...(p.kind!=="release"&&versionChanged?["src/version.py"]:[])].join(", ")+"\n"+shipped);
    check(Number.isSafeInteger(id),"handover not acknowledged; retry exact candidate");
    const confirmed=await pages(api,"/issues/"+p.issue+"/comments",10);
    check(confirmed.some(c=>c.id===id&&(c.body||"").includes(shipped)),"handover not visible");
  }
  return candidate;
}

// Close lane: the PATCH commit is landed and verified before the issue state
// flips. The close receipt is idempotent and must be visible before closing,
// so a lost close is retryable without minting a second PATCH.
function closeMarker(p,candidate){
  return "<!-- sc-connector-close v1 sha="+candidate+" -->";
}

async function checkAcceptance(api,p,candidate,comments){
  // Independent acceptance: the finalise must extend work already shipped and
  // landed on develop for this issue, not merely assert completion.
  const shipped=new Set();
  for(const c of comments)
    for(const m of (c.body||"").matchAll(/<!-- sc-ship v1 sha=([0-9a-f]{40}) -->/g))shipped.add(m[1]);
  for(const sha of shipped){
    const d=await api.get("/compare/"+sha+"..."+candidate);
    if(d.base_commit?.sha===sha&&d.merge_base_commit?.sha===sha&&d.behind_by===0&&d.status==="ahead"&&d.ahead_by>0)return;
  }
  throw Error("independent acceptance missing: finalise must extend shipped work");
}

async function closeTicket(api,p,candidate){
  validate(p);
  check(p.kind==="finalise","close ticket requires a finalise plan");
  await verifyCandidate(api,p,candidate);
  check(await landed(api,candidate),"finalise commit unconfirmed; cannot close");
  const comments=await pages(api,"/issues/"+p.issue+"/comments",10);
  const marker=closeMarker(p,candidate);
  const issue=await api.get("/issues/"+p.issue);
  if(issue.state!=="closed"){
    // Live close fencing: a competing lease or unshipped ancestry blocks the
    // open→closed transition. Once closed, the PATCH commit is already
    // immutable, so the fence does not run again on idempotent retries.
    await checkClaims(api,p);
    await checkAcceptance(api,p,candidate,comments);
  }
  if(!comments.some(c=>(c.body||"").includes(marker))){
    const id=await api.comment(p.issue,"Progress: PATCH lane landed\nHandover: "+p.next+"\nVerification: "+p.verification+"\nCommit: "+candidate+"\n"+marker);
    check(Number.isSafeInteger(id),"close receipt not acknowledged");
    const confirmed=await pages(api,"/issues/"+p.issue+"/comments",10);
    check(confirmed.some(c=>c.id===id&&(c.body||"").includes(marker)),"close receipt not visible");
  }
  if(issue.state!=="closed"){
    await api.close(p.issue);
    check((await api.get("/issues/"+p.issue)).state==="closed","issue close not acknowledged");
  }
  return candidate;
}

async function ship(api,p,candidate){
  await recordPending(api,p,candidate);
  await publishPending(api,p,candidate);
  if(p.kind==="finalise")return closeTicket(api,p,candidate);
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
    comment:async(issue,comment)=>(await tools.mcp__GitHub__add_comment_to_issue({repo_full_name:repo,pr_number:issue,comment})).result.id,
    close:async issue=>{
      const x=await tools.mcp__GitHub__update_issue({repo_full_name:repo,issue_number:issue,state:"closed"});
      check(x.result&&(x.result.state==="closed"||x.result.success===true),"issue close rejected")
    }
  };
}

export {validateVersionBump,validate,leaseCheck,pages,createCandidate,verifyCandidate,prepare,ship,recordPending,publishPending,recordHandover,closeTicket,closeMarker,connectorAdapter,treeSnapshot,verifyTreeDelta};
