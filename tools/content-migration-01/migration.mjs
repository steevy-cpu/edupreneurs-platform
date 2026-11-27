import {createHash} from "node:crypto";
import {lesson} from "./convert.mjs";
import {examDescriptor} from "./exam.mjs";

export const transform="content-migration-01.1";
const grades=new Set(["7AF","8AF","9AF","NS1","NS2","NS3","NS4"]);
const series=new Set(["LLA","SES","SMP","SVT"]);
const tables=new Set(["subjects","lessons","lesson_versions","official_exams","exam_exercises","lesson_videos","ebooks","storage.objects"]);
const uuid=/^[a-f\d]{8}-(?:[a-f\d]{4}-){3}[a-f\d]{12}$/;
const sha=/^[a-f\d]{64}$/;
export function canonical(x) {
  if (x===null || typeof x==="string" || typeof x==="boolean" || Number.isSafeInteger(x)) return JSON.stringify(x);
  if (Array.isArray(x)) return "["+x.map(canonical).join(",")+"]";
  if (!x || typeof x!=="object" || ![null,Object.prototype].includes(Object.getPrototypeOf(x))) throw Error("noncanonical_value");
  return "{"+Object.keys(x).sort().map(k=>JSON.stringify(k)+":"+canonical(x[k])).join(",")+"}";
}
export function digest(x) { return createHash("sha256").update(canonical(x),"utf8").digest("hex"); }
export function nativeId(table,id) {
  if (!tables.has(table) || !uuid.test(id)) throw Error("invalid_source_identity");
  const h=createHash("sha256").update("edupreneurs:legacy-v1/"+table+"/"+id).digest("hex");
  return [h.slice(0,8),h.slice(8,12),"8"+h.slice(13,16),"8"+h.slice(17,20),h.slice(20,32)].join("-");
}

export function project(s) {
  const id=nativeId(s.table,s.id);
  const issues=new Set(), assets=[], refs=new Map();
  const permitted=new Set(["table","id","title","revision","locale","grade","series","subject_id","unit_id","parent_id","assets","source_ref","rights_ref","workflow_status",
    "objectif","introduction","contenu","exemples_exercices","activites_interactives","quiz_final","track","pdf_ref","year","exam_type","session","duration_minutes",
    "position","points","exercise_type","has_prompt","has_answer","has_explanation"]);
  if(Object.keys(s).some(k=>!permitted.has(k))) issues.add("unmapped_source_field");
  for(const a of s.assets??[]) {
    if (!a || !uuid.test(a.id) || typeof a.ref!=="string" || !a.ref || refs.has(a.ref) || assets.some(x=>x.id===a.id)) {
      issues.add("invalid_asset_identity"); continue;
    }
    const verified=sha.test(a.sha256??"") && a.sha256===a.observed_sha256 && Number.isSafeInteger(a.bytes) && a.bytes>0 &&
      a.bytes===a.observed_bytes && typeof a.mime==="string" && a.mime===a.observed_mime && /^[a-z0-9.+-]+\/[a-z0-9.+-]+$/.test(a.mime);
    if(!verified) issues.add("unverified_asset");
    refs.set(a.ref,a.id);
    assets.push({id:a.id,mime:typeof a.mime==="string"?a.mime:null,bytes:Number.isSafeInteger(a.bytes)&&a.bytes>=0?a.bytes:null,sha256:sha.test(a.sha256??"")?a.sha256:null,verified});
  }
  const hierarchy={grade:s.grade??null,series:s.series??null,subject_id:s.subject_id??null,unit_id:s.unit_id??null,parent_id:s.parent_id??null};
  if (!grades.has(s.grade)) issues.add("missing_grade");
  if (["NS3","NS4"].includes(s.grade)?!series.has(s.series):s.series!=null) issues.add("series_mismatch");
  if (!uuid.test(s.subject_id??"")) issues.add("missing_subject_mapping");
  if (!Number.isSafeInteger(s.revision) || s.revision<=0) issues.add("source_revision_required");
  if(s.locale!=="fr" && s.locale!=="ht") issues.add("locale_unverified");
  let target=null;
  if(s.table==="lessons") {
    if(!uuid.test(s.unit_id??"")) issues.add("missing_unit_mapping");
    if(typeof s.title!=="string" || !s.title.trim() || [...s.title].length>200) issues.add("invalid_title");
    const parsed=lesson(s);
    parsed.issues.forEach(x=>issues.add(x));
    for(const asset of parsed.assets) if(!refs.has(asset.reference)) issues.add("unresolved_image_reference");
    target={title:s.title??null,blocks:parsed.blocks,questions:parsed.questions};
  } else if (["official_exams","exam_exercises"].includes(s.table)) {
    const p=examDescriptor(s.table,s);
    p.issues.forEach(x=>issues.add(x));
    if(s.table==="official_exams" && !refs.has(s.pdf_ref)) issues.add("unresolved_pdf");
    if(s.table==="exam_exercises" && !uuid.test(s.parent_id??"")) issues.add("missing_exam");
    target=p.descriptor;
  } else issues.add("inventory_only");
  // Unknown licensing is a release blocker even for structurally convertible drafts.
  // A source field called approved/reviewed is never an approval on the target.
  const entry={schema_version:1,transform,source_table:s.table,legacy_id:s.id,native_id:id,revision:Number.isSafeInteger(s.revision)&&s.revision>0?s.revision:null,
    locale:["fr","ht"].includes(s.locale)?s.locale:null,hierarchy,source_sha256:digest(s),target_sha256:issues.size?null:digest(target),
    content_sha256:digest(s.table==="lessons"?Object.fromEntries(["title","objectif","introduction","contenu","exemples_exercices","activites_interactives","quiz_final"].map(k=>[k,s[k]??null])):s),
    assets,provenance:{rights_ref:s.rights_ref??null,source_ref:s.source_ref??null,source_status:s.workflow_status??null},
    review:"draft_unreviewed",published:false,issues:[...issues].sort()};
  return {entry,target:issues.size?null:target};
}

export function plan(source) {
  if(!source.snapshot || !/^[0-9a-f]{40}$/.test(source.snapshot.commit) || !/Z$|[+]00:00$/.test(source.snapshot.time) || !Number.isFinite(Date.parse(source.snapshot.time))) throw Error("invalid_snapshot");
  const packets=source.records.map(project);
  const subjects=new Map(), units=new Map();
  for(const s of source.hierarchy.subjects) {
    if(subjects.has(s.id)) throw Error("duplicate_subject"); subjects.set(s.id,s);
  }
  for(const u of source.hierarchy.units) {
    if(units.has(u.id)) throw Error("duplicate_unit"); units.set(u.id,u);
  }
  for(const packet of packets) {
    const e=packet.entry,h=e.hierarchy,subject=subjects.get(h.subject_id);
    if(!subject || h.grade!==subject.grade || h.series!==subject.series) e.issues.push("hierarchy_mismatch");
    if(e.source_table==="lessons" && units.get(h.unit_id)?.subject_id!==h.subject_id) e.issues.push("unit_subject_mismatch");
    if(e.issues.length) {e.issues=[...new Set(e.issues)].sort(); e.target_sha256=null; packet.target=null;}
  }
  const slots=new Set();
  for(const {entry:e} of packets) {
    const k=slot(e);
    if(slots.has(k)) throw Error("duplicate_source_slot");
    slots.add(k);
  }
  packets.sort((a,b)=>slot(a.entry)<slot(b.entry)?-1:1);
  return {schema_version:1,snapshot:source.snapshot,transform,packets};
}
function slot(e) { return canonical([e.source_table,e.legacy_id,e.locale,e.revision]); }

export function reconcile(source,observed,exclusions=[]) {
  const expected=plan(source), actual=new Map(), results=[];
  for(const packet of observed) {
    const k=slot(packet.entry);
    if(actual.has(k)) throw Error("duplicate_target_slot");
    actual.set(k,packet);
  }
  const allowed=new Map(exclusions.map(e=>[e.source_sha256,e]));
  let structurallyConverted=0, inventoried=0, localeKnown=0,assetReferences=0,assetVerified=0;
  for(const {entry:e} of expected.packets) {
    const k=slot(e), a=actual.get(k), exception=allowed.get(e.source_sha256);
    const reasons=[...e.issues];
    for(const asset of e.assets){assetReferences++; if(asset.verified && a?.entry?.assets?.some(x=>canonical(x)===canonical(asset))) assetVerified++;}
    let status;
    if(!a && exception?.decision_ref && exception?.reason) status="approved_exclusion";
    else if(!a) status="missing";
    else {
      actual.delete(k);
      const verified = canonical(e)===canonical(a.entry) && (e.target_sha256===null?a.target===null:digest(a.target)===e.target_sha256);
      if(!verified) {status="changed"; reasons.push("metadata_or_payload_conflict");}
      else {
        inventoried++;
        if(["fr","ht"].includes(e.locale)) localeKnown++;
        if(e.issues.length) status="quarantined";
        else {status=a.origin==="existing"?"matched":"transformed";structurallyConverted++;}
      }
    }
    results.push({slot:k,status,reasons});
  }
  for(const k of [...actual.keys()].sort()) results.push({slot:k,status:"unexpected",reasons:["unknown_source_slot"]});
  const total=expected.packets.length;
  return {snapshot:expected.snapshot,total,results,coverage:{inventory:{numerator:inventoried,denominator:total},
    structural:{numerator:structurallyConverted,denominator:total},asset_integrity:{verified_listed_refs:assetVerified,listed_refs:assetReferences},
    language:{known_source_locale:localeKnown,records:total},human_reviewed:{numerator:0,denominator:total},publication_ready:{numerator:0,denominator:total}}};
}

/** Simulation only: return a new collection. No connections, writes or partial commits. */
export function simulate(source,previous=[]) {
  const first=plan(source), index=new Map(), latest=new Map();
  const stream=e=>canonical([e.native_id,e.locale]);
  for(const p of previous) {
    const e=p.entry;
    if(index.has(slot(e)) || e.published!==false || e.review!=="draft_unreviewed" ||
       nativeId(e.source_table,e.legacy_id)!==e.native_id ||
       (e.target_sha256===null?p.target!==null:digest(p.target)!==e.target_sha256)) throw Error("invalid_existing_ledger");
    index.set(slot(e),p);
    latest.set(stream(e),Math.max(latest.get(stream(e))??0,e.revision??0));
  }
  for(const p of first.packets) {
    const e=p.entry, old=index.get(slot(e));
    if(old) {
      if(canonical(e)!==canonical(old.entry)) throw Error("same_revision_conflict");
      index.set(slot(e),{...p,origin:"existing"});
    } else {
      if(e.revision!==null && e.revision<(latest.get(stream(e))??0)) throw Error("stale_revision");
      index.set(slot(e),p);
    }
  }
  return [...index.values()];
}
