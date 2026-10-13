import { marked } from "marked";
import DOMPurify from "dompurify";
import { urlAtStart } from "./url-rule.mjs";

// window.EvasMarkdown.render(text) -> 무해화한 HTML 문자열. 미리보기는 다른 사람이 쓴 글이라 반드시 이것을 거친다
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  // href가 있으면 태그와 무관하게 새 탭으로: 같은 탭이 외부 사이트로 바뀌거나(피싱) Referer가 새지 않게
  if (node.hasAttribute("href")) { node.setAttribute("target", "_blank"); node.setAttribute("rel", "noopener noreferrer"); }
  // input은 할 일 체크박스(읽기 전용)만 남긴다: type=image 같은 것은 외부 이미지를 불러온다
  if (node.tagName === "INPUT") node.getAttribute("type") === "checkbox" ? node.setAttribute("disabled", "") : node.remove();
  if (node.tagName === "IMG") node.setAttribute("referrerpolicy", "no-referrer"); // 외부 이미지에 어느 메모를 보는지 안 알린다
});

const OPTIONS = {
  USE_PROFILES: { html: true }, // SVG·MathML은 쓰지 않는다(SVG <a xlink:href> 등 우회로 차단)
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i, // 스킴은 http/https/mailto만(상대 주소는 허용)
  // 화면 전체를 덮거나 입력을 받는 원시 HTML, 이미지 지도 링크, 외부 영상·소리
  FORBID_TAGS: ["style", "form", "button", "textarea", "select", "area", "video", "audio", "source", "track"],
  // style: 화면 덮기, for·form·formaction: 미리보기 글자로 앱 버튼(삭제·로그아웃 등) 누르기, background: 외부 이미지
  FORBID_ATTR: ["style", "for", "form", "formaction", "background"],
  SANITIZE_NAMED_PROPS: true, // id·name에 접두어를 붙여 앱의 id(e-meta 등)를 가로채지 못하게
};

// 그냥 적은 http(s)·www. 주소는 에디터와 같은 규칙(url-rule.mjs)으로 링크한다. 그 밖(메일 등)은 marked 기본 자동 링크.
// marked가 주소 후보마다 다시 부르므로 맨 앞에서 한 번만 맞춰 본다(남은 글 전체를 훑으면 긴 메모에서 제곱 시간)
marked.use({
  tokenizer: {
    url(src) {
      if (!/^(?:https?:\/\/|www\.)/i.test(src)) return false;
      const raw = urlAtStart(src);
      if (!raw) return; // 규칙상 주소가 아니면 링크하지 않는다(false를 돌려주면 marked 기본 규칙이 한글까지 다시 링크한다)
      const href = /^www\./i.test(raw) ? "http://" + raw : raw;
      return { type: "link", raw, text: raw, href, tokens: [{ type: "text", raw, text: raw }] };
    },
  },
});

// marked의 짝 없는 강조(* _ ~~)·중첩 처리는 글 길이의 제곱에 가깝게 느려져, 긴 메모의 미리보기가 보는 모두의 화면을 멈춘다
// (node+jsdom 실측: '*abc '·'**a ' 같은 반복이 2만 자 1~5초, 5만 자 12~32초, 10만 자 37~99초). 6000자는 퍼징 최악이 약 0.5초
const LIMIT = 6000;
// shortcut: 앞 LIMIT자만 그린다. 긴 메모 전체를 미리보기로 보려면 선형 시간 파서가 필요
const clip = (text) => {
  if (text.length <= LIMIT) return text;
  const nl = text.lastIndexOf("\n", LIMIT); // 줄 경계에서 자른다(줄바꿈이 없으면 LIMIT자, 이모지 반쪽은 뺀다)
  return nl > 0 ? text.slice(0, nl) : text.slice(0, LIMIT).replace(/[\uD800-\uDBFF]$/, "");
};
const esc = (t) => t.replace(/[&<>"']/g, (c) => "&#" + c.charCodeAt(0) + ";");

// breaks: 메모는 줄 단위로 쓰므로 줄바꿈 한 번도 줄바꿈으로 보인다
const parse = (text) => DOMPurify.sanitize(marked.parse(text, { gfm: true, breaks: true, async: false }), OPTIONS);
const render = (input) => {
  const text = String(input), head = clip(text);
  let html;
  try { html = parse(head); }
  catch { html = '<pre class="md-fallback">' + esc(head) + "</pre>"; } // 깊게 중첩된 > · 1. 는 marked가 호출 깊이를 넘는다: 글 그대로 보여 준다
  // 안내는 마크다운 밖에서 붙인다: 잘린 곳이 코드 블록 안이어도 안내가 그 안에 들어가지 않고, 숫자는 상수라 주입이 없다
  return head.length < text.length ? html + `<p class="md-clip">미리보기는 앞부분 ${LIMIT}자까지만 표시합니다. 전체는 편집 화면에서 볼 수 있습니다.</p>` : html;
};

window.EvasMarkdown = { render, LIMIT };
