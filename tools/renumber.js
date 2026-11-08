// 번호 목록 자동 정렬: 번호 항목을 지우거나 끼워 넣으면, 같은 목록(같은 들여쓰기)의 번호를 첫 번호부터 1씩 이어서 다시 매긴다.
// 내 편집(입력·삭제·붙여넣기)에만 반응한다: 다른 사람의 편집은 userEvent가 없어 건드리지 않는다(서로 번호를 고쳐 대는 일 방지).
// 같은 트랜잭션에 이어 붙이므로 되돌리기(Ctrl+Z) 한 번에 지운 것과 번호 정렬이 함께 돌아간다.
import { EditorState, RangeSetBuilder } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin } from "@codemirror/view";
import { inCode } from "./format.js";

const ITEM = /^( *)(\d+)([.)])(?: |$)/; // 번호 항목 줄(번호 뒤에 공백)
const LIMIT = 5000; // 한 방향으로 훑는 최대 줄 수

// n번째 줄이 번호 항목이면 그 목록의 항목 줄 번호들(위에서 아래 순서). 목록: 같은 들여쓰기의 번호 항목이 이어진 것.
// 더 깊이 들여쓴 줄(하위 목록·이어지는 글)과 빈 줄은 건너뛴다. 덜 들여쓴 줄을 만나면 끝난다.
// 같은 단계의 번호 없는 줄은, 빈 줄 없이 이어졌으면 항목의 이어지는 글(마크다운의 lazy continuation)이라 목록이 계속된다 —
// 가운데 항목의 번호만 지워도 뒤 번호가 이어지는 까닭. 빈 줄 뒤의 글이나 제목·인용·코드·글머리는 목록을 끝낸다.
const BLOCK = /^ *(?:#{1,6} |>|```|~~~|[-*+] |-{3,}\s*$|\*{3,}\s*$)/;
function group(state, n) {
  const doc = state.doc, first = ITEM.exec(doc.line(n).text);
  if (!first || inCode(state, doc.line(n).from)) return [];
  const depth = first[1].length;
  const scan = (step) => {
    const out = [];
    let blank = false; // 마지막 항목 뒤에 빈 줄이 있었나
    for (let i = n + step, c = 0; i >= 1 && i <= doc.lines && c < LIMIT; i += step, c++) {
      const t = doc.line(i).text;
      if (!t.trim()) { blank = true; continue; }
      const ind = t.length - t.trimStart().length;
      if (ind > depth) continue;
      if (ind < depth || inCode(state, doc.line(i).from)) break;
      if (ITEM.test(t)) { out.push(i); blank = false; continue; }
      if (blank || BLOCK.test(t)) break; // 같은 단계의 다른 글
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

// 번호 잠금: 번호 항목의 번호("3. ")는 직접 고칠 수 없다(자동으로 매겨지므로). 지우려면 번호 전체를 한 번에 지운다(Backspace·줄 지우기).
// 다른 번호로 시작하려면 새로 "5. "를 쳐서 시작하면 된다(첫 번호가 시작 번호가 되어 이어 매겨진다).
// 내 입력·삭제에만 적용한다(다른 사람의 편집·되돌리기는 userEvent가 없어 그대로 통과). Tab·Shift+Tab 명령은 번호를 직접 바꾸므로 통과.
// 한 곳만 바뀌는 편집(사람이 치고 지우는 보통의 입력)만 막는다: Enter 이어 쓰기처럼 새 항목을 넣으면서 뒤 번호까지 함께 바꾸는 명령은 여러 곳이 바뀌므로 통과.
const MARKER = /^( *)(\d+[.)]) /;
const markerRange = (line) => { const m = MARKER.exec(line.text); if (!m) return null; const from = line.from + m[1].length; return [from, from + m[2].length + 1]; };

export const lockNumbers = EditorState.changeFilter.of((tr) => {
  if (!(tr.isUserEvent("input") || tr.isUserEvent("delete")) || tr.isUserEvent("input.indent") || tr.isUserEvent("delete.dedent")) return true;
  const state = tr.startState, doc = state.doc;
  let ranges = 0;
  tr.changes.iterChangedRanges(() => ranges++);
  if (ranges !== 1) return true;
  let ok = true;
  tr.changes.iterChanges((fromA, toA, _fromB, _toB, inserted) => {
    for (let n = doc.lineAt(fromA).number, end = doc.lineAt(toA).number; n <= end && ok; n++) {
      const line = doc.line(n), r = markerRange(line);
      if (!r || inCode(state, line.from)) continue;
      const [ms, me] = r;
      const hits = fromA === toA ? fromA > ms && fromA < me : fromA < me && toA > ms; // 번호 안쪽에 끼워 넣거나 일부를 바꾸는 편집(맞닿는 것은 제외)
      if (hits && !(fromA <= ms && toA >= me)) ok = false; // 번호 전체를 지우거나 덮는 것은 허용
      if (fromA === toA && fromA === ms && /\d$/.test(inserted.toString())) ok = false; // 번호 바로 앞에 숫자를 쳐 붙여 번호를 바꾸는 것(2. -> 72.)
    }
  });
  return ok;
});

// 번호는 커서가 한 덩어리로 건너뛰고(방향키·클릭), 흐린 색으로 보인다
const numMark = Decoration.mark({ class: "cm-num" });
function numberDecos(view) {
  const b = new RangeSetBuilder();
  let last = -1;
  for (const { from, to } of view.visibleRanges) {
    for (let pos = Math.max(from, last + 1); pos <= to;) {
      const line = view.state.doc.lineAt(pos), r = markerRange(line);
      if (r && !inCode(view.state, line.from)) b.add(r[0], r[1], numMark);
      last = line.to;
      pos = line.to + 1;
    }
  }
  return b.finish();
}
export const numberMarkers = ViewPlugin.fromClass(class {
  constructor(view) { this.decorations = numberDecos(view); }
  update(u) { if (u.docChanged || u.viewportChanged) this.decorations = numberDecos(u.view); }
}, {
  decorations: (p) => p.decorations,
  provide: (p) => EditorView.atomicRanges.of((v) => v.plugin(p)?.decorations || Decoration.none),
});
