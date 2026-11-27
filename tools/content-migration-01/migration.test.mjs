import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createHash} from "node:crypto";
import {parse,convertField,practiceQuestions} from "./convert.mjs";
import {examDescriptor} from "./exam.mjs";
import {plan,reconcile,simulate,nativeId} from "./migration.mjs";
const data=()=>JSON.parse(readFileSync(new URL("./synthetic.json",import.meta.url)));
const subject=data().records[0].subject_id;
const paper={grade:"NS4",track:"NS4",series:"LLA",year:2023,subject_id:subject,pdf_ref:"paper",duration_minutes:120,exam_type:"official",revision:1};

test("a repeatable full projection with source order, educational text and answer bound to a real choice",()=>{
  const a=data(), {entry,target}=plan(a).packets[0];
  assert.deepEqual(entry.issues,[]);
  assert.deepEqual(target.blocks.map(b=>b.text),["Sommes","Compter des jetons.","2 + 3 = 5","1. Compter.","2. Vérifier."]);
  assert.equal(target.questions[0].answer_key.correct_choice_id,"A");
  assert.deepEqual(plan(a),plan(structuredClone(a)));
  const report=reconcile(a,simulate(a,simulate(a)));
  assert.equal(report.results[0].status,"matched");
  assert.equal(report.coverage.publication_ready.numerator,0);
});
test("identity is namespaced and stable across revisions",()=>{
  const s=data().records[0];
  assert.equal(nativeId("lessons",s.id),nativeId("lessons",s.id));
  assert.notEqual(nativeId("lessons",s.id),nativeId("ebooks",s.id));
  const h=createHash("sha256").update("edupreneurs:legacy-v1/lessons/"+s.id).digest("hex");
  assert.equal(nativeId("lessons",s.id).replaceAll("-",""),h.slice(0,12)+"8"+h.slice(13,16)+"8"+h.slice(17,32));
});
for(const [label,patch,reason] of [
  ["locale",{locale:null},"locale_unverified"],["misassigned grade",{grade:"8AF"},"hierarchy_mismatch"],
  ["wrong subject",{subject_id:data().records[0].id},"hierarchy_mismatch"],["missing series",{grade:"NS3"},"series_mismatch"],
  ["missing unit",{unit_id:null},"missing_unit_mapping"],["false mathematics",{contenu:"<p>2 + 2 = 5</p>"},"contenu:false_math"],
  ["malformed math",{contenu:"<p>2 + = 2</p>"},"contenu:math_needs_review"],
  ["image resolution",{contenu:'<img src="missing" alt="sample">'},"unresolved_image_reference"],
  ["unknown column",{interactive_diagram:"sample"},"unmapped_source_field"],
  ["unreviewed activity",{activites_interactives:"<p>sample</p>"},"activity_semantics_unverified"],
]) test(label,()=>{const s=data();Object.assign(s.records[0],patch);const p=plan(s).packets[0];assert.ok(p.entry.issues.includes(reason));assert.equal(p.target,null);});
for(const tag of ["table","svg","iframe","script","math"]) test("unsupported "+tag,()=>{
  const part=convertField("<p>Hello</p><"+tag+">sample</"+tag+">");
  assert.deepEqual(part.blocks,[]);assert.ok(part.issues.includes("unsupported_element:"+tag));
});
test("emphasis and images retain a private semantic representation",()=>{
  const v=convertField('<p><em>important</em><img src="diagram" alt="two lines"></p>');
  assert.equal(v.sourceTree.children[0].children[0].tag,"em");
  assert.equal(v.assets[0].alt,"two lines");assert.deepEqual(v.blocks,[]);
});
test("unbalanced, ambiguous markup and excessive input are refused",()=>{
  for(const s of ["<p>a",'<p a="1" a="2">a</p>',"a".repeat(200001)])assert.throws(()=>parse(s));
});
test("ambiguous or mismatched practice keys quarantine the whole set",()=>{
  const s=data().records[0].quiz_final;
  assert.throws(()=>practiceQuestions(s.replace('data-answer="B"','data-answer="A"')));
  assert.throws(()=>practiceQuestions(s.replace("Réponse : A","Réponse : B")));
});
test("missing, unexpected, excluded and explicitly quarantined rows",()=>{
  const s=data(),p=plan(s).packets;
  assert.equal(reconcile(s,[]).results[0].status,"missing");
  assert.equal(reconcile(s,[],[{source_sha256:p[0].entry.source_sha256,reason:"retired",decision_ref:"signed:test"}]).results[0].status,"approved_exclusion");
  const unknown=structuredClone(p[0]);unknown.entry.legacy_id=subject;
  assert.deepEqual(reconcile(s,[...p,unknown]).results.map(x=>x.status),["transformed","unexpected"]);
  s.records[0].locale=null;
  assert.equal(reconcile(s,plan(s).packets).results[0].status,"quarantined");
});
test("removed educational text, crossed locale, a forged ID or fabricated approval fails reconciliation",()=>{
  const s=data();
  for(const change of [p=>p.target.blocks.pop(),p=>p.entry.hierarchy.grade="NS4",p=>p.entry.published=true,p=>p.entry.native_id=subject,p=>p.entry.locale="ht"]){
    const target=plan(s).packets;change(target[0]);
    assert.ok(reconcile(s,target).results.some(r=>["changed","missing"].includes(r.status)));
  }
});
test("duplicate slots and stale or conflicting revision cannot overwrite a previous import",()=>{
  const s=data(),history=simulate(s);
  assert.throws(()=>reconcile(s,[history[0],history[0]]));
  s.records.push(s.records[0]);assert.throws(()=>plan(s));s.records.pop();
  s.records[0].title="Changed";assert.throws(()=>simulate(s,history),/same_revision_conflict/);
  s.records[0].revision=2;const next=simulate(s,history);assert.equal(next.length,2);
  s.records[0].revision=1;assert.throws(()=>simulate(s,[next[1]]),/stale_revision/);
});
test("exercise scoring is never inferred from a stored answer",()=>{
  const s={points:5,position:1,has_prompt:true,exercise_type:"multiple_choice",has_answer:true,has_explanation:true};
  let p=examDescriptor("exam_exercises",s);assert.equal(p.descriptor.mode,"quarantined");assert.equal(p.descriptor.auto_gradable,false);
  assert.equal(examDescriptor("exam_exercises",{...s,exercise_type:"open-ended"}).descriptor.mode,"human_marked_or_self_review");
  assert.equal(examDescriptor("exam_exercises",{...s,has_prompt:false}).descriptor.mode,"pdf_only_or_insufficient");
  assert.ok(examDescriptor("official_exams",{...paper,duration_minutes:null}).issues.includes("unusable_duration"));
});

test("source hierarchy join and an independent fingerprint bind the assignments",async()=>{
  const {adaptLesson}=await import("./adapt.mjs");
  const {digest}=await import("./migration.mjs");
  const {fields}=await import("./convert.mjs");
  const s=data().records[0], body=Object.fromEntries(fields.map(k=>[k,s[k]]));
  const row={...body,id:s.id,title:s.title,subject_id:subject,grade_level:"7AF",source_revision:1,subject_grade:"7AF",subject_series:null,workflow_status:"published"};
  const parent={id:subject,grade_level:"7AF",series:null};
  const assignment={lesson_id:row.id,subject_id:subject,source_content_sha256:digest({title:s.title,...body}),decision_ref:"test-receipt",locale:"fr",unit_id:s.unit_id,revision:1};
  const result=adaptLesson(row,parent,assignment);
  assert.equal(result.subject_id,nativeId("subjects",subject));
  assert.deepEqual(result.supplemental_sha256,{});
  assert.equal(result.locale,"fr");
  assert.equal(adaptLesson(row,parent,{...assignment,lesson_id:subject}).locale,null);
  assert.equal(adaptLesson({...row,title:"changed"},parent,assignment).locale,null);
  assert.throws(()=>adaptLesson({...row,subject_series:"SES"},parent,assignment));
  assert.ok(adaptLesson({...row,youtube_url:"test-ref"},parent,assignment).supplemental_sha256.youtube_url);
});
test("asset observations bind bytes, detected MIME type and length",async()=>{
  const {observeAsset}=await import("./migration.mjs");
  const bytes=Buffer.from("synthetic"), actual=observeAsset(bytes,"text/plain");
  const s=data();s.records[0].assets=[{id:subject,ref:"private:test",bytes:bytes.length,mime:"text/plain",sha256:actual.observed_sha256,...actual}];
  assert.ok(plan(s).packets[0].entry.assets[0].verified);
  for(const patch of [observeAsset(Buffer.from("different"),"text/plain"),{observed_mime:"image/png"},{observed_bytes:0}]) {
    const copy=structuredClone(s);Object.assign(copy.records[0].assets[0],patch);
    assert.ok(plan(copy).packets[0].entry.issues.includes("unverified_asset"));
  }
});
test("a missing body and supplemental content cannot produce a completed lesson",()=>{
  for(const patch of [{contenu:null},{supplemental_sha256:{audio:"x"}}]){
    const s=data();Object.assign(s.records[0],patch);assert.equal(plan(s).packets[0].target,null);
  }
});
test("exam parents, ordering, score and independent sealed-key comparison",async()=>{
  const {adaptPaper,adaptExercise}=await import("./adapt.mjs");
  const {compareSealedKey}=await import("./exam.mjs");
  const s=data().records[0], row={id:subject,title:"Synthetic",grade_level:"9AF",series:null,subject_slug:"subject",version_number:2};
  const p=adaptPaper(row,{'["9AF",null,"subject"]':s.subject_id});
  assert.equal(p.subject_id,s.subject_id);
  const x={id:s.id,exam_id:subject,exercise_number:4,points:6,exercise_type:"open-ended",has_prompt:true};
  const a=adaptExercise(x,p);assert.equal(a.parent_id,nativeId("official_exams",subject));assert.equal(a.position,4);assert.equal(a.points,6);
  assert.throws(()=>adaptExercise({...x,exam_id:s.id},p));
  const proposal={item_id:s.id,revision:1,content_sha256:"1".repeat(64),choice_ids:["x","y"],correct_choice_id:"x"};
  const receipt={...proposal,owner_accepted:true,independent_reviewer:"synthetic",review_ref:"test"};
  assert.equal(compareSealedKey(proposal,null).mode,"quarantined");
  assert.equal(compareSealedKey(proposal,{...receipt,correct_choice_id:"y"}).reason,"key_mismatch");
  assert.equal(compareSealedKey(proposal,{...receipt,revision:2}).mode,"quarantined");
  assert.deepEqual(compareSealedKey(proposal,receipt),{mode:"verified_auto_gradable",review_ref:"test"});
});
test("question revision IDs are deterministic and revision scoped",()=>{
  const s=data(), a=plan(s).packets[0].entry;
  assert.deepEqual(plan(s).packets[0].entry.practice_items,a.practice_items);
  s.records[0].revision++;const b=plan(s).packets[0].entry;
  assert.equal(b.native_id,a.native_id);assert.notEqual(b.revision_id,a.revision_id);
  assert.notEqual(b.practice_items[0].revision_item_id,a.practice_items[0].revision_item_id);
});

test("independent inventory catches omission even when both plan and observed payload omit a lesson",async()=>{
  const {compareCensus}=await import("./migration.mjs");
  const {records}=data(), s=records[0], row={source_table:s.table,legacy_id:s.id,native_id:nativeId(s.table,s.id)};
  assert.equal(compareCensus([row],[]).results[0].status,"missing");
  assert.equal(compareCensus([],records).results[0].status,"unexpected");
  assert.equal(compareCensus([row],records).results[0].status,"matched");
  assert.equal(compareCensus([{...row,native_id:subject}],records).results[0].status,"changed");
  assert.throws(()=>compareCensus([row,row],records));
});

test("two exercises cannot occupy the same paper revision position",()=>{
  const s=data(), base={...s.records[0],table:"exam_exercises",parent_id:subject,position:1,exercise_type:"open-ended",points:1,has_prompt:true};
  s.records=[base,{...base,id:subject}];
  assert.throws(()=>plan(s),/duplicate_exercise_position/);
});
