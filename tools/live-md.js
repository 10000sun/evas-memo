// 디스코드식 라이브 표시: 커서·선택이 없는 줄은 마크다운 표시를 숨기고 꾸민 모양으로, 커서가 있는 줄은 원문 그대로 보여 고친다.
// 장식만 한다(문서 글자는 바꾸지 않는다). 화면에 보이는 범위(visibleRanges)만 훑어 긴 문서에서도 선형으로 끝난다
import { StateEffect } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, WidgetType } from "@codemirror/view";
import { syntaxTree } from "@codemirror/language";
import { findUrls } from "./url-rule.mjs";
import { TEXT_COLORS, COLOR_OPEN } from "./text-colors.mjs";

const MAX_LINE = 10000; // 이보다 긴 줄은 줄 단위 훑기(스포일러·글자 색·인용 등)를 건너뛴다
const MAX_PER_LINE = 300; // 한 줄에서 찾는 스포일러·글자 색 개수 상한(|나 { 수만 개에도 멈추지 않게)
const NO_LINE_RULES = new Set(["FencedCode", "CodeBlock", "Table", "HTMLBlock", "CommentBlock"]);
const refresh = StateEffect.define();

const hideDeco = Decoration.replace({});
const markCache = new Map(), lineCache = new Map();
const markDeco = (c) => markCache.get(c) || markCache.set(c, Decoration.mark({ class: c })).get(c);
const lineDeco = (c) => lineCache.get(c) || lineCache.set(c, Decoration.line({ class: c })).get(c);
class Bullet extends WidgetType {
  eq() { return true; }
  toDOM() { const s = document.createElement("span"); s.className = "cm-bullet"; s.textContent = "•"; return s; }
}
const bulletDeco = Decoration.replace({ widget: new Bullet() });

const within = (state, pos, names) => {
  for (let n = syntaxTree(state).resolveInner(pos, 1); n; n = n.parent) if (names.has(n.name)) return true;
  return false;
};
const CODE = new Set(["InlineCode"]);
// 주소 글자가 통째로 http(s) 주소면 그 주소, 아니면 null(user: 등)
const webUrl = (u) => { for (const x of findUrls(u)) return x.from === 0 && x.to === u.length ? x.url : null; return null; };

// ">>> " 여러 줄 인용이 시작되는 줄 위치(없으면 -1). 맨 위 단계 인용 블록과 그 안의 인용만 본다(end 이후는 볼 필요 없음)
function multiQuote(state, end) {
  const doc = state.doc, at = (pos) => { const l = doc.lineAt(pos); return doc.sliceString(l.from, l.from + 4) === ">>> " ? l.from : -1; };
  for (let n = syntaxTree(state).topNode.firstChild; n && n.from <= end; n = n.nextSibling) {
    if (n.name !== "Blockquote") continue;
    let p = at(n.from);
    for (let c = n.firstChild; p < 0 && c && c.from <= end; c = c.nextSibling) if (c.name === "Blockquote") p = at(c.from);
    if (p >= 0) return p;
  }
  return -1;
}

function build(view, linkWidget) {
  const { state } = view, doc = state.doc, tree = syntaxTree(state);
  // 커서·선택이 닿은 줄은 원문 그대로. 포커스가 없으면 모든 줄을 꾸민다(읽기 모드)
  const act = view.hasFocus ? state.selection.ranges.map((r) => [doc.lineAt(r.from).from, doc.lineAt(r.to).to]) : [];
  const shown = (pos) => act.some(([a, b]) => pos >= a && pos <= b);
  const marks = [], hidden = [], lines = new Map(), seen = new Set();
  // 보이는 범위 두 곳에 걸친 노드는 두 번 지나가므로 같은 장식은 한 번만
  const mark = (from, to, c) => {
    const k = c + from + "," + to;
    if (to > from && !seen.has(k)) { seen.add(k); marks.push(markDeco(c).range(from, to)); }
  };
  const addLine = (pos, c) => { const s = lines.get(pos); if (s) s.add(c); else lines.set(pos, new Set([c])); };
  // 같은 줄 안의 범위만 숨긴다(줄바꿈을 숨기면 줄 구조가 바뀐다)
  const hide = (from, to, deco = hideDeco) => {
    if (to <= from || shown(from) || to > doc.lineAt(from).to) return;
    const k = from + "," + to;
    if (!seen.has(k)) { seen.add(k); hidden.push(deco.range(from, to)); }
  };
  const vr = view.visibleRanges, mq = vr.length ? multiQuote(state, vr[vr.length - 1].to) : -1;
  const doneLines = new Set();

  for (const { from, to } of vr) {
    tree.iterate({
      from, to,
      enter: (n) => {
        switch (n.name) {
          case "ATXHeading1": case "ATXHeading2": case "ATXHeading3": { // #### 부터는 디스코드 제목이 아니다
            const l = doc.lineAt(n.from), m = n.node.firstChild;
            addLine(l.from, "cm-h" + n.name.slice(-1));
            if (m && m.name === "HeaderMark") {
              let e = m.to;
              while (e < l.to && doc.sliceString(e, e + 1) === " ") e++;
              if (e < l.to) hide(m.from, e);
            }
            break;
          }
          case "Emphasis": case "StrongEmphasis": case "Strikethrough": case "InlineCode": {
            const ms = n.node.getChildren(n.name === "Strikethrough" ? "StrikethroughMark" : n.name === "InlineCode" ? "CodeMark" : "EmphasisMark");
            if (ms.length < 2) break;
            const first = ms[0], last = ms[ms.length - 1];
            // __글__ 은 디스코드에서 밑줄(굵게 아님). **글** 은 cm-b: 밑줄 안에 들어가도 굵게 남게
            if (n.name === "StrongEmphasis") mark(n.from, n.to, doc.sliceString(first.from, first.to) === "__" ? "cm-u" : "cm-b");
            if (n.name === "InlineCode") mark(first.to, last.from, "cm-code");
            hide(first.from, first.to); hide(last.from, last.to);
            if (n.name === "InlineCode") return false;
            break;
          }
          case "Link": { // [글](주소): "[" 와 "](주소)" 를 숨기고 글만 링크 색. http(s)면 숨긴 자리에 ↗ 버튼
            const lm = n.node.getChildren("LinkMark"), url = n.node.getChild("URL");
            if (lm.length < 3 || !url || doc.sliceString(lm[1].to, lm[1].to + 1) !== "(") break;
            const open = lm[0], close = lm[1], u = doc.sliceString(url.from, url.to);
            if (close.from <= open.to) break;
            const isHidden = !shown(close.from);
            const tag = doc.sliceString(open.to, open.to + 1) === "@" || u.startsWith("user:"); // [@제목](…)·[@이름](user:id) 태그
            mark(open.to, close.from, tag && isHidden ? "cm-mlink cm-tag" : "cm-mlink");
            if (doc.lineAt(open.from).number !== doc.lineAt(n.to).number) break;
            const web = webUrl(u);
            hide(open.from, open.to);
            hide(close.from, n.to, web ? Decoration.replace({ widget: linkWidget(web) }) : hideDeco);
            break;
          }
          case "Escape": hide(n.from, n.from + 1); break; // \* 의 \
          case "ListMark": { // - · * 목록 표시는 • 로(할 일 목록 - [ ] 은 그대로)
            const item = n.node.parent;
            if (item && item.parent && item.parent.name === "BulletList" && !item.getChild("Task") && n.to - n.from === 1 && doc.sliceString(n.to, n.to + 1) === " ")
              hide(n.from, n.to, bulletDeco);
            break;
          }
          case "FencedCode": { // 코드 블록: 줄마다 배경, 펜스 줄은 흐리게(숨기지 않는다)
            const a = Math.max(n.from, from), b = Math.min(n.to, to);
            for (let p = doc.lineAt(a).from; p <= b;) { const l = doc.lineAt(p); addLine(l.from, "cm-codeblock"); p = l.to + 1; }
            addLine(doc.lineAt(n.from).from, "cm-fence");
            const lc = n.node.lastChild;
            if (lc && lc.name === "CodeMark" && lc.from > doc.lineAt(n.from).to) addLine(doc.lineAt(lc.from).from, "cm-fence");
            return false;
          }
          case "Table": case "HTMLBlock": case "CodeBlock": case "CommentBlock": return false; // 디스코드에 없는 것: 기존 강조 그대로
        }
      },
    });

    // 줄 단위(트리가 모르는 디스코드 문법): 인용·여러 줄 인용·작은 글씨·스포일러·글자 색
    for (let p = from; p <= to;) {
      const l = doc.lineAt(p);
      p = l.to + 1;
      if (doneLines.has(l.from)) continue;
      doneLines.add(l.from);
      if (mq >= 0 && l.from >= mq) addLine(l.from, "cm-quote");
      if (l.length > MAX_LINE || within(state, l.from, NO_LINE_RULES)) continue;
      const head = doc.sliceString(l.from, Math.min(l.to, l.from + 4));
      if (head === ">>> ") { addLine(l.from, "cm-quote"); hide(l.from, l.from + 4); }
      else if (head.startsWith("> ")) { addLine(l.from, "cm-quote"); hide(l.from, l.from + 2); }
      else if (head.startsWith("-# ") && l.length > 3) { addLine(l.from, "cm-sub"); hide(l.from, l.from + 3); }
      const text = doc.sliceString(l.from, l.to);
      if (text.includes("||")) spoilers(text, l.from);
      if (text.includes("{")) colors(text, l.from);
    }
  }

  // ||글|| : 같은 줄 안에서 앞에서부터 짝짓는다. 인라인 코드 안·\| 뒤는 건너뛴다
  function spoilers(text, base) {
    for (let i = 0, k = 0; k < MAX_PER_LINE; k++) {
      const a = text.indexOf("||", i);
      if (a < 0) return;
      if (a && text[a - 1] === "\\") { i = a + 2; continue; }
      const b = text.indexOf("||", a + 3);
      if (b < 0) return;
      const A = base + a, B = base + b;
      if (within(state, A, CODE) || within(state, B, CODE)) { i = a + 2; continue; }
      hide(A, A + 2); hide(B, B + 2);
      mark(A + 2, B, shown(A) ? "cm-spoiler-on" : "cm-spoiler");
      i = b + 2;
    }
  }
  // {빨강|글} : 여는 표시 뒤 첫 } 까지. 겹쳐 쓴 색은 지원하지 않는다
  function colors(text, base) {
    COLOR_OPEN.lastIndex = 0;
    for (let k = 0, m; k < MAX_PER_LINE && (m = COLOR_OPEN.exec(text)); k++) {
      const e = m.index + m[0].length, c = text.indexOf("}", e);
      if (c < 0) return;
      COLOR_OPEN.lastIndex = c + 1;
      const A = base + m.index;
      if (c === e || within(state, A, CODE)) continue;
      hide(A, base + e); hide(base + c, base + c + 1);
      mark(base + e, base + c, "cm-tc-" + TEXT_COLORS[m[1]]);
    }
  }

  for (const [pos, set] of lines) marks.push(lineDeco([...set].join(" ")).range(pos));
  return { marks: Decoration.set(marks, true), hidden: Decoration.set(hidden, true) };
}

// linkWidget(url): 숨긴 "](주소)" 자리에 둘 ↗ 위젯, openUrl(url): Ctrl/Cmd+클릭으로 링크 글을 열 때
export function liveMarkdown({ linkWidget, openUrl }) {
  const plugin = ViewPlugin.fromClass(class {
    constructor(view) { this.stale = false; Object.assign(this, build(view, linkWidget)); }
    update(u) {
      const want = u.docChanged || u.viewportChanged || u.selectionSet || u.focusChanged || this.stale
        || syntaxTree(u.startState) !== syntaxTree(u.state) || u.transactions.some((tr) => tr.effects.some((e) => e.is(refresh)));
      if (!want) return;
      if (u.view.composing) { // 한글 조합 중: 다시 그리지 않고 위치만 옮긴다(조합 글자 둘레가 바뀌면 입력기가 끊긴다)
        this.marks = this.marks.map(u.changes); this.hidden = this.hidden.map(u.changes); this.stale = true;
        return;
      }
      this.stale = false;
      Object.assign(this, build(u.view, linkWidget));
    }
  }, {
    decorations: (p) => p.marks,
    // 숨긴 범위는 한 덩어리: 화살표 키가 건너뛰고 클릭도 그 가장자리에 커서를 둔다
    provide: (p) => [
      EditorView.decorations.of((v) => v.plugin(p)?.hidden || Decoration.none),
      EditorView.atomicRanges.of((v) => v.plugin(p)?.hidden || Decoration.none),
    ],
    eventHandlers: {
      mousedown(e, view) { // Ctrl/Cmd+클릭: 링크 글([글](주소)의 글)도 연다
        if (!(e.ctrlKey || e.metaKey) || e.button !== 0) return false;
        const pos = view.posAtCoords({ x: e.clientX, y: e.clientY });
        if (pos == null) return false;
        for (const side of [1, -1])
          for (let n = syntaxTree(view.state).resolveInner(pos, side); n; n = n.parent) {
            if (n.name !== "Link") continue;
            const url = n.getChild("URL"), web = url && webUrl(view.state.sliceDoc(url.from, url.to));
            if (!web) return false;
            e.preventDefault(); openUrl(web);
            return true;
          }
        return false;
      },
      compositionend(_e, view) { // 조합이 끝나면 미뤄 둔 장식을 다시 그린다
        setTimeout(() => { if (this.stale && !view.composing && view.dom.isConnected) view.dispatch({ effects: refresh.of(null) }); }, 0);
      },
    },
  });
  return plugin;
}
