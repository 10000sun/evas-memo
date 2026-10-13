import { marked } from "marked";
import DOMPurify from "dompurify";
import { urlAtStart } from "./url-rule.mjs";

// window.EvasMarkdown.render(text) -> 무해화한 HTML 문자열. 미리보기는 다른 사람이 쓴 글이라 반드시 이것을 거친다
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  // href가 있으면 태그와 무관하게 새 탭으로: 같은 탭이 외부 사이트로 바뀌거나(피싱) Referer가 새지 않게
  if (node.hasAttribute("href")) { node.setAttribute("target", "_blank"); node.setAttribute("rel", "noopener noreferrer"); }
  if (node.hasAttribute("href") && !node.hasAttribute("title")) node.setAttribute("title", "클릭하면 새 탭에서 열립니다"); // 올려 두면 보이는 안내
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

// 사람 태그 [@이름](user:<id>)는 링크가 아니라 이름 칩으로 그린다(user:는 허용 스킴이 아니라 그대로 두면 링크가 사라진다).
// 이름은 marked가 이미 글로 처리한 조각이고, 결과는 아래 DOMPurify를 거친다
marked.use({
  renderer: {
    link({ href, tokens }) {
      if (!/^user:[A-Za-z0-9_-]{1,40}$/.test(href || "")) return false; // 그 밖의 링크는 기본 처리
      return `<span class="md-user">${this.parser.parseInline(tokens)}</span>`;
    },
  },
});

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

// 디스코드식 문법. 원시 HTML은 지원하지 않아 글자 그대로 보인다(블록 html·인라인 tag 토크나이저를 끈다. 아래 DOMPurify는 이중 방어).
// 토크나이저가 undefined를 돌려주면 기본 규칙으로 넘어가지 않는다(false여야 넘어간다)
const none = () => undefined;
// 쌍 기호(__ ||): src 맨 앞 기호 두 개가 여는 쪽. 같은 문단(빈 줄 앞)에서 닫는 쪽을 찾아 {raw, inner}를 돌려준다.
// 닫는 쪽은 기호가 이어진 덩어리의 마지막 두 개이고 앞에 \가 홀수 개면 이스케이프다. 한 문단은 LIMIT자 이하라 최악의 탐색도 짧다
function pairAt(src, ch, wordGuard) {
  const mark = ch + ch, blank = src.indexOf("\n\n"), lim = blank < 0 ? src.length : blank;
  const body = ch === "|" ? /[^\s|]/ : /[^\s_]/;
  for (let j = 2; (j = src.indexOf(mark, j)) !== -1 && j < lim;) {
    let k = j, bs = 0;
    while (k < lim && src[k] === ch) k++;
    for (let b = j - 1; b >= 2 && src[b] === "\\"; b--) bs++;
    const c = k - 2;
    if (c >= j + (bs % 2) && c > 2 && !(wordGuard && /[A-Za-z0-9]/.test(src[k] || "")) && body.test(src.slice(2, c))) return { raw: src.slice(0, k), inner: src.slice(2, c) };
    j = k;
  }
}
const pairStart = (mark) => (src) => { const i = src.indexOf(mark); return i < 0 ? undefined : i; };
// 글자 색 {이름|글자}: 디스코드에 없는 우리 문법. 이름은 한글 두 글자
const COLORS = { 빨강: "red", 주황: "orange", 노랑: "yellow", 초록: "green", 파랑: "blue", 보라: "purple", 분홍: "pink", 회색: "gray" };
let inBigQuote = false; // >>> 안에서는 다시 >>>를 큰 인용으로 보지 않는다(중첩 깊이 제한)
marked.use({
  extensions: [
    { // __밑줄__: 기본 굵게보다 먼저 맞춘다. 영숫자 바로 뒤의 __ 와 영숫자 바로 앞의 __ 는 밑줄이 아니다(snake__case)
      name: "underline", level: "inline", start: pairStart("__"),
      tokenizer(src, tokens) {
        if (src[0] !== "_" || src[1] !== "_") return;
        const prev = tokens.length ? tokens[tokens.length - 1].raw.slice(-1) : "";
        if (/[A-Za-z0-9]/.test(prev)) return;
        const m = pairAt(src, "_", true);
        return m && { type: "underline", raw: m.raw, text: m.inner, tokens: this.lexer.inlineTokens(m.inner) };
      },
      renderer(t) { return `<u>${this.parser.parseInline(t.tokens)}</u>`; },
    },
    { // ||스포일러||: 눌러야 보인다(app.js)
      name: "spoiler", level: "inline", start: pairStart("||"),
      tokenizer(src) {
        if (src[0] !== "|" || src[1] !== "|") return;
        const m = pairAt(src, "|", false);
        return m && { type: "spoiler", raw: m.raw, text: m.inner, tokens: this.lexer.inlineTokens(m.inner) };
      },
      renderer(t) { return `<span class="md-spoiler" tabindex="0">${this.parser.parseInline(t.tokens)}</span>`; },
    },
    { // {빨강|글자}: 같은 줄의 첫 } 까지
      name: "color", level: "inline", start: pairStart("{"),
      tokenizer(src) {
        const name = COLORS[src.slice(1, 3)];
        if (src[0] !== "{" || !name || src[3] !== "|") return;
        const end = src.indexOf("}", 4), nl = src.indexOf("\n", 4);
        if (end < 5 || (nl >= 0 && nl < end)) return;
        const inner = src.slice(4, end);
        return { type: "color", raw: src.slice(0, end + 1), text: inner, color: name, tokens: this.lexer.inlineTokens(inner) };
      },
      renderer(t) { return `<span class="md-c" data-c="${t.color}">${this.parser.parseInline(t.tokens)}</span>`; },
    },
    { // -# 작은 글씨: 줄 맨 앞, 공백 필요
      name: "subtext", level: "block",
      start(src) { const e = src.indexOf("\n\n"), i = (e < 0 ? src : src.slice(0, e)).search(/\n {0,3}-# /); return i < 0 ? undefined : i; },
      tokenizer(src) {
        const m = /^ {0,3}-# +([^\n]*)(?:\n|$)/.exec(src);
        if (!m || !m[1].trim()) return;
        const tok = { type: "subtext", raw: m[0], text: m[1].trim(), tokens: [] };
        this.lexer.inline(tok.text, tok.tokens);
        return tok;
      },
      renderer(t) { return `<p class="md-sub">${this.parser.parseInline(t.tokens)}</p>\n`; },
    },
    { // >>> 문서 끝까지 한 인용(> 한 줄 인용은 marked 기본)
      name: "bigquote", level: "block",
      start(src) { const e = src.indexOf("\n\n"), i = (e < 0 ? src : src.slice(0, e)).search(/\n {0,3}>>>[ \t]/); return i < 0 ? undefined : i; },
      tokenizer(src) {
        const m = /^ {0,3}>>>[ \t]+/.exec(src);
        if (!m || inBigQuote || !src.slice(m[0].length).trim()) return;
        const { lexer } = this, top = lexer.state.top;
        inBigQuote = true; lexer.state.top = true;
        try { return { type: "blockquote", raw: src, text: src.slice(m[0].length), tokens: lexer.blockTokens(src.slice(m[0].length), []) }; }
        finally { inBigQuote = false; lexer.state.top = top; }
      },
    },
  ],
  tokenizer: {
    html: none, tag: none, lheading: none, // 원시 HTML과 밑줄 줄(===, ---) 제목은 글자 그대로
    heading(src) { // 제목은 # ## ### 만: 그 이상은 글자 그대로의 문단
      const m = /^ {0,3}(#{4,6})(?=\s|$)(.*)(?:\n+|$)/.exec(src);
      if (!m) return false;
      const text = m[0].replace(/\n+$/, "").trim();
      return { type: "paragraph", raw: m[0], text, tokens: this.lexer.inline(text) };
    },
  },
});

// marked의 짝 없는 강조(* _ ~~)·링크 처리는 한 문단(빈 줄 사이 덩어리) 안에서 글 길이의 제곱에 가깝게 느려진다(node+jsdom 실측: 6000자 한 문단 최악 약 0.3~1초).
// 문단이 길면 보는 모두의 화면이 멈추므로 ① 한 블록이 LIMIT자를 넘으면 그 블록만 잘라 그리고(블록이 모두 짧으면 전체가 길어도 자르지 않는다)
// ② 문단별 비용 추정(서식 기호 덩어리 수 x 글자 수)의 합이 BUDGET을 넘게 되는 블록부터는 서식 없이 글 그대로 보여 준다.
const LIMIT = 6000;
const BUDGET = 2e7; // 실측 비용은 대략 5e-8~1.5e-7초 x 추정치(느린 상태 기준 최대 약 3초). 6000자 이하 한 블록(덩어리 최대 3000 x 6000 = 1.8e7)은 항상 이 안이라 짧은 글은 검사를 건너뛴다
const DELIM = /[*_~`[<|{]+/g; // 연속한 서식 기호 하나를 한 덩어리로 센다(**a 는 1개)
const FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
// 코드 펜스 상태를 한 줄 진행한다: 열려 있으면 그 표시(```·~~~), 아니면 null. 펜스 안의 빈 줄은 블록을 나누지 않는다
const step = (fence, line) => {
  const m = FENCE.exec(line);
  if (!fence) return m && !(m[1][0] === "`" && m[2].includes("`")) ? m[1] : null; // 한 줄 안에서 닫히는 ```x```는 펜스가 아니다
  return m && m[1][0] === fence[0] && m[1].length >= fence.length && !m[2].trim() ? null : fence;
};
const openFence = (lines) => lines.reduce(step, null);
const cutLine = (s, limit) => s.slice(0, limit).replace(/[\uD800-\uDBFF]$/, ""); // 이모지 반쪽은 뺀다
const esc = (t) => t.replace(/[&<>"']/g, (c) => "&#" + c.charCodeAt(0) + ";");

// 긴 블록은 줄 경계(줄이 하나뿐이면 글자 경계)에서 자르고 열린 코드 펜스를 닫는다. 안내·글 그대로 보일 블록은 자리표시(token)로 바꿔 두고
// subs[i] = [html, 글]에 담는다: 자리표시는 렌더마다 새로 뽑은 영숫자라 글이 미리 적어 둘 수 없고, 안내 html은 상수다
function prepare(text, limit, token, note) {
  const out = [], subs = [];
  let block = [], size = 0, fence = null, spent = 0;
  const hold = (html, plain) => `${token}q${subs.push([html, plain]) - 1}q`;
  const flush = () => {
    if (!block.length) return;
    let kept = block, clipped = size > limit;
    if (clipped) {
      kept = []; let n = 0;
      for (const l of block) { const w = l.length + (kept.length ? 1 : 0); if (n + w > limit) break; kept.push(l); n += w; }
      if (!kept.length) kept = [cutLine(block[0], limit)];
    }
    const body = kept.join("\n"), r = (body.match(DELIM) || []).length;
    if (spent + r * body.length > BUDGET) out.push(hold(`<pre class="md-fallback">${esc(body)}</pre>`, body));
    else { spent += r * body.length; out.push(...kept); const open = clipped && openFence(kept); if (open) out.push(open); }
    if (clipped) out.push("", hold(`<p class="md-clip">${note}</p>`, note));
    block = []; size = 0;
  };
  for (const line of text.split("\n")) {
    if (!fence && !line.trim()) { flush(); out.push(line); continue; }
    fence = step(fence, line);
    size += line.length + (block.length ? 1 : 0); block.push(line);
  }
  flush();
  return { src: out.join("\n"), subs };
}

// breaks: 메모는 줄 단위로 쓰므로 줄바꿈 한 번도 줄바꿈으로 보인다
const parse = (text) => DOMPurify.sanitize(marked.parse(text, { gfm: true, breaks: true, async: false }), OPTIONS);
const render = (input, limit = LIMIT) => {
  const text = String(input);
  if (text.length <= limit) { // 짧은 글: 한 블록이 limit 이하라 자르지도, 비용을 따지지도 않는다
    try { return parse(text); } catch { return '<pre class="md-fallback">' + esc(text) + "</pre>"; }
  }
  const token = "EVASCLIP" + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
  const note = `이 문단은 길어서 앞부분 ${limit}자까지만 미리보기에 표시합니다. 전체는 편집 화면에서 볼 수 있습니다.`;
  const { src, subs } = prepare(text, limit, token, note);
  const slot = new RegExp(`(?:<p>)?${token}q(\\d+)q(?:</p>)?`, "g");
  try { return parse(src).replace(slot, (_, i) => subs[i][0]); }
  catch { return '<pre class="md-fallback">' + esc(src.replace(slot, (_, i) => subs[i][1])) + "</pre>"; } // 깊게 중첩된 > · 1. 는 marked가 호출 깊이를 넘는다: 글 그대로 보여 준다
};

window.EvasMarkdown = { render, LIMIT };
