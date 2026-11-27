/** Private draft descriptors only. No key or explanation value belongs on this surface. */
export function examDescriptor(table, s) {
  if (table==="official_exams") {
    const reasons=[];
    if (!["9AF","NS4"].includes(s.grade) || s.track!==s.grade) reasons.push("exam_track");
    if (!s.subject_id || !s.pdf_ref) reasons.push("unresolved_paper_reference");
    if (!Number.isInteger(s.year) || s.year<1990 || s.year>2100) reasons.push("exam_year");
    if (!Number.isInteger(s.duration_minutes) || s.duration_minutes<5 || s.duration_minutes>300) reasons.push("unusable_duration");
    if (!["official","model","practice","rattrapage"].includes(s.exam_type)) reasons.push("exam_type_unmapped");
    return {descriptor:{track:s.track,series:s.series,year:s.year,pdf_ref:s.pdf_ref,source_version:s.revision,
      exam_type:s.exam_type,duration_minutes:s.duration_minutes,session:s.session??null},issues:reasons};
  }
  const reasons=[];
  if (!Number.isInteger(s.position) || s.position<1) reasons.push("exercise_position");
  if (!Number.isInteger(s.points) || s.points<0 || s.points>100) reasons.push("source_points_invalid");
  let mode;
  if (!s.has_prompt) mode="pdf_only_or_insufficient";
  else if (["open_ended","open-ended"].includes(s.exercise_type)) mode="human_marked_or_self_review";
  else if (s.exercise_type==="multiple_choice") {
    // A source answer and options are necessary but cannot authorize automatic grading.
    mode="quarantined";
    reasons.push(s.has_answer?"independent_key_verification_required":"missing_answer");
  } else { mode="quarantined"; reasons.push("unmapped_exercise_type"); }
  if(reasons.length) mode="quarantined";
  return {descriptor:{mode,position:s.position,source_points:s.points,exercise_type:s.exercise_type,
    source_has_answer:s.has_answer===true,source_has_explanation:s.has_explanation===true,
    auto_gradable:false},issues:reasons};
}
