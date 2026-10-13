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
assert.match(render("| a | b |\n|---|---|\n| 1 | 2 |"), /<table>/);
assert.match(render("[a](https://example.com)"), /<a href="https:\/\/example.com"(?=[^>]*target="_blank")(?=[^>]*rel="noopener noreferrer")/);
assert.match(render("[m](mailto:a@b.co)"), /href="mailto:a@b.co"/);
// 그냥 적은 주소도 링크가 되고, 링크는 모두 새 탭 + noopener noreferrer
const links = render("https://example.com 와 [링크](https://a.com) [나쁜](javascript:alert(1))");
const anchors = links.match(/<a [^>]*>/g) || [];
assert.equal(anchors.length, 3, links);
for (const a of anchors) assert.match(a, /(?=.*target="_blank")(?=.*rel="noopener noreferrer")/, a);
assert.match(links, /<a href="https:\/\/example.com"/);
assert.match(links, /<a href="https:\/\/a.com"/);
assert.doesNotMatch(links, /javascript:/);
assert.doesNotMatch(render("[f](ftp://example.com)"), /href=/); // 허용 스킴은 http/https/mailto뿐
// 다른 사람의 원시 HTML이 화면 전체를 덮거나(style) 앱의 id를 가로채거나(id) 입력을 받지(form) 못한다
const raw = render('<style>body{display:none}</style><p style="position:fixed" id="e-meta">x</p><form><input type="text"></form>');
assert.doesNotMatch(raw, /<style|style=|id="e-meta"|<form/);
assert.match(raw, /<input[^>]*disabled/);
assert.equal(render(""), "");

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
