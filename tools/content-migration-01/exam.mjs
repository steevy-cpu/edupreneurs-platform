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

/** Compare a sealed grading proposal with a separately authenticated decision register.
 * The caller authenticates the register outside this offline comparison. Never return a key.
 * This diagnostic does not activate grading or change an import decision. */
export function compareSealedKey(proposal, register) {
  const blocked = reason => ({mode:"quarantined",reason});
  if (!register?.owner_accepted || register.owner_accepted!==true ||
      !register.review_ref || !register.independent_reviewer || !proposal?.item_id ||
      !Number.isSafeInteger(proposal.revision) || proposal.revision<1 ||
      !/^[0-9a-f]{64}$/.test(proposal.content_sha256??"") ||
      register.item_id!==proposal.item_id || register.revision!==proposal.revision ||
      register.content_sha256!==proposal.content_sha256) return blocked("missing_independent_key_receipt");
  const choices=proposal.choice_ids;
  if (!Array.isArray(choices) || choices.length<2 || new Set(choices).size!==choices.length ||
      !choices.every(x=>typeof x==="string" && x.trim()) || !choices.includes(proposal.correct_choice_id) ||
      proposal.correct_choice_id!==register.correct_choice_id) return blocked("key_mismatch");
  return {mode:"verified_auto_gradable",review_ref:register.review_ref};
}
