import {readFileSync} from "node:fs";
import {plan,reconcile,simulate} from "./migration.mjs";

const [command,input,observation,register]=process.argv.slice(2);
const read=path=>JSON.parse(readFileSync(path,"utf8"));
try {
  if (!input || !["plan","reconcile","simulate"].includes(command)) throw Error("usage: node cli.mjs plan|simulate INPUT or reconcile INPUT OBSERVED [EXCLUSIONS]");
  const source=read(input);
  const p=plan(source);
  let output;
  if(command==="reconcile") {
    const comparison=reconcile(source,read(observation),register?read(register):[]);
    output={report:comparison};
  } else {
    const packets=command==="simulate"?simulate(source,observation?read(observation):[]):p.packets;
    output={manifest:{schema_version:1,snapshot:p.snapshot,transform:p.transform,entries:packets.map(p=>p.entry)},report:reconcile(source,packets),packets};
  }
  process.stdout.write(JSON.stringify(output)+"\n");
  if(output.report.results.some(r=>["changed","missing","unexpected","quarantined"].includes(r.status))) process.exitCode=2;
} catch(e) {
  // JSON syntax errors can contain input text. Logs must not echo private source.
  const reason=e instanceof SyntaxError?"invalid_json":/^[a-z_]+$/.test(e.message)?e.message:"invalid_input_or_io";
  console.log(JSON.stringify({report:{fatal:reason}}));
  process.exitCode=1;
}
