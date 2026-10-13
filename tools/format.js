// 서식 명령(굵게·기울임·…·서식 지우기). 툴바(app.js)·선택 위 버블·단축키가 모두 여기 정의를 쓴다.
// 문서 글자만 바꾸고(한 트랜잭션 = 되돌리기 한 번), 꾸밈은 라이브 표시(live-md.js)가 따라 그린다
import { EditorSelection, Prec, StateEffect, StateField } from "@codemirror/state";
import { EditorView, ViewPlugin, keymap, showTooltip } from "@codemirror/view";
import { syntaxTree } from "@codemirror/language";
import { completionStatus } from "@codemirror/autocomplete";
import { findUrls } from "./url-rule.mjs";
import { TEXT_COLORS, COLOR_NAMES, COLOR_OPEN, COLOR_OPEN_END, COLOR_WRAPPED } from "./text-colors.mjs";

// 코드 블록(펜스·들여쓰기 코드) 안인가. 목록 규칙(editor-entry.js)도 같이 쓴다
export function inCode(state, pos) {
  for (let n = syntaxTree(state).resolveInner(pos, -1); n; n = n.parent) if (n.name === "FencedCode" || n.name === "CodeBlock") return true;
  return false;
}

const MAC = /Mac|iPhone|iPad/.test((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "");
const keyText = (k) => k && k.split("-").map((p) => (p === "Mod" ? (MAC ? "⌘" : "Ctrl") : p === "Shift" ? (MAC ? "⇧" : "Shift") : p.toUpperCase())).join(MAC ? "" : "+");
const WRAPS = { bold: "**", italic: "*", underline: "__", strike: "~~", code: "`", spoiler: "||" };
const PREFIX = { quote: "> ", subtext: "-# ", list: "- " };
// 이름·라벨·글자 아이콘·단축키. bubble: 선택 위 버블에도 보일 것
const LIST = [
  ["bold", "굵게", "B", "Mod-b", 1], ["italic", "기울임", "I", "Mod-i", 1], ["underline", "밑줄", "U", "Mod-u", 1],
  ["strike", "취소선", "S", "Mod-Shift-x", 1], ["code", "코드", "<>", "Mod-e", 1], ["color", "글자 색", "A", "", 1],
  ["spoiler", "스포일러", "▒", "Mod-Shift-s", 1], ["heading", "제목", "H", ""], ["quote", "인용", "❝", ""],
  ["subtext", "작은 글씨", "-#", ""], ["list", "목록", "•", ""], ["link", "링크", "링크", "", 1], ["clear", "서식 지우기", "Tx", ""],
];
export const COMMANDS = LIST.map(([name, label, icon, key, bubble]) => ({
  name, label, icon, bubble: !!bubble, key: keyText(key) || "", cmKey: key || "", ...(name === "color" ? { colors: COLOR_NAMES.map((n) => ({ name: n, cls: "cm-tc-" + TEXT_COLORS[n] })) } : {}),
}));

// pos 앞(dir<0)·뒤(dir>0)로 같은 글자 ch가 몇 개 이어지는가(8개까지만 센다)
function run(doc, pos, ch, dir) {
  let n = 0;
  for (; n < 8; n++) {
    const p = dir < 0 ? pos - n - 1 : pos + n;
    if (p < 0 || p >= doc.length || doc.sliceString(p, p + 1) !== ch) break;
  }
  return n;
}
// 이어진 표시 글자 n개가 표시 m을 품는가. * 는 홀수(*, ***)일 때만 기울임(** 는 굵게)
const fits = (m, n) => (m === "*" ? n % 2 === 1 : n >= m.length);

// 한 줄 조각 [f,t]의 감싸기·풀기 변경
function wrapSeg(doc, f, t, m) {
  const ch = m[0], L = m.length;
  if (fits(m, run(doc, f, ch, -1)) && fits(m, run(doc, t, ch, 1))) return [{ from: f - L, to: f }, { from: t, to: t + L }]; // 바깥 표시 풀기
  if (t - f > 2 * L && fits(m, run(doc, f, ch, 1)) && fits(m, run(doc, t, ch, -1))) return [{ from: f, to: f + L }, { from: t - L, to: t }]; // 고른 글 안의 표시 풀기
  return [{ from: f, insert: m }, { from: t, insert: m }];
}
// 글자 색: 같은 색이면 풀고, 다른 색이면 이름만 바꾸고, 없으면 감싼다. name이 null이면 색 해제
function colorSeg(doc, f, t, name) {
  const before = COLOR_OPEN_END.exec(doc.sliceString(Math.max(0, f - 8), f));
  if (before && doc.sliceString(t, t + 1) === "}") {
    const o = f - before[0].length;
    return name && name !== before[1] ? [{ from: o, to: f, insert: `{${name}|` }] : [{ from: o, to: f }, { from: t, to: t + 1 }];
  }
  const inner = COLOR_WRAPPED.exec(doc.sliceString(f, t));
  if (inner && !inner[2].includes("}")) {
    const o = f + inner[0].length - inner[2].length - 1; // "{이름|" 끝
    return name && name !== inner[1] ? [{ from: f, to: o, insert: `{${name}|` }] : [{ from: f, to: o }, { from: t - 1, to: t }];
  }
  return name ? [{ from: f, insert: `{${name}|` }, { from: t, insert: "}" }] : [];
}
const COLOR_PAIR = new RegExp(`${COLOR_OPEN.source}([^{}]*)\\}`, "g");
const MARKERS = /\*+|__|~~|`+|\|\|/g;
function clearText(s) {
  for (let i = 0; i < 5; i++) { const n = s.replace(COLOR_PAIR, "$2"); if (n === s) break; s = n; }
  return s.replace(COLOR_OPEN, "").replace(MARKERS, "");
}

// 범위 r의 줄별 조각(앞뒤 공백 뺌, 빈 조각·코드 블록 줄은 건너뜀)
function segments(state, r) {
  const doc = state.doc, out = [];
  for (let n = doc.lineAt(r.from).number, end = doc.lineAt(r.to).number; n <= end; n++) {
    const l = doc.line(n), text = l.text;
    let f = Math.max(r.from, l.from), t = Math.min(r.to, l.to);
    while (f < t && /\s/.test(text[f - l.from])) f++;
    while (t > f && /\s/.test(text[t - 1 - l.from])) t--;
    if (t > f && !inCode(state, f)) out.push([f, t]);
  }
  return out;
}

// 인라인 명령(감싸기·색·서식 지우기·링크): 범위마다 따로 계산해 한 트랜잭션으로
function inline(state, name, arg) {
  const doc = state.doc;
  return state.changeByRange((r) => {
    if (r.empty) {
      const p = r.head;
      if (inCode(state, p)) return { range: r };
      if (name === "link") {
        const s = "[링크](", ins = s + "https://)";
        return { changes: { from: p, insert: ins }, range: EditorSelection.range(p + s.length, p + s.length + 8) };
      }
      if (name === "clear") return { range: r };
      const [o, c] = name === "color" ? (arg ? [`{${arg}|`, "}"] : ["", ""]) : [WRAPS[name], WRAPS[name]];
      if (!o) return { range: r };
      if (doc.sliceString(p - o.length, p) === o && doc.sliceString(p, p + c.length) === c) // 빈 표시 쌍 **|** 은 지운다
        return { changes: [{ from: p - o.length, to: p }, { from: p, to: p + c.length }], range: EditorSelection.cursor(p - o.length) };
      return { changes: { from: p, insert: o + c }, range: EditorSelection.cursor(p + o.length) };
    }
    if (name === "link") {
      if (doc.lineAt(r.from).number !== doc.lineAt(r.to).number || inCode(state, r.from)) return { range: r };
      const text = doc.sliceString(r.from, r.to), u = [...findUrls(text)][0];
      if (u && u.from === 0 && u.to === text.length) // 주소를 골랐으면 [](주소) 로 만들고 글 자리에 커서
        return { changes: { from: r.from, to: r.to, insert: `[](${text})` }, range: EditorSelection.cursor(r.from + 1) };
      const at = r.from + 1 + text.length + 2; // "[글](" 뒤: 주소 자리를 골라 바로 붙여 넣게
      return { changes: { from: r.from, to: r.to, insert: `[${text}](https://)` }, range: EditorSelection.range(at, at + 8) };
    }
    const changes = [];
    for (const [f, t] of segments(state, r)) {
      if (name === "clear") { const s = doc.sliceString(f, t), n = clearText(s); if (n !== s) changes.push({ from: f, to: t, insert: n }); }
      else changes.push(...(name === "color" ? colorSeg(doc, f, t, arg || null) : wrapSeg(doc, f, t, WRAPS[name])));
    }
    if (!changes.length) return { range: r };
    const cs = state.changes(changes), back = r.anchor > r.head;
    const a = cs.mapPos(r.from, name === "clear" ? -1 : 1), b = cs.mapPos(r.to, name === "clear" ? 1 : -1);
    return { changes: cs, range: back ? EditorSelection.range(b, a) : EditorSelection.range(a, Math.max(a, b)) };
  });
}

// 줄 명령(제목 순환·인용·작은 글씨·목록): 선택이 닿은 모든 줄. 여러 줄이면 빈 줄은 건너뛴다
function lineCmd(state, name) {
  const doc = state.doc, nums = new Set();
  for (const r of state.selection.ranges) for (let n = doc.lineAt(r.from).number, e = doc.lineAt(r.to).number; n <= e; n++) nums.add(n);
  const lines = [...nums].sort((a, b) => a - b).map((n) => doc.line(n))
    .filter((l) => (nums.size === 1 || l.text.trim()) && !inCode(state, l.from));
  if (!lines.length) return null;
  const changes = [];
  if (name === "heading") { // # -> ## -> ### -> 해제 (첫 줄 기준으로 모든 줄을 같은 단계로)
    const cur = /^(#{1,3}) /.exec(lines[0].text), next = cur ? (cur[1].length + 1) % 4 : 1;
    for (const l of lines) {
      const old = /^#{1,6} +/.exec(l.text);
      changes.push({ from: l.from, to: l.from + (old ? old[0].length : 0), insert: next ? "#".repeat(next) + " " : "" });
    }
  } else {
    const p = PREFIX[name], all = lines.every((l) => l.text.startsWith(p));
    for (const l of lines) {
      if (all) changes.push({ from: l.from, to: l.from + p.length });
      else if (!l.text.startsWith(p)) changes.push({ from: l.from, insert: p });
    }
  }
  const cs = state.changes(changes);
  return { changes: cs, selection: state.selection.map(cs, 1) };
}

function spec(state, name, arg) {
  if (name === "heading" || PREFIX[name]) return lineCmd(state, name);
  if (WRAPS[name] || name === "color" || name === "clear" || name === "link") return inline(state, name, arg);
  return null;
}

// 선택 위 버블: 비어 있지 않은 한 범위를 고르고, 마우스를 놓은 뒤(드래그 중엔 안 뜸), 조합 중·@ 힌트가 열려 있을 땐 숨김
const setBubble = StateEffect.define();
const bubbleOn = StateField.define({
  create: () => false,
  update(v, tr) { for (const e of tr.effects) if (e.is(setBubble)) v = e.value; return v; },
});

// formatting({undo}) -> {extension, exec(view, name, arg)}. undo: Y.UndoManager(서식 한 번이 되돌리기 한 번이 되게 끊는다)
export function formatting({ undo }) {
  const exec = (view, name, arg) => {
    if (view.composing || !view.state.facet(EditorView.editable) || view.contentDOM.closest("[inert]")) return false;
    const s = spec(view.state, name, arg);
    if (!s || (s.changes && s.changes.empty)) return false;
    if (undo) undo.stopCapturing();
    view.dispatch({ ...s, userEvent: "input.format", scrollIntoView: true });
    if (undo) undo.stopCapturing();
    return true;
  };
  // 단축키는 브라우저 기본 동작(Ctrl+U 소스 보기·Ctrl+I 등)보다 먼저: 처리했다고 알려 기본 동작을 막는다. 조합 중엔 건드리지 않는다
  const keys = Prec.high(keymap.of(COMMANDS.filter((c) => c.cmKey).map((c) => ({
    key: c.cmKey, run: (view) => { if (view.composing) return false; exec(view, c.name); return true; },
  }))));

  const coarse = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
  const bubbleTip = showTooltip.compute([bubbleOn, "selection"], (state) => {
    const r = state.selection.main;
    if (!state.field(bubbleOn) || r.empty || state.selection.ranges.length > 1) return null;
    return {
      pos: r.from, above: true, arrow: false,
      create(view) {
        const dom = document.createElement("div");
        dom.className = "cm-fmt-bubble"; dom.setAttribute("role", "toolbar"); dom.setAttribute("aria-label", "선택한 글 서식");
        dom.addEventListener("mousedown", (e) => e.preventDefault()); // 눌러도 선택·포커스를 잃지 않게
        const row = document.createElement("div"), pal = document.createElement("div");
        row.className = "cm-fmt-row"; pal.className = "cm-fmt-row cm-fmt-pal"; pal.hidden = true;
        const btn = (text, label, onClick, cls) => {
          const b = document.createElement("button");
          b.type = "button"; b.textContent = text; b.title = label; b.setAttribute("aria-label", label);
          if (cls) b.className = cls;
          b.addEventListener("click", onClick);
          return b;
        };
        for (const c of COMMANDS.filter((x) => x.bubble)) {
          const b = btn(c.icon, c.label + (c.key ? ` (${c.key})` : ""), () => {
            if (c.colors) { pal.hidden = !pal.hidden; b.setAttribute("aria-expanded", String(!pal.hidden)); return; }
            exec(view, c.name); view.focus();
          }, "cm-fmt-" + c.name);
          if (c.colors) b.setAttribute("aria-expanded", "false");
          row.append(b);
        }
        for (const { name: n, cls } of COMMANDS.find((x) => x.colors).colors) pal.append(btn("A", n, () => { exec(view, "color", n); view.focus(); }, "cm-fmt-swatch " + cls));
        pal.append(btn("✕", "색 해제", () => { exec(view, "color", null); view.focus(); }, "cm-fmt-swatch"));
        dom.append(row, pal);
        return { dom, offset: { x: 0, y: coarse ? 16 : 6 } }; // 폰: 선택 핸들과 겹치지 않게 조금 더 위
      },
    };
  });
  const watch = ViewPlugin.fromClass(class {
    constructor(view) {
      this.view = view; this.down = false; this.t = 0;
      this.up = () => { if (this.down) { this.down = false; this.schedule(); } };
      addEventListener("pointerup", this.up); addEventListener("pointercancel", this.up);
    }
    schedule() { clearTimeout(this.t); this.t = setTimeout(() => this.check(), 0); }
    check() {
      const v = this.view, s = v.state.selection;
      if (!v.dom.isConnected) return;
      const want = v.hasFocus && !this.down && !v.composing && s.ranges.length === 1 && !s.main.empty
        && completionStatus(v.state) !== "active" && !v.contentDOM.closest("[inert]");
      if (want !== v.state.field(bubbleOn)) v.dispatch({ effects: setBubble.of(want) });
    }
    update(u) {
      if (u.selectionSet || u.focusChanged || u.docChanged || completionStatus(u.state) !== completionStatus(u.startState)) this.schedule();
    }
    destroy() { clearTimeout(this.t); removeEventListener("pointerup", this.up); removeEventListener("pointercancel", this.up); }
  }, {
    eventHandlers: {
      pointerdown(e) { if (e.button === 0 && !e.target.closest?.(".cm-tooltip")) { this.down = true; this.schedule(); } },
      compositionstart() { this.schedule(); },
      compositionend() { this.schedule(); },
    },
  });
  return { extension: [keys, bubbleOn, bubbleTip, watch], exec };
}
