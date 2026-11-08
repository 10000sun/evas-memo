// 번호 목록 자동 정렬: 번호 항목을 지우거나 끼워 넣으면, 같은 목록(같은 들여쓰기)의 번호를 첫 번호부터 1씩 이어서 다시 매긴다.
// 내 편집(입력·삭제·붙여넣기)에만 반응한다: 다른 사람의 편집은 userEvent가 없어 건드리지 않는다(서로 번호를 고쳐 대는 일 방지).
// 같은 트랜잭션에 이어 붙이므로 되돌리기(Ctrl+Z) 한 번에 지운 것과 번호 정렬이 함께 돌아간다.
import { EditorState } from "@codemirror/state";
import { inCode } from "./format.js";

const ITEM = /^( *)(\d+)([.)])(?: |$)/; // 번호 항목 줄(번호 뒤에 공백)
const LIMIT = 5000; // 한 방향으로 훑는 최대 줄 수

// n번째 줄이 번호 항목이면 그 목록의 항목 줄 번호들(위에서 아래 순서). 목록: 같은 들여쓰기의 번호 항목이 이어진 것.
// 더 깊이 들여쓴 줄(하위 목록·이어지는 글)과 빈 줄은 건너뛰고, 덜 들여쓴 줄이나 같은 단계의 다른 글(글머리·본문)을 만나면 끝난다.
function group(state, n) {
  const doc = state.doc, first = ITEM.exec(doc.line(n).text);
  if (!first || inCode(state, doc.line(n).from)) return [];
  const depth = first[1].length;
  const scan = (step) => {
    const out = [];
    for (let i = n + step, c = 0; i >= 1 && i <= doc.lines && c < LIMIT; i += step, c++) {
      const t = doc.line(i).text;
      if (!t.trim()) continue;
      const ind = t.length - t.trimStart().length;
      if (ind > depth) continue;
      if (ind < depth || !ITEM.test(t) || inCode(state, doc.line(i).from)) break;
      out.push(i);
    }
    return out;
  };
  return [...scan(-1).reverse(), n, ...scan(1)];
}

// 이 상태에서 고쳐야 할 번호들의 changes. lineNos: 살펴볼 줄 번호(편집한 줄과 그 위·아래).
// startOf(items): 목록이 몇 번부터 시작해야 하는지(기본: 첫 항목의 지금 번호)
export function renumberChanges(state, lineNos, startOf = (items) => +ITEM.exec(state.doc.line(items[0]).text)[2]) {
  const doc = state.doc, changes = [], seen = new Set();
  for (const n of [...lineNos].sort((a, b) => a - b)) {
    if (seen.has(n)) continue;
    const items = group(state, n);
    items.forEach((i) => seen.add(i));
    if (items.length < 2) continue;
    const start = startOf(items);
    items.forEach((i, k) => {
      const line = doc.line(i), m = ITEM.exec(line.text);
      if (+m[2] !== start + k) changes.push({ from: line.from + m[1].length, to: line.from + m[1].length + m[2].length, insert: String(start + k) });
    });
  }
  return changes.sort((a, b) => a.from - b.from);
}

export const renumber = EditorState.transactionFilter.of((tr) => {
  if (!tr.docChanged || !(tr.isUserEvent("input") || tr.isUserEvent("delete"))) return tr;
  const doc = tr.newDoc, lines = new Set();
  tr.changes.iterChangedRanges((_fa, _ta, fromB, toB) => {
    const a = doc.lineAt(fromB).number, b = doc.lineAt(toB).number;
    for (let n = Math.max(1, a - 1); n <= Math.min(doc.lines, b + 1); n++) lines.add(n); // 지운 줄의 위·아래 항목까지 본다
  });
  // 첫 항목 번호를 내가 직접 고쳤으면 그 번호부터, 아니면(앞 항목을 지운 경우 등) 편집 전 목록의 시작 번호를 지킨다: 1번을 지우면 2번이 1번이 된다
  const inv = tr.changes.invert(tr.startState.doc), startOf = (items) => {
    const m = ITEM.exec(doc.line(items[0]).text), from = doc.line(items[0]).from + m[1].length, to = from + m[2].length;
    let touched = false;
    tr.changes.iterChangedRanges((_fa, _ta, fromB, toB) => { if (fromB < to && toB > from) touched = true; });
    if (touched) return +m[2];
    const old = tr.startState, og = group(old, old.doc.lineAt(inv.mapPos(from, 1)).number);
    return og.length ? +ITEM.exec(old.doc.line(og[0]).text)[2] : +m[2];
  };
  const changes = renumberChanges(tr.state, lines, startOf);
  return changes.length ? [tr, { changes, sequential: true }] : tr;
});
