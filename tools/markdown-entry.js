import { marked } from "marked";
import DOMPurify from "dompurify";
import { findUrls } from "./url-rule.mjs";

// window.EvasMarkdown.render(text) -> 무해화한 HTML 문자열. 미리보기는 다른 사람이 쓴 글이라 반드시 이것을 거친다
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  // href가 있으면 태그와 무관하게 새 탭으로: 같은 탭이 외부 사이트로 바뀌거나(피싱) Referer가 새지 않게
  if (node.hasAttribute("href")) { node.setAttribute("target", "_blank"); node.setAttribute("rel", "noopener noreferrer"); }
  if (node.tagName === "INPUT") node.setAttribute("disabled", ""); // 체크박스는 읽기 전용
  if (node.tagName === "IMG") node.setAttribute("referrerpolicy", "no-referrer"); // 외부 이미지에 어느 메모를 보는지 안 알린다
});

const OPTIONS = {
  USE_PROFILES: { html: true }, // SVG·MathML은 쓰지 않는다(SVG <a xlink:href> 등 우회로 차단)
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i, // 스킴은 http/https/mailto만(상대 주소는 허용)
  // 화면 전체를 덮거나 입력을 받는 원시 HTML, 이미지 지도 링크, 외부 영상·소리
  FORBID_TAGS: ["style", "form", "button", "textarea", "select", "area", "video", "audio", "source", "track"],
  FORBID_ATTR: ["style"],
  SANITIZE_NAMED_PROPS: true, // id·name에 접두어를 붙여 앱의 id(e-meta 등)를 가로채지 못하게
};

// 그냥 적은 http(s) 주소는 에디터와 같은 규칙(url-rule.mjs)으로 링크한다. 그 밖(메일 등)은 marked 기본 자동 링크
marked.use({
  tokenizer: {
    url(src) {
      const www = /^www\./i.test(src); // www.로 시작하는 주소도 같은 규칙(http:// 붙여 판단)
      if (!www && !/^https?:\/\//i.test(src)) return false;
      const u = findUrls(www ? "http://" + src : src).next().value;
      // 규칙상 주소가 아니면 링크하지 않는다(false를 돌려주면 marked 기본 규칙이 한글까지 다시 링크한다)
      if (!u || u.from || (www && !/^http:\/\/www\.[^.]/i.test(u.url))) return;
      const raw = www ? u.url.slice(7) : u.url;
      return { type: "link", raw, text: raw, href: u.url, tokens: [{ type: "text", raw, text: raw }] };
    },
  },
});

// breaks: 메모는 줄 단위로 쓰므로 줄바꿈 한 번도 줄바꿈으로 보인다
const render = (text) => DOMPurify.sanitize(marked.parse(String(text), { gfm: true, breaks: true, async: false }), OPTIONS);

window.EvasMarkdown = { render };
