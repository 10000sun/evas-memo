// node tools/test-renumber.mjs — 번호 목록 자동 정렬(renumber.js)을 확인한다. 실패하면 종료 코드 1
import assert from "node:assert/strict";
import { EditorState } from "@codemirror/state";
import { markdown, markdownLanguage, deleteMarkupBackward, insertNewlineContinueMarkup } from "@codemirror/lang-markdown";
import { renumber, lockNumbers } from "./renumber.js";

const run = (doc, changes, userEvent, selection) => {
  const st = EditorState.create({ doc, selection, extensions: [markdown({ base: markdownLanguage }), renumber] });
  return st.update({ changes, userEvent }).state;
};
// doc 안의 글을 찾아 지운다(뒤 줄바꿈 하나까지). 줄 전체를 지우는 보통의 삭제
const del = (doc, text) => { const i = doc.indexOf(text); return run(doc, { from: i, to: i + text.length + 1, insert: "" }, "delete").doc.toString(); };
const ins = (doc, at, text) => run(doc, { from: doc.indexOf(at), insert: text }, "input").doc.toString();

// 가운데 항목을 지우면 뒤 번호가 당겨진다
assert.equal(del("1. a\n2. b\n3. c\n4. d", "2. b"), "1. a\n2. c\n3. d");
// 첫 항목을 지우면 다음 항목이 1번이 된다(목록은 1부터)
assert.equal(del("1. a\n2. b\n3. c", "1. a"), "1. b\n2. c");
// 마지막 항목을 지워도 앞은 그대로
assert.equal(del("1. a\n2. b\n3. c\n", "3. c"), "1. a\n2. b\n");
// 처음부터 5번인 목록은 그 시작을 지킨다
assert.equal(del("5. a\n6. b\n7. c", "5. a"), "5. b\n6. c");
assert.equal(del("5. a\n6. b\n7. c", "6. b"), "5. a\n6. c");
// 가운데에 새 항목을 끼우면 뒤 번호가 밀린다(Enter로 이어 쓴 번호는 +1이라 뒤와 겹친다)
assert.equal(ins("1. a\n2. b\n3. c", "2. b", "2. new\n"), "1. a\n2. new\n3. b\n4. c");
// 번호 뒤 구분자 ')' 도 같다
assert.equal(del("1) a\n2) b\n3) c", "2) b"), "1) a\n2) c");
// 두 자리 수로 넘어가거나 내려와도
const long = Array.from({ length: 12 }, (_, i) => `${i + 1}. x${i + 1}`).join("\n");
assert.equal(del(long, "3. x3"), Array.from({ length: 11 }, (_, i) => `${i + 1}. x${i < 2 ? i + 1 : i + 2}`).join("\n"));
// 하위 목록은 따로 센다: 하위 항목을 지우면 하위만, 상위 항목을 지우면 상위만(하위 번호는 그대로)
assert.equal(del("1. a\n    1. x\n    2. y\n    3. z\n2. b", "    2. y"), "1. a\n    1. x\n    2. z\n2. b");
assert.equal(del("1. a\n    1. x\n2. b\n3. c", "2. b"), "1. a\n    1. x\n2. c");
// 빈 줄로 띄운 목록도 한 목록이다. 다른 글(본문)이 끼면 거기서 끝난다
assert.equal(del("1. a\n\n2. b\n\n3. c", "2. b"), "1. a\n\n\n2. c");
assert.equal(del("1. a\n2. b\n\n본문\n\n1. p\n2. q\n3. r", "2. q"), "1. a\n2. b\n\n본문\n\n1. p\n2. r");
assert.equal(del("1. a\n2. b\n3. c\n\n- 글머리\n\n1. p\n3. q", "2. b"), "1. a\n2. c\n\n- 글머리\n\n1. p\n3. q", "다른 목록은 건드리지 않는다");
// 번호를 내가 직접 고치면(첫 항목) 그 번호부터 이어진다
assert.equal(run("1. a\n2. b\n3. c", { from: 0, to: 1, insert: "4" }, "input").doc.toString(), "4. a\n5. b\n6. c");
// 코드 블록 안은 건드리지 않는다
const code = "```\n1. a\n3. b\n```";
assert.equal(run(code, { from: code.indexOf("a"), to: code.indexOf("a") + 1, insert: "aa" }, "input").doc.toString(), "```\n1. aa\n3. b\n```");
// 다른 사람의 편집(userEvent 없음)에는 반응하지 않는다
{
  const doc = "1. a\n2. b\n3. c", i = doc.indexOf("2. b");
  assert.equal(run(doc, { from: i, to: i + 5, insert: "" }, undefined).doc.toString(), "1. a\n3. c");
}
// 이미 맞으면 아무것도 바꾸지 않는다(한 글자 입력)
assert.equal(ins("1. a\n2. b", "b", "x"), "1. a\n2. xb");
// 커서는 자기 글을 따라간다: 9번 줄을 지워 10번이 9번이 될 때 뒤 항목 끝에 있던 커서가 유지된다
{
  const doc = Array.from({ length: 11 }, (_, i) => `${i + 1}. x`).join("\n"), end = doc.length;
  const i = doc.indexOf("9. x");
  const st = run(doc, { from: i, to: i + 5, insert: "" }, "delete", { anchor: end });
  assert.equal(st.doc.toString().split("\n").at(-1), "10. x");
  assert.equal(st.selection.main.head, st.doc.length);
}
// 되돌리기용: 지운 것과 번호 정렬이 한 트랜잭션이다
{
  const doc = "1. a\n2. b\n3. c", i = doc.indexOf("2. b");
  const st = EditorState.create({ doc, extensions: [renumber] });
  const tr = st.update({ changes: { from: i, to: i + 5, insert: "" }, userEvent: "delete" });
  assert.equal(tr.state.doc.toString(), "1. a\n2. c");
  assert.equal(tr.changes.invert(st.doc).apply(tr.newDoc).toString(), doc);
}

// --- 번호 잠금(lockNumbers): 번호는 직접 고칠 수 없고, 지우려면 번호 전체를 한 번에 지운다 ---
const locked = (doc, selection) => EditorState.create({ doc, selection, extensions: [markdown({ base: markdownLanguage }), renumber, lockNumbers] });
const lk = (doc, changes, userEvent = "input") => locked(doc).update({ changes, userEvent }).state.doc.toString();
const D = "1. a\n2. b\n3. c"; // 0-3 "1. a", 4 \n, 5 "2", 6 ".", 7 " ", 8 "b"
assert.equal(lk(D, { from: 6, insert: "9" }), D, "번호 안쪽에 끼워 넣기는 막힌다");
assert.equal(lk(D, { from: 5, to: 6, insert: "9" }), D, "숫자를 바꾸는 입력은 막힌다");
assert.equal(lk(D, { from: 5, to: 6 }, "delete"), D, "숫자 하나만 지우기는 막힌다");
assert.equal(lk(D, { from: 6, to: 7 }, "delete"), D, "마침표만 지우기는 막힌다");
assert.equal(lk(D, { from: 7, to: 8 }, "delete"), D, "번호 뒤 공백만 지우기도 막힌다");
assert.equal(lk(D, { from: 0, to: 1, insert: "7" }), D, "첫 항목의 번호도 직접 못 고친다");
assert.equal(lk(D, { from: 8, insert: "x" }), "1. a\n2. xb\n3. c", "항목 글(번호 뒤)은 그대로 고칠 수 있다");
assert.equal(lk(D, { from: 5, insert: "7" }), D, "번호 바로 앞에 숫자를 붙여 번호를 바꾸는 것도 막힌다(2. -> 72.)");
assert.equal(lk(D, { from: 5, insert: "새 " }), "1. a\n새 2. b\n2. c", "번호 앞에 끼워 넣는 것은 허용(그 줄은 번호 항목이 아니게 되므로 뒤 번호가 이어진다)");
assert.equal(lk(D, { from: 5, to: 8 }, "delete"), "1. a\nb\n2. c", "번호 전체를 지우면 허용되고, 뒤 번호는 이어진다(b는 앞 항목의 이어지는 글)");
assert.equal(lk(D, { from: 4, to: 9 }, "delete"), "1. a\n2. c", "줄 전체를 지우는 것도 허용(번호 포함)");
assert.equal(lk(D, { from: 4, to: 12 }, "delete"), D, "다음 줄 번호를 일부만 덮는 삭제는 막힌다");
// 시작 번호: 새로 "5. "를 쳐서 시작하면 그 번호부터 이어진다(번호를 쳐 넣는 입력은 기존 번호를 건드리는 게 아니다)
{
  let st = locked("");
  for (const [ch, i] of [["5", 0], [".", 1], [" ", 2], ["a", 3]]) st = st.update({ changes: { from: i, insert: ch }, userEvent: "input.type" }).state;
  assert.equal(st.doc.toString(), "5. a");
  st = st.update({ changes: { from: 4, insert: "\n6. b\n7. c" }, userEvent: "input" }).state; // 이어 쓰기(Enter가 번호를 +1로 넣은 것)
  assert.equal(st.doc.toString(), "5. a\n6. b\n7. c");
  st = st.update({ changes: { from: 5, to: 8 }, userEvent: "delete" }).state; // 가운데 번호를 지워도 시작 번호(5)는 유지된다
  assert.equal(st.doc.toString(), "5. a\nb\n6. c");
}
// 이어 붙인 번호는 다른 번호를 쳐도 순서대로 바로잡힌다
assert.equal(lk("1. a\n2. b", { from: 9, insert: "\n9. c" }), "1. a\n2. b\n3. c");
// 다른 사람의 편집(userEvent 없음)과 되돌리기는 막지 않는다
assert.equal(locked(D).update({ changes: { from: 5, to: 6, insert: "9" } }).state.doc.toString(), "1. a\n9. b\n3. c");
// Tab·Shift+Tab(들여쓰기 명령)은 번호를 직접 바꾸므로 통과
assert.equal(lk(D, { from: 5, to: 7, insert: "    1." }, "delete.dedent").includes("    1."), true);
// 코드 블록 안의 "3. x"는 번호가 아니다
const fence = "```\n3. x\n```";
assert.equal(lk(fence, { from: 4, to: 5, insert: "9" }), "```\n9. x\n```");
// markdown의 Backspace(번호 바로 뒤에서)는 번호 전체를 지우므로 통과한다
{
  const st = EditorState.create({ doc: D, selection: { anchor: 8 }, extensions: [markdown({ base: markdownLanguage }), renumber, lockNumbers] });
  let out = st;
  deleteMarkupBackward({ state: st, dispatch: (tr) => { out = tr.state; } });
  assert.equal(out.doc.toString().startsWith("1. a\n"), true);
  assert.notEqual(out.doc.toString(), D, "번호가 지워졌다(막히지 않았다)");
  assert.equal(out.doc.toString().split("\n")[1].includes("2."), false);
}
// markdown의 Enter(이어 쓰기)로 만든 새 항목도 막히지 않는다
{
  const st = EditorState.create({ doc: "1. a\n2. b", selection: { anchor: 4 }, extensions: [markdown({ base: markdownLanguage }), renumber, lockNumbers] });
  let out = st;
  insertNewlineContinueMarkup({ state: st, dispatch: (tr) => { out = tr.state; } });
  assert.equal(out.doc.toString(), "1. a\n2. \n3. b");
}
console.log("renumber: ok");
