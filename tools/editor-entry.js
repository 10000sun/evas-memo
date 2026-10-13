import { EditorView, basicSetup } from "codemirror";
import { EditorState, Prec, RangeSetBuilder } from "@codemirror/state";
import { Decoration, ViewPlugin, WidgetType, keymap } from "@codemirror/view";
import { indentLess, indentMore } from "@codemirror/commands";
import * as Y from "yjs";
import { WebsocketProvider } from "y-websocket";
import { yCollab, yUndoManagerKeymap } from "y-codemirror.next";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { HighlightStyle, indentUnit, syntaxHighlighting, syntaxTree } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";
import { findUrls } from "./url-rule.mjs";

// 마크다운 입력 강조. 색은 style.css 변수를 써서 라이트·다크를 따라간다
const mdHighlight = HighlightStyle.define([
  { tag: t.heading, fontWeight: "700", color: "var(--primary)" },
  { tag: t.strong, fontWeight: "700" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strikethrough, textDecoration: "line-through" },
  { tag: [t.link, t.url], color: "var(--primary)" },
  { tag: t.monospace, fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace", fontSize: ".92em" },
  { tag: t.quote, color: "var(--muted)", fontStyle: "italic" },
  { tag: [t.processingInstruction, t.contentSeparator, t.meta, t.comment], color: "var(--muted)" },
]);

// 본문의 http(s) 주소(마크다운 링크의 주소 포함): 밑줄·링크 색 + 바로 뒤 "↗" 버튼(문서 밖 위젯)으로 새 탭 열기.
// 글자 클릭은 편집(커서)용으로 두고, PC는 Ctrl/Cmd+클릭으로도 연다. 주소 규칙(url-rule.mjs)이 http(s)만 잡아 다른 스킴은 위젯도 없다
const openUrl = (url) => window.open(url, "_blank", "noopener,noreferrer");
class OpenLink extends WidgetType {
  constructor(url) { super(); this.url = url; }
  eq(o) { return o.url === this.url; }
  toDOM() {
    const b = document.createElement("button");
    b.type = "button"; b.className = "cm-url-open"; b.textContent = "↗";
    b.title = "새 탭에서 열기"; b.setAttribute("aria-label", "새 탭에서 열기: " + this.url);
    b.onclick = () => openUrl(this.url);
    return b;
  }
  ignoreEvent() { return true; } // 버튼 클릭이 커서 이동·선택으로 처리되지 않게
}
const urlMark = Decoration.mark({ class: "cm-url" });
function linkDecos(view) {
  const b = new RangeSetBuilder();
  for (const { from, to } of view.visibleRanges)
    for (const u of findUrls(view.state.sliceDoc(from, to), from)) {
      b.add(u.from, u.to, urlMark);
      b.add(u.to, u.to, Decoration.widget({ widget: new OpenLink(u.url), side: 1 }));
    }
  return b.finish();
}
const links = ViewPlugin.fromClass(class {
  constructor(view) { this.decorations = linkDecos(view); }
  update(u) { if (u.docChanged || u.viewportChanged) this.decorations = linkDecos(u.view); } // 다른 사람의 입력도 docChanged
}, {
  decorations: (p) => p.decorations,
  eventHandlers: {
    mousedown(e, view) {
      if (!(e.ctrlKey || e.metaKey) || e.button !== 0) return false;
      const pos = view.posAtCoords({ x: e.clientX, y: e.clientY });
      if (pos == null) return false;
      const line = view.state.doc.lineAt(pos);
      for (const u of findUrls(line.text, line.from)) if (pos >= u.from && pos <= u.to) { e.preventDefault(); openUrl(u.url); return true; }
      return false;
    },
  },
});

// Tab: 커서 자리에 공백 4칸(탭 문자 아님), 여러 글자/줄을 고르면 줄 들여쓰기. Shift+Tab: 줄 앞 공백 최대 4칸 내어쓰기.
// 목록: Enter 이어쓰기·번호 +1·빈 항목 해제는 markdown()의 markdownKeymap이 한다. 여기서는 표시만 있는 항목의 Tab(하위 목록, 번호 1부터)과
// 번호 항목의 Shift+Tab(같은 단계 직전 번호 +1)만 맞춘다. 키보드로 에디터를 벗어나려면 Esc 뒤 Tab(CodeMirror 기본 동작)
const EMPTY_ITEM = /^( *)(?:[-*+]|(\d+)([.)]))( +)(\[[ xX]\] +)?$/;
const ORDERED = /^( *)(\d+)([.)])/;
// 코드 블록(펜스·들여쓰기 코드) 안에서는 목록 규칙을 쓰지 않는다
function inCode(state, pos) {
  for (let n = syntaxTree(state).resolveInner(pos, -1); n; n = n.parent) if (n.name === "FencedCode" || n.name === "CodeBlock") return true;
  return false;
}
function tab(view) {
  const s = view.state, sel = s.selection.main;
  if (s.selection.ranges.some((r) => !r.empty)) return indentMore(view);
  const line = s.doc.lineAt(sel.head), m = s.selection.ranges.length === 1 && sel.head === line.to && !inCode(s, sel.head) && EMPTY_ITEM.exec(line.text);
  if (m) {
    const text = "    " + (m[2] ? m[1] + "1" + m[3] + m[4] + (m[5] || "") : line.text);
    view.dispatch({ changes: { from: line.from, to: line.to, insert: text }, selection: { anchor: line.from + text.length }, userEvent: "input.indent" });
    return true;
  }
  view.dispatch(s.replaceSelection("    "), { scrollIntoView: true, userEvent: "input" });
  return true;
}
function shiftTab(view) {
  const s = view.state, sel = s.selection.main;
  const line = s.doc.lineAt(sel.head), m = ORDERED.exec(line.text);
  if (s.selection.ranges.length > 1 || !sel.empty || !m || !m[1] || inCode(s, sel.head)) return indentLess(view);
  const depth = Math.max(0, m[1].length - 4);
  let num = m[2]; // 같은 단계의 직전 번호를 못 찾으면 그대로
  for (let n = line.number - 1; n >= 1; n--) {
    const t = s.doc.line(n).text, ind = t.length - t.trimStart().length;
    if (!t.trim() || ind > depth) continue;
    const p = ORDERED.exec(t);
    if (ind === depth && p) num = String(+p[2] + 1);
    break;
  }
  view.dispatch({ changes: { from: line.from, to: line.from + m[0].length, insert: " ".repeat(depth) + num + m[3] }, userEvent: "delete.dedent" });
  return true;
}
// 표시만 있는 목록·인용 줄에서 Enter: 표시를 지워 일반 줄로(lang-markdown 기본은 빈 줄을 넣고 표시를 남긴다). 코드 블록 안은 그대로.
// 바로 윗줄에 글이 있으면 빈 줄을 하나 둔다: 붙여 쓰면 마크다운에서 윗 목록·인용에 이어지는 글이 된다(lazy continuation)
function enterOnEmptyItem(view) {
  const s = view.state, sel = s.selection.main, line = s.doc.lineAt(sel.head);
  if (s.selection.ranges.length > 1 || !sel.empty || sel.head !== line.to || !(EMPTY_ITEM.test(line.text) || /^ *> ?$/.test(line.text))) return false;
  if (inCode(s, sel.head)) return false;
  const gap = line.number > 1 && s.doc.line(line.number - 1).text.trim() ? "\n" : "";
  view.dispatch({ changes: { from: line.from, to: line.to, insert: gap }, selection: { anchor: line.from + gap.length }, userEvent: "delete" });
  return true;
}
// markdown()의 Enter(이어쓰기)보다 먼저 돈다: 같은 Prec.high에서 확장 목록 앞쪽이 우선
const tabKeys = Prec.high(keymap.of([{ key: "Tab", run: tab, shift: shiftTab }, { key: "Enter", run: enterOnEmptyItem }]));
// 되돌리기는 Y.UndoManager(yCollab이 만든 것)로: 내 편집만 되돌린다. basicSetup의 history는 원격 편집까지 되돌린다
const undoKeys = Prec.high(keymap.of(yUndoManagerKeymap));

// window.EvasEditor.create({parent, memoId, user:{name,color}}) -> {destroy(), view, awareness, provider}
// provider: 화면이 연결 상태('status')·닫힘 코드('connection-close')·문서(provider.doc)를 본다
function create({ parent, memoId, user }) {
  const doc = new Y.Doc();
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  // y-websocket은 `${서버주소}/${방이름}`으로 접속한다 -> /ws/memos/{memoId}
  const provider = new WebsocketProvider(`${proto}//${location.host}/ws/memos`, String(memoId), doc);
  provider.awareness.setLocalStateField("user", { name: user.name, color: user.color, colorLight: user.color + "33" });
  const text = doc.getText("text");
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: text.toString(),
      extensions: [basicSetup, EditorView.lineWrapping, indentUnit.of("    "), undoKeys, tabKeys, markdown({ base: markdownLanguage }),
        syntaxHighlighting(mdHighlight), links, yCollab(text, provider.awareness)],
    }),
  });
  return {
    view,
    awareness: provider.awareness,
    provider,
    destroy() {
      view.destroy();
      provider.destroy();
      doc.destroy();
    },
  };
}

window.EvasEditor = { create };
