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
