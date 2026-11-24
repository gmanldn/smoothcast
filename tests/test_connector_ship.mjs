import test from "node:test";
import assert from "node:assert/strict";
import {validate,leaseCheck,pages,treeSnapshot,verifyTreeDelta,prepare,ship} from "../scripts/connector_ship.mjs";
const p={issue:598,agent:"test",base:"a".repeat(40),versionBlob:"b".repeat(40),
  changes:[{path:"src/foo.py",old:null,content:"pass\n"}],message:"fix",verification:"not run",next:"integration"};
const now=Date.parse("2026-11-24T07:00:00Z");
const row=(id,issue,body)=>({id,issue_url:"https://api.github.com/repos/gmanldn/smoothcast/issues/"+issue,
  body,created_at:"2026-11-24T06:55:00Z",updated_at:"2026-11-24T06:55:00Z"});
const mine=row(1,598,"<!-- sc-claim v1 agent=test ttl=30 files=src/foo.py -->");
test("valid plan and scoped live lease",()=>{validate(p);leaseCheck([mine],p,now)});
test("no version writes or path traversal",()=>{for(const path of ["src/version.py","src/../foo.py",".git/config"])assert.throws(()=>validate({...p,changes:[{...p.changes[0],path}]}))});
test("no duplicate paths",()=>assert.throws(()=>validate({...p,changes:[...p.changes,...p.changes]})));
test("no absent or expired lease",()=>{assert.throws(()=>leaseCheck([],p,now));assert.throws(()=>leaseCheck([mine],p,now+3600000))});
test("release wins in comment ID order",()=>assert.throws(()=>leaseCheck([row(2,598,"<!-- sc-release v1 agent=test -->"),mine],p,now)));
test("other issue's overlapping lease is rejected",()=>assert.throws(()=>leaseCheck([mine,row(2,599,"<!-- sc-claim v1 agent=other ttl=30 files=src/foo.py -->")],p,now)));
test("missing server timestamps fail closed",()=>assert.throws(()=>leaseCheck([{...mine,created_at:null}],p,now)));
test("scope must cover source paths",()=>assert.throws(()=>leaseCheck([mine],{...p,changes:[{...p.changes[0],path:"src/bar.py"}]},now)));
test("pagination saturation fails closed",async()=>{
  let n=0;
  await assert.rejects(pages({get:async()=>Array.from({length:100},()=>({id:++n}))},"/issues/comments",2),/incomplete comment feed/);
});
test("complete page accepted",async()=>assert.deepEqual(await pages({get:async()=>[{id:1}]},"/issues/comments",2),[{id:1}]));

const id=x=>x.repeat(40);
const leaf=(path,sha='a',mode='100644',type='blob')=>({path,sha:id(sha),mode,type});
const entries=(...xs)=>new Map(xs.map(x=>[x.path,x]));
const before=entries(leaf('src','a','040000','tree'),leaf('src/a.py'),leaf('src/version.py','b'));
const after=entries(leaf('src','c','040000','tree'),leaf('src/a.py','d'),leaf('src/version.py','b'));
const changes=[{path:'src/a.py'}];
test('directory ID changes are expected',()=>verifyTreeDelta(before,after,changes));
test('undeclared addition rejected',()=>assert.throws(()=>verifyTreeDelta(before,entries(...after.values(),leaf('surprise')),changes),/unexpected/));
test('undeclared deletion rejected',()=>assert.throws(()=>verifyTreeDelta(before,entries(...[...after.values()].filter(x=>x.path!=='src/version.py')),changes),/unexpected/));
test('rename cannot conceal source deletion',()=>assert.throws(()=>verifyTreeDelta(before,entries(leaf('src/new.py','a'),leaf('src/version.py','b')),[{path:'src/new.py'}]),/unexpected/));
test('undeclared mode edit rejected',()=>assert.throws(()=>verifyTreeDelta(before,entries(...after.values(),leaf('src/version.py','b','100755')),changes),/unexpected/));
test('declared symlink rejected',()=>assert.throws(()=>verifyTreeDelta(before,entries(...after.values(),leaf('src/a.py','d','120000')),changes),/invalid mode/));
test('truncated tree rejected',async()=>assert.rejects(treeSnapshot({get:async()=>({sha:id('a'),truncated:true,tree:[]})},id('a')),/incomplete/));
test('duplicate path rejected',async()=>assert.rejects(treeSnapshot({get:async()=>({sha:id('a'),truncated:false,tree:[leaf('a'),leaf('a')]})},id('a')),/invalid tree entry/));
test('valid tree snapshot',async()=>assert.deepEqual(await treeSnapshot({get:async()=>({sha:id('a'),truncated:false,tree:[leaf('a')]})},id('a')),entries(leaf('a'))));

test("duplicate IDs within a page fail closed",async()=>assert.rejects(
  pages({get:async()=>[{id:1},{id:1}]},"/issues/comments",2),/duplicate comment ID/));
test("overlapping pages fail closed instead of hiding a missing claim",async()=>{
  let n=0;
  await assert.rejects(pages({get:async()=>n++===0?Array.from({length:100},(_,i)=>({id:i+1})):[{id:100}]},
    "/issues/comments",2),/duplicate comment ID/);
});
test("invalid ID and oversized page fail closed",async()=>{
  for(const page of [[{}],[{id:0}],[{id:"1"}],[{id:1.5}],Array.from({length:101},(_,i)=>({id:i+1}))])
    await assert.rejects(pages({get:async()=>page},"/issues/comments",2));
});

function transport(){
  const baseTree=id("c"), newTree=id("d"), candidate=id("e"), newBlob=id("f");
  const comments=[mine], counters={trees:0,commits:0,updates:0};
  const state={head:p.base,parents:[{sha:p.base}],updateMode:"ok",hidePending:false,raceAfterPending:false};
  const api={
    now:()=>now,
    get:async path=>{
      if(path==="/issues/598")return {number:598,state:"open"};
      if(path.startsWith("/issues/comments?"))return state.globalOverride??[...comments];
      if(path.startsWith("/issues/598/comments?"))return state.localOverride??comments.filter(c=>c.issue_url.endsWith("/598"));
      if(path==="/git/ref/heads/develop")return {ref:"refs/heads/develop",object:{type:"commit",sha:state.head}};
      if(path==="/git/commits/"+p.base)return {sha:p.base,tree:{sha:baseTree}};
      if(path==="/git/commits/"+candidate)return {sha:candidate,tree:{sha:newTree},parents:state.parents};
      if(path==="/git/trees/"+baseTree+"?recursive=1")return {sha:baseTree,truncated:false,tree:[leaf("src/version.py","b")]};
      if(path==="/git/trees/"+newTree+"?recursive=1")return {sha:newTree,truncated:false,tree:[leaf("src/version.py","b"),leaf("src/foo.py","f")]};
      if(path.startsWith("/compare/"+candidate+"..."))return {status:"behind",behind_by:1};
      throw Error("unexpected GET "+path);
    },
    file:async(ref,path)=>{assert.equal(ref,candidate);assert.equal(path,"src/foo.py");return {sha:newBlob,content:p.changes[0].content}},
    tree:async(base,changes)=>{assert.equal(base,baseTree);assert.deepEqual(changes,[{path:"src/foo.py",mode:"100644",type:"blob",content:"pass\n"}]);counters.trees++;return newTree},
    commit:async(tree,parent,message)=>{assert.equal(tree,newTree);assert.equal(parent,p.base);assert.equal(message,"fix (Refs #598)");counters.commits++;return candidate},
    update:async(base,sha)=>{
      counters.updates++;assert.equal(base,p.base);assert.equal(sha,candidate);
      if(state.updateMode==="reject")throw Error("ref rejected");
      state.head=sha;
      if(state.updateMode==="lost")throw Error("lost acknowledgement");
    },
    comment:async(issue,body)=>{
      assert.equal(issue,598);
      const nextId=comments.length+1;
      if(!(state.hidePending&&body.includes("sc-connector-pending")))comments.push(row(nextId,598,body));
      if(state.raceAfterPending&&body.includes("sc-connector-pending"))state.head=id("9");
      return nextId;
    }
  };
  return {api,state,counters,comments,candidate};
}

test("prepare and ship verify candidate, persist receipt, and replay without duplicates",async()=>{
  const t=transport(), c=await prepare(t.api,p);
  assert.equal(c,t.candidate);
  await ship(t.api,p,c);
  assert.equal(t.state.head,c);
  assert.equal(t.comments.filter(x=>x.body.includes("sc-connector-pending")).length,1);
  assert.equal(t.comments.filter(x=>x.body.includes("sc-ship v1")).length,1);
  await ship(t.api,p,c);
  assert.deepEqual(t.counters,{trees:1,commits:1,updates:1});
  assert.equal(t.comments.length,3);
});
test("stale base prevents immutable object creation",async()=>{
  const t=transport();t.state.head=id("9");
  await assert.rejects(prepare(t.api,p),/stale base/);
  assert.deepEqual(t.counters,{trees:0,commits:0,updates:0});
});
test("wrong candidate parent prevents any ref update",async()=>{
  const t=transport();t.state.parents=[{sha:id("9")}];
  await assert.rejects(prepare(t.api,p),/candidate parent/);
  assert.equal(t.counters.updates,0);
});
test("unconfirmed pending receipt prevents ref update",async()=>{
  const t=transport(), c=await prepare(t.api,p);
  t.state.hidePending=true;
  await assert.rejects(ship(t.api,p,c),/pending receipt not visible/);
  assert.equal(t.counters.updates,0);
});
test("lost update acknowledgement reconciles the same landed candidate",async()=>{
  const t=transport(), c=await prepare(t.api,p);
  t.state.updateMode="lost";
  await ship(t.api,p,c);
  assert.equal(t.state.head,c);
  assert.equal(t.counters.updates,1);
  assert.equal(t.comments.filter(x=>x.body.includes("sc-ship v1")).length,1);
});
test("rejected update preserves pending receipt and blocks duplicate preparation",async()=>{
  const t=transport(), c=await prepare(t.api,p);
  t.state.updateMode="reject";
  await assert.rejects(ship(t.api,p,c),/shipment unconfirmed/);
  await assert.rejects(prepare(t.api,p),/recover pending candidate/);
  t.state.updateMode="ok";
  await ship(t.api,p,c);
  assert.deepEqual(t.counters,{trees:1,commits:1,updates:2});
  assert.equal(t.comments.filter(x=>x.body.includes("sc-connector-pending")).length,1);
});
test("base movement after receipt prevents ref update",async()=>{
  const t=transport(), c=await prepare(t.api,p);
  t.state.raceAfterPending=true;
  await assert.rejects(ship(t.api,p,c),/base moved before ref update/);
  assert.equal(t.counters.updates,0);
});
test("new competing lease after preparation prevents ref update",async()=>{
  const t=transport(), c=await prepare(t.api,p);
  t.comments.push(row(2,599,"<!-- sc-claim v1 agent=other ttl=30 files=src/foo.py -->"));
  await assert.rejects(ship(t.api,p,c),/conflicting active lease/);
  assert.equal(t.counters.updates,0);
});

test("inconsistent global and issue claim snapshots prevent preparation",async()=>{
  const t=transport();
  t.state.globalOverride=[{...mine,body:"<!-- sc-release v1 agent=test -->",updated_at:"2026-11-24T06:56:00Z"}];
  await assert.rejects(prepare(t.api,p),/inconsistent comment snapshots/);
  assert.equal(t.counters.commits,0);
});
test("missing body in global comment feed prevents preparation",async()=>{
  const t=transport();t.state.globalOverride=[mine,{...row(2,599,""),body:null}];
  await assert.rejects(prepare(t.api,p),/incomplete comment metadata/);
});
test("wrong issue in local comment feed prevents preparation",async()=>{
  const t=transport();t.state.localOverride=[mine,row(2,599,"ordinary comment")];
  await assert.rejects(prepare(t.api,p),/wrong issue comment feed/);
});
