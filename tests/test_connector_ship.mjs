import test from "node:test";
import assert from "node:assert/strict";
import {validate,leaseCheck,pages} from "../scripts/connector_ship.mjs";
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
test("pagination saturation fails closed",async()=>assert.rejects(pages({get:async()=>Array(100).fill({id:1})},"/issues/comments",2)));
test("complete page accepted",async()=>assert.deepEqual(await pages({get:async()=>[{id:1}]},"/issues/comments",2),[{id:1}]));
