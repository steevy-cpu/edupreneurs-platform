import {readFileSync} from "node:fs";
import {plan,reconcile,simulate,compareCensus} from "./migration.mjs";
import {examDescriptor} from "./exam.mjs";
import {lesson} from "./convert.mjs";

const [command,input,observation,register]=process.argv.slice(2);
const read=path=>JSON.parse(readFileSync(path,"utf8"));
try {
  if (!input || !["plan","reconcile","simulate","review","census"].includes(command)) throw Error("usage: node cli.mjs plan|simulate INPUT or reconcile INPUT OBSERVED [EXCLUSIONS]");
  const source=read(input);
  let output;
  if(command==="census") {
    output={report:compareCensus(read(observation),source.records)};
  } else if(command==="reconcile") {
    const comparison=reconcile(source,read(observation),register?read(register):[]);
    output={report:comparison};
  } else {
    const p=plan(source);
    const packets=command==="simulate"?simulate(source,observation?read(observation):[]):p.packets;
    const review=command==="review"?{exam_descriptors:source.records.filter(s=>["official_exams","exam_exercises"].includes(s.table)).map(s=>({id:s.id,subject_id:s.subject_id,parent_id:s.parent_id??null,source_ref:s.source_ref,legacy_metadata:s.legacy_metadata,...examDescriptor(s.table,s)})),
      review_sections:source.records.filter(s=>s.table==="lessons").map(s=>({legacy_id:s.id,revision:s.revision,locale:s.locale,sections:lesson(s).sections}))}:{};
    output={...review,manifest:{schema_version:1,snapshot:p.snapshot,transform:p.transform,entries:packets.map(p=>p.entry)},report:reconcile(source,packets),packets};
  }
  process.stdout.write(JSON.stringify(output)+"\n");
  if(output.report.results.some(r=>["changed","missing","unexpected","quarantined"].includes(r.status))) process.exitCode=2;
} catch(e) {
  // JSON syntax errors can contain input text. Logs must not echo private source.
  const reason=e instanceof SyntaxError?"invalid_json":/^[a-z_]+$/.test(e.message)?e.message:"invalid_input_or_io";
  console.log(JSON.stringify({report:{fatal:reason}}));
  process.exitCode=1;
}
