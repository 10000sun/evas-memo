// node tools/test-markdown.mjs — 미리보기 무해화(markdown.bundle.js)와 커서 색 배정(color.js)을 확인한다. 실패하면 종료 코드 1
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

// 번들을 브라우저처럼 jsdom 창 안에서 실행한다(DOMPurify가 DOM을 쓴다)
const { window } = new JSDOM("", { runScripts: "outside-only" });
window.eval(readFileSync(new URL("../static/vendor/markdown.bundle.js", import.meta.url), "utf8"));
const render = (t) => window.EvasMarkdown.render(t);

for (const bad of [
  "<script>alert(1)</script>",
  "<img src=x onerror=alert(1)>",
  "[x](javascript:alert(1))",
  '<a href="javascript:alert(1)">x</a>',
  '<a href="JaVaScRiPt:alert(1)">x</a>',
  "[x](data:text/html,<script>alert(1)</script>)",
  '<iframe src="https://example.com"></iframe>',
  '<svg onload="alert(1)"></svg>',
]) {
  const out = render(bad);
  assert.doesNotMatch(out, /<script|onerror|onload|javascript:|data:text|<iframe/i, `${bad} -> ${out}`);
}
assert.match(render("**굵게**"), /<strong>굵게<\/strong>/);
assert.match(render("- [ ] 할 일"), /<input(?=[^>]*type="checkbox")(?=[^>]*disabled)[^>]*>/);
assert.match(render("3. 셋\n4. 넷"), /<ol start="3">/); // 번호가 3부터면 그대로
assert.match(render("1. 가\n    1. 하위\n    - [ ] 할 일\n2. 나"), /<ol>\s*<li>가\s*<ol>\s*<li>하위<\/li>\s*<\/ol>\s*<ul>\s*<li><input[^>]*disabled[^>]*> 할 일<\/li>/);
assert.match(render("| a | b |\n|---|---|\n| 1 | 2 |"), /<table>/);
assert.match(render("[a](https://example.com)"), /<a href="https:\/\/example.com"(?=[^>]*target="_blank")(?=[^>]*rel="noopener noreferrer")/);
assert.match(render("[m](mailto:a@b.co)"), /href="mailto:a@b.co"/);
// 그냥 적은 주소도 링크가 되고, 링크는 모두 새 탭 + noopener noreferrer
const links = render("https://example.com 와 [링크](https://a.com) [나쁜](javascript:alert(1))");
const anchors = links.match(/<a [^>]*href=[^>]*>/g) || []; // javascript: 링크는 href가 지워져 이동할 곳이 없다
assert.equal(anchors.length, 2, links);
for (const a of anchors) assert.match(a, /(?=.*target="_blank")(?=.*rel="noopener noreferrer")/, a);
assert.match(links, /<a href="https:\/\/example.com"/);
assert.match(links, /<a href="https:\/\/a.com"/);
assert.doesNotMatch(links, /javascript:/);
assert.doesNotMatch(render("[f](ftp://example.com)"), /href=/); // 허용 스킴은 http/https/mailto뿐
// 다른 사람의 원시 HTML이 화면 전체를 덮거나(style) 앱의 id를 가로채거나(id) 입력을 받지(form) 못한다
const raw = render('<style>body{display:none}</style><p style="position:fixed" id="e-meta">x</p><form><input type="text"></form>');
assert.doesNotMatch(raw, /<style|style=|id="e-meta"|<form|<input/); // input은 할 일 체크박스만 남는다
// 미리보기 글자를 눌러 앱 버튼(삭제·로그아웃)이 눌리지 않게(for), 다른 폼 속성도 없게
const labels = render('<label for="e-del">눌러</label><label for="logout">x</label><img src="a.png" form="f" formaction="https://e.com">');
assert.doesNotMatch(labels, /\sfor=|\sform=|formaction/, labels);
// 외부 이미지 빈틈: input type=image, table·td background
const bg = render('<input type="image" src="https://e.com/a.png"><table background="https://e.com/b.png"><tr><td background="https://e.com/c.png">x</td></tr></table>');
assert.doesNotMatch(bg, /<input|background|e\.com/, bg);
assert.equal(render(""), "");
// href가 있는 요소는 태그와 무관하게 새 탭(SVG <a>·<area>로 앱 탭을 외부 사이트로 바꾸지 못하게)
for (const bad of [
  '<svg><a href="https://evil.com"><text>x</text></a></svg>',
  '<svg><a xlink:href="https://evil.com"><text>x</text></a></svg>',
  '<map name="m"><area href="https://evil.com" shape="rect" coords="0,0,9,9"></map><img usemap="#m" src="https://e.com/a.png">',
]) {
  const out = render(bad);
  for (const tag of out.match(/<[^>]*href=[^>]*>/gi) || []) assert.match(tag, /(?=.*target="_blank")(?=.*rel="noopener noreferrer")/, `${bad} -> ${out}`);
  assert.doesNotMatch(out, /<svg|<area|xlink/i, `${bad} -> ${out}`);
}
// 외부 이미지는 Referer 없이, 영상·소리는 막는다
assert.match(render("![a](https://e.com/a.png)"), /<img(?=[^>]*referrerpolicy="no-referrer")/);
assert.doesNotMatch(render('<video src="https://e.com/v.mp4"><source src="https://e.com/v.mp4"><track src="x"></video><audio src="https://e.com/a.mp3"></audio>'), /<video|<audio|<source|<track/);
// 주소 규칙: 한글 조사·끝 문장부호·짝 없는 닫는 괄호는 주소가 아니고, 짝이 맞는 괄호는 주소다
const hrefOf = (t) => (render(t).match(/href="([^"]*)"/) || [])[1];
assert.equal(hrefOf("https://drive.google.com/xyz에 있어요"), "https://drive.google.com/xyz");
assert.equal(hrefOf("주소(https://a.com/x), 그리고"), "https://a.com/x");
assert.equal(hrefOf("https://a.com/x. 끝"), "https://a.com/x");
assert.equal(hrefOf("https://en.wikipedia.org/wiki/Foo_(bar) 문서"), "https://en.wikipedia.org/wiki/Foo_(bar)");
assert.equal(hrefOf("https:// 없음"), undefined); // 스킴만 있으면 링크 아님(https://한글.kr 같은 한글 도메인은 주소로 본다)
assert.equal(hrefOf("www.naver.com에 있어요"), "http://www.naver.com");
assert.equal(hrefOf("https://a.com/?a=1&b=2"), "https://a.com/?a=1&amp;b=2");
assert.equal(hrefOf("a@b.co 로 메일"), "mailto:a@b.co"); // http(s) 밖의 자동 링크(메일)는 marked 기본 그대로
const { findUrls } = await import("./url-rule.mjs"); // 에디터(↗·Ctrl+클릭)도 같은 규칙
assert.deepEqual([...findUrls("x https://drive.google.com/xyz에 [d](https://a.com/(y)) https://", 10)].map((u) => [u.from, u.url]),
  [[12, "https://drive.google.com/xyz"], [46, "https://a.com/(y)"]]);
// 한글이 든 주소: 끝 한글 덩어리가 영숫자·_·-·) 바로 뒤면 조사로 떼고, 구분 문자 뒤면 주소의 일부로 둔다
const urlOf = (t) => [...findUrls(t)].map((u) => u.url);
for (const [text, want] of [
  ["https://drive.google.com/xyz에서 봐요", "https://drive.google.com/xyz"],
  ["https://drive.google.com/xyz에", "https://drive.google.com/xyz"],
  ["https://a.com/a_b-에요", "https://a.com/a_b-"],
  ["(https://a.com/x)에서", "https://a.com/x"],
  ["https://en.wikipedia.org/wiki/Foo_(bar)에서", "https://en.wikipedia.org/wiki/Foo_(bar)"],
  ["https://ko.wikipedia.org/wiki/한글 문서", "https://ko.wikipedia.org/wiki/한글"],
  ["https://ko.wikipedia.org/wiki/한글.", "https://ko.wikipedia.org/wiki/한글"],
  ["https://a.com/search?q=한글 로", "https://a.com/search?q=한글"],
  ["https://a.com/doc#제목", "https://a.com/doc#제목"],
  ["https://a.com/s?q=한글&page=2에서", "https://a.com/s?q=한글&page=2"],
  ["https://a.com/한글/abc 끝", "https://a.com/한글/abc"],
]) {
  assert.deepEqual(urlOf(text), [want], text);
  assert.equal(hrefOf(text), encodeURI(want).replace(/&/g, "&amp;"), text); // 미리보기 자동 링크도 같은 규칙
}
// 붙여 넣은 아주 긴 주소·괄호에도 멈추지 않는다(선형). 에디터 장식과 미리보기 모두
for (const text of ["https://a.com/" + ")".repeat(100000), "https://a.com/" + "(".repeat(100000), "https://a.com/" + "(a)".repeat(30000),
  ")".repeat(100000), "https://a.com/x" + "가".repeat(100000), "https://a.com/" + "a가".repeat(50000)]) {
  let t0 = performance.now();
  [...findUrls(text)];
  const f = performance.now() - t0;
  t0 = performance.now();
  render(text);
  const r = performance.now() - t0;
  assert.ok(f < 1000 && r < 1000, `${text.slice(0, 20)}… findUrls ${f.toFixed(0)}ms, render ${r.toFixed(0)}ms`);
}

// 커서 색: 같은 색을 쓰는 3명이 서로의 상태를 보며 돌아가며 배정하면 모두 다른 색이 되고, 그 뒤로는 바뀌지 않는다
const { assignDistinctColor } = createRequire(import.meta.url)("../static/color.js");
const PALETTE = ["#a", "#b", "#c", "#d"];
const states = new Map([3, 1, 2].map((id) => [id, { user: { name: "u" + id, color: "#a", colorLight: "#a33" } }]));
let sets = 0;
const aw = (clientID) => ({
  clientID,
  getStates: () => states,
  getLocalState: () => states.get(clientID),
  setLocalStateField(k, v) { sets++; states.set(clientID, { ...states.get(clientID), [k]: v }); },
});
for (let round = 0; round < 3; round++) for (const id of [3, 1, 2]) assignDistinctColor(aw(id), "#a", PALETTE);
const colors = [...states.values()].map((s) => s.user.color);
assert.equal(new Set(colors).size, 3, colors.join());
assert.equal(states.get(1).user.color, "#a"); // clientID가 가장 작은 사람은 선호 색을 지킨다
assert.equal(states.get(2).user.colorLight, states.get(2).user.color + "33");
const before = sets;
for (const id of [1, 2, 3]) assignDistinctColor(aw(id), "#a", PALETTE);
assert.equal(sets, before); // 이미 안 겹치면 바꾸지 않는다(깜빡임 없음)
console.log("ok");
