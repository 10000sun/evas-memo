import { marked } from "marked";
import DOMPurify from "dompurify";

// window.EvasMarkdown.render(text) -> 무해화한 HTML 문자열. 미리보기는 다른 사람이 쓴 글이라 반드시 이것을 거친다
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") { node.setAttribute("target", "_blank"); node.setAttribute("rel", "noopener noreferrer"); }
  if (node.tagName === "INPUT") node.setAttribute("disabled", ""); // 체크박스는 읽기 전용
});

const OPTIONS = {
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i, // 스킴은 http/https/mailto만(상대 주소는 허용)
  FORBID_TAGS: ["style", "form", "button", "textarea", "select"], // 화면 전체를 덮거나 입력을 받는 원시 HTML
  FORBID_ATTR: ["style"],
  SANITIZE_NAMED_PROPS: true, // id·name에 접두어를 붙여 앱의 id(e-meta 등)를 가로채지 못하게
};

// breaks: 메모는 줄 단위로 쓰므로 줄바꿈 한 번도 줄바꿈으로 보인다
const render = (text) => DOMPurify.sanitize(marked.parse(String(text), { gfm: true, breaks: true, async: false }), OPTIONS);

window.EvasMarkdown = { render };
