import { EditorView, basicSetup } from "codemirror";
import { EditorState, Prec, RangeSetBuilder } from "@codemirror/state";
import { Decoration, ViewPlugin, WidgetType, keymap } from "@codemirror/view";
import { indentLess, indentMore } from "@codemirror/commands";
import * as Y from "yjs";
import { WebsocketProvider } from "y-websocket";
import { yCollab } from "y-codemirror.next";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { HighlightStyle, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";

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
// 글자 클릭은 편집(커서)용으로 두고, PC는 Ctrl/Cmd+클릭으로도 연다. 정규식이 http(s)만 잡아 다른 스킴은 위젯도 없다
const URL_RE = /https?:\/\/[^\s<>()[\]"'`]+/g;
function* urlsIn(text, base) {
  for (const m of text.matchAll(URL_RE)) {
    const url = m[0].replace(/[.,;:!?]+$/, ""); // 문장 끝 부호는 주소가 아니다
    yield { from: base + m.index, to: base + m.index + url.length, url };
  }
}
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
    for (const u of urlsIn(view.state.sliceDoc(from, to), from)) {
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
      for (const u of urlsIn(line.text, line.from)) if (pos >= u.from && pos <= u.to) { e.preventDefault(); openUrl(u.url); return true; }
      return false;
    },
  },
});

// Tab: 커서 자리에 공백 4칸(탭 문자 아님), 여러 글자/줄을 고르면 줄 들여쓰기. Shift+Tab: 줄 앞 공백 최대 4칸 내어쓰기.
// 키보드로 에디터를 벗어나려면 Esc 뒤 Tab(CodeMirror 기본 동작)
const tabKeys = Prec.high(keymap.of([{
  key: "Tab",
  run: (view) => view.state.selection.ranges.some((r) => !r.empty) ? indentMore(view)
    : (view.dispatch(view.state.replaceSelection("    "), { scrollIntoView: true, userEvent: "input" }), true),
  shift: indentLess,
}]));

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
      extensions: [basicSetup, EditorView.lineWrapping, indentUnit.of("    "), tabKeys, markdown({ base: markdownLanguage }),
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
