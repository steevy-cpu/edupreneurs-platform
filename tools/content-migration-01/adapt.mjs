/** Adapt an allowlisted private export; never read a database or execute legacy modules. */
import {digest,nativeId} from "./migration.mjs";
import {fields} from "./convert.mjs";

function populated(v) {
  return v!==null && v!==undefined && v!=="" && !(Array.isArray(v) && v.length===0);
}
export function adaptLesson(row, subject, mapping = {}) {
  if (row.subject_id!==subject.id || row.grade_level!==subject.grade_level || ("subject_grade" in row && row.subject_grade!==subject.grade_level) || ("subject_series" in row && row.subject_series!==subject.series)) throw Error("legacy_hierarchy_conflict");
  const body=Object.fromEntries(fields.map(k=>[k,row[k]??null]));
  const fingerprint=digest({title:row.title,...body});
  // Language and unit assignments belong to the particular source version and an external register.
  const verified=Number.isSafeInteger(row.source_revision) && row.source_revision>0 && mapping.revision===row.source_revision && mapping.source_content_sha256===fingerprint && populated(mapping.decision_ref);
  const statusFields=["has_source_reviewer","scheduled_publish_at","quiz_count","activities_count","needs_quiz_regeneration","needs_activities_regeneration","last_content_validated_at","last_activities_validated_at","validation_fingerprint"];
  const supplemental={};
  const basic=new Set(["id","title","subject_id","grade_level","workflow_status","is_published","updated_at","source_revision","subject_grade","subject_series",...statusFields,...fields]);
  for(const [k,v] of Object.entries(row)) if(!basic.has(k)&&populated(v)) supplemental[k]=v;
  return {table:"lessons",id:row.id,title:row.title,subject_id:nativeId('subjects',subject.id),grade:row.grade_level,series:subject.series,
    locale:verified?mapping.locale:null,unit_id:verified?mapping.unit_id:null,revision:row.source_revision??null,...body,
    workflow_status:row.workflow_status,source_ref:"public.lessons/"+row.id,rights_ref:verified?mapping.rights_ref??null:null,
    assets:verified?mapping.assets??[]:[],legacy_metadata:{source_updated_at:row.updated_at??null,source_published:row.is_published??null,
      order_index:row.order_index??null,slug:row.slug??null,...Object.fromEntries(statusFields.map(k=>[k,row[k]??null]))},
    // Non-empty legacy fields beyond the adapter need an explicit mapping before a complete lesson is produced.
    supplemental_sha256:Object.fromEntries(Object.entries(supplemental).filter(([k])=>!["order_index","slug"].includes(k)).map(([k,v])=>[k,digest(v)]))};
}
export function adaptPaper(row, subjectCrosswalk, assets=[]) {
  return {table:"official_exams",id:row.id,title:row.title,grade:row.grade_level,series:row.series,
    track:row.track,year:row.year,exam_type:row.exam_type,revision:row.version_number,session:row.session,source_ref:"public.official_exams/"+row.id,
    subject_id:subjectCrosswalk?.[JSON.stringify([row.grade_level,row.series,row.subject_slug])]??null,
    pdf_ref:row.pdf_url,duration_minutes:row.duration_minutes,locale:null,assets,
    legacy_metadata:{version:row.version,subject:row.subject,subject_slug:row.subject_slug,total_points:row.total_points,
      total_exercises:row.total_exercises,is_model_exam:row.is_model_exam,reference_texts_digest:row.reference_texts_sha256??null}};
}
export function adaptExercise(row, paper) {
  if(row.exam_id!==paper.id) throw Error("orphan_exercise");
  return {table:"exam_exercises",id:row.id,parent_id:nativeId("official_exams",row.exam_id),grade:paper.grade,series:paper.series,subject_id:paper.subject_id,
    revision:paper.revision,locale:null,position:row.exercise_number,points:row.points,exercise_type:row.exercise_type,
    has_prompt:row.has_prompt,has_answer:row.has_answer,has_explanation:row.has_explanation,
    source_ref:"public.exam_exercises/"+row.id,
    legacy_metadata:{private_content_fingerprint:row.private_content_fingerprint,source_version:paper.revision}};
}
