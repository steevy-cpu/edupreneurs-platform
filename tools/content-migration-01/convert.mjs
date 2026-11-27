/** Strict parser for a deliberately small HTML subset. Never creates a DOM or fetches a URL. */
export const fields = ["objectif", "introduction", "contenu", "exemples_exercices", "activites_interactives", "quiz_final"];
const limits = { field: 200000, nodes: 12000, depth: 48 };
const voids = new Set(["br", "img", "hr", "input", "meta", "link", "source", "area", "wbr"]);
function fail(reason) { throw new Error(reason); }

function decode(text) {
  const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: "\u00a0", eacute: "é", egrave: "è", agrave: "à", times: "×", divide: "÷", minus: "−" };
  return text.replace(/&(#x[\da-f]+|#\d+|[a-z][a-z0-9]*);/gi, (_, key) => {
    if (Object.hasOwn(named, key)) return named[key];
    if (key[0] !== "#") fail("unsupported_entity");
    const n = key[1].toLowerCase() === "x" ? parseInt(key.slice(2), 16) : Number(key.slice(1));
    if (!Number.isSafeInteger(n) || n < 32 || n > 0x10ffff || (n >= 0xd800 && n <= 0xdfff)) fail("invalid_character");
    return String.fromCodePoint(n);
  });
}

export function parse(html) {
  if (typeof html !== "string" || html.length > limits.field) fail("invalid_field_or_size");
  const root = { tag: "root", attrs: {}, children: [] };
  const stack = [root];
  const token = /<\/?([A-Za-z][A-Za-z0-9-]*)\b((?:[^"'<>]|"[^"]*"|'[^']*')*)>|[^<]+/gy;
  const attribute = /\s+([a-zA-Z_:][\w:.-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>\x60]+))/gy;
  let index = 0, nodes = 0;
  while (index < html.length) {
    token.lastIndex = index;
    const m = token.exec(html);
    if (!m || ++nodes > limits.nodes || stack.length > limits.depth) fail("unsupported_markup_or_limit");
    index = token.lastIndex;
    const parent = stack.at(-1);
    if (!m[1]) { parent.children.push(decode(m[0])); continue; }
    const tag = m[1].toLowerCase();
    if (m[0].startsWith("</")) {
      if (stack.length === 1 || parent.tag !== tag || m[2].trim()) fail("unbalanced_markup");
      stack.pop();
      continue;
    }
    let rest = m[2].trimEnd();
    if (rest.endsWith("/") && voids.has(tag)) rest = rest.slice(0, -1).trimEnd();
    let pos = 0;
    const attrs = Object.create(null);
    while (pos < rest.length) {
      attribute.lastIndex = pos;
      const a = attribute.exec(rest);
      if (!a) fail("unsupported_attribute_syntax");
      const name = a[1].toLowerCase();
      if (Object.hasOwn(attrs, name)) fail("duplicate_attribute");
      attrs[name] = decode(a[2] ?? a[3] ?? a[4]);
      pos = attribute.lastIndex;
    }
    const node = { tag, attrs, children: [] };
    parent.children.push(node);
    if (!voids.has(tag)) stack.push(node);
  }
  if (stack.length !== 1) fail("unclosed_markup");
  return root;
}

function plain(s) {
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u200b-\u200f\u202a-\u202e\ufeff]/u.test(s)) fail("unsafe_text");
  return s.replace(/[ \t\r\n]+/g, " ").trim();
}

// Accept only a complete small equality. Everything else math-like needs review.
function math(s) {
  if (!/[=<>≤≥≠≈＝]/u.test(s)) return;
  const m = /^(-?\d{1,12})\s*([+−×÷])\s*(-?\d{1,12})\s*=\s*(-?\d{1,12})$/u.exec(s);
  if (!m) fail("math_needs_review");
  const a = BigInt(m[1]), b = BigInt(m[3]), c = BigInt(m[4]);
  const correct = { "+": a + b === c, "−": a - b === c, "×": a * b === c, "÷": b !== 0n && a === b * c }[m[2]];
  if (!correct) fail("false_math");
}

export function convertField(html) {
  const root = parse(html), blocks = [], structure = [], assets = [], issues = new Set();
  function visit(n, path, prefix="") {
    if (typeof n === "string") return n;
    const attrs = Object.keys(n.attrs);
    if (attrs.some(k => k !== "class" && !(n.tag === "img" && ["src", "alt"].includes(k)))) issues.add("unmapped_attributes");
    if (n.attrs.class && !/^(lesson-content|wiki-content|user-content)$/.test(n.attrs.class)) issues.add("unmapped_class");
    if (n.tag === "img") {
      assets.push({ reference: n.attrs.src ?? null, alt: n.attrs.alt ?? null, path });
      issues.add("image_requires_asset_capable_contract");
      return "";
    }
    if (["br","strong","em","b","i","span"].includes(n.tag)) {
      structure.push({path,tag:n.tag});
      return n.tag === "br" ? "\n" : n.children.map((c,i)=>visit(c,path+"."+i)).join("");
    }
    if (["root","div","ul","ol"].includes(n.tag)) {
      structure.push({path,tag:n.tag});
      let ordinal=0;
      for (const [i,c] of n.children.entries()) {
        if (typeof c === "string" && !c.trim()) continue;
        let marker="";
        if (n.tag==="ul" || n.tag==="ol") {
          if (c.tag!=="li") issues.add("invalid_list_child");
          marker=n.tag==="ol"?String(++ordinal)+". ":"• ";
        }
        const text = visit(c,path+"."+i,marker);
        if (text && plain(text)) emit("paragraph",text,path+"."+i);
      }
      return "";
    }
    if (/^h[1-6]$/.test(n.tag) || ["li","p"].includes(n.tag)) {
      structure.push({path,tag:n.tag});
      if (n.children.some(c=>typeof c !== "string" && !["br","strong","em","b","i","span","img"].includes(c.tag))) issues.add("nested_block");
      const s = n.children.map((c,i)=>visit(c,path+"."+i)).join("");
      if (plain(s)) emit(n.tag.startsWith("h")?"heading":"paragraph",prefix+s,path);
      return "";
    }
    issues.add("unsupported_element:"+n.tag);
    // No partial target can be accepted when an unsupported subtree is present.
    return "";
  }
  function emit(type,text,path) {
    const s = plain(text);
    if (!s) return;
    try { math(s); } catch(e) { issues.add(e.message); }
    if ([...s].length > (type==="heading"?200:4000)) issues.add("target_text_limit");
    structure.push({path,block:blocks.length});
    blocks.push({key:"b-"+(blocks.length+1),type,text:s});
  }
  visit(root,"0");
  if (structure.some(n=>["strong","em","b","i","br"].includes(n.tag))) issues.add("rich_semantics_require_review");
  return {blocks:issues.size?[]:blocks,structure,sourceTree:root,assets,issues:[...issues].sort()};
}

export function quizShape(html) {
  const root = parse(html);
  let candidates = 0, withChoices = 0;
  function walk(n) {
    if (typeof n === "string") return;
    if (n.tag === "div" && (n.attrs.class??"").split(/\s+/).includes("quiz-question")) {
      candidates++;
      const options = n.children.filter(x=>x?.attrs?.class==="quiz-options");
      if (options.length===1 && options[0].children.filter(x=>x?.attrs?.class==="option").length>=2) withChoices++;
    }
    n.children.forEach(walk);
  }
  walk(root);
  return {candidates,withChoices};
}


function children(node) { return node.children.filter(c => typeof c !== "string" || c.trim()); }
function requireTag(node, tag, attrs = []) {
  if (!node || node.tag !== tag || Object.keys(node.attrs).some(k => !attrs.includes(k))) fail("unmapped_quiz_markup");
}
function simpleText(node) {
  if (node.children.some(c => typeof c !== "string")) fail("rich_quiz_text_requires_review");
  const s = plain(node.children.join(""));
  if (!s) fail("empty_quiz_text");
  return s;
}
export function practiceQuestions(html) {
  const roots = children(parse(html));
  if (roots.length !== 1) fail("unmapped_quiz_wrapper");
  const wrapper = roots[0];
  requireTag(wrapper,"div",["class"]);
  if (wrapper.attrs.class !== "quiz-container") fail("unmapped_quiz_wrapper");
  const questions = [];
  for (const node of children(wrapper)) {
    requireTag(node,"div",["class","data-number"]);
    if (node.attrs.class !== "quiz-question" || node.attrs["data-number"] !== String(questions.length+1)) fail("quiz_item_order");
    const parts = children(node);
    if (parts.length !== 4) fail("unmapped_quiz_parts");
    const [heading,prompt,options,feedback] = parts;
    requireTag(heading,"h3"); requireTag(prompt,"p"); requireTag(options,"div",["class"]); requireTag(feedback,"div",["class","data-correct"]);
    if (options.attrs.class!=="quiz-options" || feedback.attrs.class!=="correct-answer") fail("unmapped_quiz_parts");
    const choices = children(options).map(option => {
      requireTag(option,"div",["class","data-answer"]);
      if (option.attrs.class !== "option") fail("invalid_choice");
      const id = option.attrs["data-answer"], text = simpleText(option);
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(id??"") || [...text].length>300) fail("invalid_choice");
      return {id,text};
    });
    const ids = new Set(choices.map(c=>c.id));
    const correct = feedback.attrs["data-correct"];
    if (ids.size!==choices.length || !ids.has(correct) || choices.length<2 || choices.length>6) fail("ambiguous_answer");
    const lines = children(feedback);
    if (lines.length!==2) fail("unmapped_feedback");
    lines.forEach(n=>requireTag(n,"p"));
    const keyLabel=children(lines[0]);
    if(keyLabel.length!==1) fail("unmapped_key_label");
    requireTag(keyLabel[0],"strong");
    const displayed=simpleText(keyLabel[0]).match(/^(?:bonne réponse|réponse correcte|réponse|repons ki kòrèk|repons)\s*:\s*([A-Za-z0-9_-]+)$/iu);
    if (!displayed || displayed[1]!==correct) fail("answer_label_mismatch");
    const text=simpleText(prompt), explanation=simpleText(lines[1]);
    if ([...text].length>1000 || [...explanation].length>2000) fail("target_question_limit");
    const label=simpleText(heading);
    // Heading is metadata in v1: only a redundant ordinal can be projected away.
    if (!new RegExp("^(?:Question|Kesyon)\\s+"+(questions.length+1)+"$","iu").test(label)) fail("nonordinal_question_heading");
    math(text); math(explanation);
    questions.push({prompt:{text},response_spec:{choices},answer_key:{correct_choice_id:correct},explanation:{text:explanation}});
  }
  if(!questions.length) fail("empty_quiz");
  return questions;
}

export function lesson(source) {
  const issues = new Set(), blocks = [], sections = {}, assets = [], questions = [];
  for (const field of fields) {
    const raw = source[field];
    if (raw===null || raw==="") continue;
    try {
      if (field==="quiz_final") {
        sections[field]=quizShape(raw);
        questions.push(...practiceQuestions(raw));
      } else {
        const part=convertField(raw);
        sections[field]={structure:part.structure,sourceTree:part.sourceTree,issues:part.issues};
        part.issues.forEach(s=>issues.add(field+":"+s));
        part.assets.forEach(a=>assets.push({...a,field}));
        if(field==="activites_interactives") issues.add("activity_semantics_unverified");
        for (const b of part.blocks) blocks.push({...b,key:field.replaceAll("_","-")+"-"+b.key});
      }
    } catch(e) { issues.add(field+":"+e.message); }
  }
  if (!["fr","ht"].includes(source.locale)) issues.add("locale_unverified");
  if (!blocks.length || blocks.length>200) issues.add("target_block_count");
  return {blocks:issues.size?[]:blocks,questions:issues.size?[]:questions,sections,assets,issues:[...issues].sort()};
}
