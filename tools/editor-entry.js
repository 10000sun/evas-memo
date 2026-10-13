import { EditorView, basicSetup } from "codemirror";
import { EditorState } from "@codemirror/state";
import * as Y from "yjs";
import { WebsocketProvider } from "y-websocket";
import { yCollab } from "y-codemirror.next";

// window.EvasEditor.create({parent, memoId, user:{name,color}}) -> {destroy(), view}
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
      extensions: [basicSetup, EditorView.lineWrapping, yCollab(text, provider.awareness)],
    }),
  });
  return {
    view,
    awareness: provider.awareness,
    destroy() {
      view.destroy();
      provider.destroy();
      doc.destroy();
    },
  };
}

window.EvasEditor = { create };
