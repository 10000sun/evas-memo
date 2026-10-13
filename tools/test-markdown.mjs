// node tools/test-markdown.mjs — 미리보기 무해화(markdown.bundle.js)와 커서 색 배정(color.js)을 확인한다. 실패하면 종료 코드 1
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

// 번들을 브라우저처럼 jsdom 창 안에서 실행한다(DOMPurify가 DOM을 쓴다)
const { window } = new JSDOM("", { runScripts: "outside-only" });
window.eval(readFileSync(new URL("../static/vendor/markdown.bundle.js", import.meta.url), "utf8"));
const render = (t) => window.EvasMarkdown.render(t);
// 원시 HTML은 글자 그대로 보이므로 "<script"가 이스케이프된 글로 남는 것은 괜찮다: 결과를 DOM으로 읽어 위험한 요소·속성이 없는지 본다
const dom = (html) => { const d = window.document.createElement("div"); d.innerHTML = html; return d; };
const assertSafe = (html, msg = "") => {
  const d = dom(html);
  assert.equal(d.querySelector("script,iframe,svg,style,form,area,video,audio,source,track,input:not([type=checkbox])"), null, `${msg} -> ${html}`);
  for (const el of d.querySelectorAll("*")) {
    for (const a of el.attributes) {
      assert.ok(!/^on|^(?:style|id|for|form|formaction|background)$/i.test(a.name), `${msg} ${a.name} -> ${html}`);
      assert.ok(!/^(?:href|src|xlink:href)$/i.test(a.name) || !/^\s*(?:javascript|data):/i.test(a.value), `${msg} ${a.name} -> ${html}`);
    }
  }
};

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
  assertSafe(render(bad), bad);
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
assertSafe(raw); // 원시 HTML은 글자일 뿐
// 미리보기 글자를 눌러 앱 버튼(삭제·로그아웃)이 눌리지 않게(for), 다른 폼 속성도 없게
const labels = render('<label for="e-del">눌러</label><label for="logout">x</label><img src="a.png" form="f" formaction="https://e.com">');
assertSafe(labels);
// 외부 이미지 빈틈: input type=image, table·td background
const bg = render('<input type="image" src="https://e.com/a.png"><table background="https://e.com/b.png"><tr><td background="https://e.com/c.png">x</td></tr></table>');
assertSafe(bg);
assert.equal(dom(bg).querySelector("input,table,img"), null);
assert.equal(render(""), "");
// href가 있는 요소는 태그와 무관하게 새 탭(SVG <a>·<area>로 앱 탭을 외부 사이트로 바꾸지 못하게)
for (const bad of [
  '<svg><a href="https://evil.com"><text>x</text></a></svg>',
  '<svg><a xlink:href="https://evil.com"><text>x</text></a></svg>',
  '<map name="m"><area href="https://evil.com" shape="rect" coords="0,0,9,9"></map><img usemap="#m" src="https://e.com/a.png">',
]) {
  const out = render(bad);
  for (const tag of out.match(/<[^>]*href=[^>]*>/gi) || []) assert.match(tag, /(?=.*target="_blank")(?=.*rel="noopener noreferrer")/, `${bad} -> ${out}`);
  assertSafe(out, bad);
  assert.equal(dom(out).querySelector("area,svg"), null, out); // 글자일 뿐(주소만 일반 링크)
}
// 외부 이미지는 Referer 없이, 영상·소리는 막는다
assert.match(render("![a](https://e.com/a.png)"), /<img(?=[^>]*referrerpolicy="no-referrer")/);
assertSafe(render('<video src="https://e.com/v.mp4"><source src="https://e.com/v.mp4"><track src="x"></video><audio src="https://e.com/a.mp3"></audio>'));
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
  ["https://www.naver.com/에서 봐요", "https://www.naver.com/"], // 호스트 뒤 / 하나뿐이면 한글은 문장
  ["https://www.naver.com/wiki/한글", "https://www.naver.com/wiki/한글"],
  ["https://a.com/x에서~", "https://a.com/x"], // ~도 끝 문장부호
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
// 버려지는 주소 후보가 많은 긴 메모도 미리보기가 멈추지 않는다(토크나이저가 남은 글 전체를 훑지 않음)
assert.equal(hrefOf("www.naver.com/에서"), "http://www.naver.com/");
const timeRender = (t) => { const t0 = performance.now(); render(t); return performance.now() - t0; };
for (const unit of ["https://. ", "https://, ", "https:// ", "www. "]) {
  const ms = timeRender(unit.repeat(2e4));
  assert.ok(ms < 1000, `${JSON.stringify(unit)}x2e4 render ${ms.toFixed(0)}ms`);
}
// 진짜 링크 2만 개는 jsdom의 DOMPurify가 <a> 2만 개를 만드는 데만 1초 안팎이 든다(브라우저는 훨씬 빠름).
// 그래서 여기서는 선형인지(2배 입력에 3배 미만)만 본다
const ms1 = timeRender("https://a.com/ ".repeat(1e4)), ms2 = timeRender("https://a.com/ ".repeat(2e4));
assert.ok(ms2 < 3 * ms1 + 100 && ms2 < 5000, `링크 1e4 ${ms1.toFixed(0)}ms, 2e4 ${ms2.toFixed(0)}ms`);

// 긴 메모: 한 블록(빈 줄 사이 덩어리; 코드 펜스 안의 빈 줄은 한 블록)이 LIMIT자를 넘으면 그 블록만 잘라 그 자리에 안내를 붙이고,
// 블록이 모두 짧으면 전체가 10만 자여도 자르지 않는다. 느린 입력(짝 없는 강조)이 여러 블록이어도 비용 안전장치가 총 시간을 묶는다
const { LIMIT } = window.EvasMarkdown;
const NOTE = `이 문단은 길어서 앞부분 ${LIMIT}자까지만 미리보기에 표시합니다. 전체는 편집 화면에서 볼 수 있습니다.`;
const count = (s, sub) => s.split(sub).length - 1;
const timed = (text) => { const t0 = performance.now(); const out = render(text); return [out, performance.now() - t0]; };
// 한 문단이 10만 자: 앞 LIMIT자만 그리고 안내 한 번, 1.5초 안(깊은 중첩 `> `·`1. `는 던지지 않고 글 그대로)
for (const unit of ["*abc ", "_a ", "**a ", "*~>*", "*a ", "[a ", "`a ", "<a ", "> ", "- ", "1. ", "*", "__a ", "||a ", "{빨강|a ", "-# ", ">>> ", "#### "]) {
  const [out, ms] = timed(unit.repeat(Math.ceil(100000 / unit.length)));
  assert.ok(ms < 1500, `${JSON.stringify(unit)} 한 문단 10만 자 ${ms.toFixed(0)}ms`);
  assert.equal(count(out, NOTE), 1, JSON.stringify(unit));
}
// 가장 느린 문단(6000자)을 16개 이어 붙인 10만 자: 블록 수에 따라 늘어나도 비용 안전장치가 있어 수 초 안(측정 최대 약 3초)
for (const unit of ["*abc ", "_a ", "**a ", "*~>*", "__# "]) {
  const block = unit.repeat(Math.ceil(LIMIT / unit.length)).slice(0, LIMIT);
  const [out, ms] = timed(Array(16).fill(block).join("\n\n"));
  assert.ok(ms < 8000, `${JSON.stringify(unit)} x16 ${ms.toFixed(0)}ms`);
  assert.ok(out.includes("md-fallback"), `${JSON.stringify(unit)}: 뒤쪽 블록은 글 그대로`);
  assert.doesNotMatch(out, /<script/i);
}
// 짧은 블록만 있는 긴 문서는 자르지 않는다(안전장치도 걸리지 않는다)
const prose = Array.from({ length: 2500 }, (_, i) => `문단 ${i}: **굵게** 와 [링크](https://a.com/${i}) 그리고 \`코드\` 와 _기울임_ 이 섞인 보통 글입니다.`).join("\n\n");
assert.ok(prose.length > 100000 - 50000);
const [proseOut, proseMs] = timed(prose);
assert.equal(count(proseOut, "<p>"), 2500);
assert.ok(!proseOut.includes("md-clip") && !proseOut.includes("md-fallback"), "짧은 블록은 자르지 않는다");
assert.ok(proseMs < 8000, `보통 글 ${proseMs.toFixed(0)}ms`);
const exact = "가".repeat(LIMIT); // 딱 LIMIT자인 블록도 자르지 않는다
assert.ok(!render(exact + "\n\n" + exact).includes("md-clip"));
// 긴 블록 하나만 잘리고 앞뒤 짧은 블록은 그대로
const lines = Array.from({ length: 2000 }, (_, i) => `줄 ${i} **굵게**`).join("\n");
const mixed = render("앞 문단\n\n" + lines + "\n\n뒤 문단");
assert.ok(mixed.includes("앞 문단") && mixed.includes("뒤 문단"));
assert.equal(count(mixed, NOTE), 1);
assert.ok(mixed.indexOf(NOTE) < mixed.indexOf("뒤 문단") && mixed.indexOf(NOTE) > mixed.indexOf("앞 문단"), "안내는 잘린 자리");
const lastLine = [...mixed.matchAll(/줄 (\d+) <strong>굵게<\/strong>/g)].pop();
assert.ok(lastLine && +lastLine[1] > 100 && +lastLine[1] < 1999, "앞부분은 보이고 뒷부분은 없다");
assert.ok(!mixed.includes("**"), "줄 경계에서 자른다(줄 중간에서 자르지 않는다)");
// 코드 펜스 안의 빈 줄은 블록을 나누지 않는다: 펜스 전체가 LIMIT를 넘으면 한 번 잘리고 안내는 코드 밖, 넘지 않으면 그대로
const fenced = render("```\n" + "코드 줄\n\n".repeat(1500) + "```\n\n뒤");
assert.equal(count(fenced, "<pre>"), 1);
assert.ok(/<\/pre>\s*<p class="md-clip">이 문단은/.test(fenced) && fenced.includes("뒤") && !/<pre>[^]*이 문단은[^]*<\/pre>/.test(fenced), "안내는 코드 블록 밖");
assert.ok(!render("```\n" + "가\n\n".repeat(1500) + "```\n\n" + "나".repeat(100)).includes("md-clip")); // 4500자 펜스: 안 자른다
const small = render("```\na\n\nb\n```\n\n끝");
assert.ok(small.includes("a\n\nb\n</code></pre>") && !small.includes("md-clip"));
const twoGroups = render("```\n" + "가".repeat(4000) + "\n\n" + "나".repeat(4000) + "\n```"); // 빈 줄로 나뉘어도 한 블록이라 8000자 -> 잘림
assert.equal(count(twoGroups, NOTE), 1);
assert.ok(!twoGroups.includes("나"), "펜스 뒷부분은 잘려 나간다");
// 안내 문구에 글이 끼어들지 않는다: 글 속의 같은 문구·HTML은 무해화되고, 자리표시처럼 보이는 글도 그대로 글자다
const inj = render("<script>alert(1)</script><img src=x onerror=alert(1)>\nEVASCLIPq0q " + NOTE + "\n" + "가".repeat(LIMIT * 2));
assertSafe(inj);
assert.equal(count(inj, NOTE), 2); // 글 속 문구 하나 + 진짜 안내 하나
assert.ok(inj.includes("EVASCLIPq0q"));
// 한 줄이 아주 긴 블록은 글자 경계에서 자르되 이모지(서로게이트 쌍)를 반으로 가르지 않는다
for (const pad of ["", "a"]) {
  const emoji = render(pad + "😀".repeat(LIMIT));
  assert.doesNotMatch(emoji, /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/);
  assert.equal(count(emoji, NOTE), 1);
}
// 깊게 중첩돼 marked가 호출 깊이를 넘어도 던지지 않고 글 그대로(HTML 아님) 보여 준다
const deep = render("> ".repeat(2900) + "<b>x</b>");
assert.ok(deep.includes("md-fallback") && !deep.includes("<b>"), "깊은 중첩은 글 그대로");

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
// 사람 태그 [@이름](user:id)는 링크가 아니라 이름 칩(span)으로. 이름에 HTML이 들어 있어도 무해화된다
{
  const out = render("안녕 [@홍길동](user:123456789012345678) 와 [@<img src=x onerror=alert(1)>](user:u1) 그리고 [x](user:a b)");
  assert.match(out, /<span class="md-user">@홍길동<\/span>/);
  assertSafe(out); assert.doesNotMatch(out, /href="user:/i);
  assert.match(render("[링크](https://a.com)"), /href="https:\/\/a\.com"/); // 일반 링크는 그대로
}
assert.match(render("[링크](https://a.com)"), /title="클릭하면 새 탭에서 열립니다"/); // 미리보기 링크에 올리면 여는 방법 안내
assert.equal(dom(render('<a href="https://a.com" title="내 제목">x</a>')).querySelector("a[title=\"내 제목\"]"), null); // 원시 HTML은 지원하지 않는다: 글자로 보인다

// ---- 디스코드식 문법 ----
const has = (t, re) => assert.match(render(t), re, t);
const lacks = (t, re) => assert.doesNotMatch(render(t), re, t);
// 1. __밑줄__ (굵게가 아니다), 조합, 단어 안/스네이크 케이스는 그대로
has("__밑줄__", /<p><u>밑줄<\/u><\/p>/);
lacks("__밑줄__", /<strong>/);
has("__**굵은 밑줄**__", /<u><strong>굵은 밑줄<\/strong><\/u>/);
has("__*기울인 밑줄*__", /<u><em>기울인 밑줄<\/em><\/u>/);
has("***굵고 기울임***", /<em><strong>굵고 기울임<\/strong><\/em>|<strong><em>굵고 기울임<\/em><\/strong>/);
has("**굵게 __밑줄__**", /<strong>굵게 <u>밑줄<\/u><\/strong>/);
has("__밑줄__은 한글 조사가 붙어도", /<u>밑줄<\/u>은/);
for (const t of ["snake__case__word", "my_var_name", "a__b", "__", "____", "__ __", "\\_\\_not\\_\\_"]) lacks(t, /<u>/);
has("snake_case_name", /snake_case_name/);
lacks("__a\n\nb__", /<u>/); // 빈 줄을 넘지 않는다
// 2. ||스포일러||
has("||비밀||", /<span class="md-spoiler" tabindex="0">비밀<\/span>/);
has("||**굵게** 와 `코드` 와 __밑줄__||", /<span class="md-spoiler" tabindex="0"><strong>굵게<\/strong> 와 <code>코드<\/code> 와 <u>밑줄<\/u><\/span>/);
has("앞 ||a|| 중간 ||b|| 뒤", /앞 <span[^>]*>a<\/span> 중간 <span[^>]*>b<\/span> 뒤/);
lacks("||a\n\nb||", /md-spoiler/);
lacks("||||", /md-spoiler/);
// 7. 이스케이프
has("\\|\\|스포일러 아님\\|\\|", /<p>\|\|스포일러 아님\|\|<\/p>/);
has("\\_\\_밑줄 아님\\_\\_", /<p>__밑줄 아님__<\/p>/);
has("\\*별\\* \\~물결\\~ \\` \\\\", /<p>\*별\* ~물결~ ` \\<\/p>/);
lacks("\\*별\\*", /<em>/);
// 3. -# 작은 글씨
has("-# 작은 글씨", /<p class="md-sub">작은 글씨<\/p>/);
has("-# 작은 **굵게** _기울임_", /<p class="md-sub">작은 <strong>굵게<\/strong> <em>기울임<\/em><\/p>/);
has("본문\n-# 작은", /<p>본문<\/p>\s*<p class="md-sub">작은<\/p>/);
lacks("-#없음", /md-sub/);
lacks("-# ", /md-sub/);
// 4. >>> 문서 끝까지 한 인용, > 는 기존대로
{
  const out = render("앞\n>>> 첫째\n둘째\n\n셋째 **굵게**\n\n- 목록");
  assert.equal(count(out, "<blockquote>"), 1, out);
  assert.match(out, /<p>앞<\/p>\s*<blockquote>\s*<p>첫째<br>둘째<\/p>\s*<p>셋째 <strong>굵게<\/strong><\/p>\s*<ul>\s*<li>목록<\/li>\s*<\/ul>\s*<\/blockquote>/);
  assert.match(render("> 한 줄\n\n뒤"), /<blockquote>\s*<p>한 줄<\/p>\s*<\/blockquote>\s*<p>뒤<\/p>/);
}
// 5. 제목은 # ## ### 만
{
  const out = render("# 하나\n## 둘\n### 셋\n#### 넷\n##### 다섯\n###### 여섯\n####");
  for (const [n, t] of [[1, "하나"], [2, "둘"], [3, "셋"]]) assert.match(out, new RegExp(`<h${n}>${t}</h${n}>`), out);
  assert.doesNotMatch(out, /<h[456]>/);
  for (const t of ["#### 넷", "##### 다섯", "###### 여섯"]) assert.match(out, new RegExp(`<p>${t}</p>`), out);
  has("####", /<p>####<\/p>/);
  has("#### 넷 **굵게**", /<p>#### 넷 <strong>굵게<\/strong><\/p>/);
  has("#태그", /<p>#태그<\/p>/);
  lacks("제목\n===", /<h1>/); // 밑줄 줄 제목은 글자
}
// 6. 원시 HTML은 글자 그대로(이스케이프). 그 밖의 문법은 그대로 동작
{
  assert.match(render("<b>x</b>"), /<p>&lt;b&gt;x&lt;\/b&gt;<\/p>/);
  assert.equal(dom(render("<b>x</b> <div>y</div>\n\n<div>z</div>\n\n<!-- c -->")).querySelector("b,div"), null);
  assert.equal(dom(render("<img src=x onerror=alert(1)> <script>alert(1)</script>")).querySelector("img,script,[onerror]"), null);
  assert.match(render("<https://a.com>"), /<a href="https:\/\/a\.com"/); // <주소> 자동 링크는 남는다
  assert.match(render("```js\nconst a = 1;\n```"), /<pre><code class="language-js">/);
  assert.match(render("a\nb"), /a<br>b/); // 줄바꿈 한 번도 줄바꿈
  assert.match(render("---"), /<hr>/);
  assert.match(render("~~지움~~"), /<del>지움<\/del>/);
}
// 글자 색 {이름|글자}: 이름 8개, 같은 줄의 첫 } 까지, 안쪽 서식은 그대로, 모르는 이름·줄바꿈 넘김·코드 안은 적용 안 함
for (const [ko, en] of Object.entries({ 빨강: "red", 주황: "orange", 노랑: "yellow", 초록: "green", 파랑: "blue", 보라: "purple", 분홍: "pink", 회색: "gray" })) {
  has(`{${ko}|글자}`, new RegExp(`<p><span class="md-c" data-c="${en}">글자</span></p>`));
}
has("{빨강|**굵게** __밑줄__ ||숨김||}", /<span class="md-c" data-c="red"><strong>굵게<\/strong> <u>밑줄<\/u> <span class="md-spoiler"[^>]*>숨김<\/span><\/span>/);
has("{파랑|a} 와 {초록|b}", /data-c="blue">a<\/span> 와 <span class="md-c" data-c="green">b<\/span>/);
has("**{보라|굵은 보라}**", /<strong><span class="md-c" data-c="purple">굵은 보라<\/span><\/strong>/);
for (const t of ["{가나|글자}", "{빨강|글자", "{빨강|}", "{빨강|a\nb}", "{빨강|a\n\nb}", "`{빨강|글자}`", "```\n{빨강|글자}\n```", "{빨강}", "{ 빨강|글자}", "\\{빨강|글자}"]) lacks(t, /md-c/);
has("{가나|글자}", /\{가나\|글자\}/);
assertSafe(render("{빨강|<img src=x onerror=alert(1)>}"));
assert.ok(!/style=/.test(render("{빨강|글자}")), "style 속성은 쓰지 않는다");
// 악의적인 긴 입력(각 1초 안): 기호만 반복하거나 짝이 안 맞는 열기만 반복
for (const unit of ["__", "||", "{", "{빨강|", "{빨강|a", "__a", "||a", "__a__b", "||a|||", "_|", "-# ", ">>> ", "#### ", "{빨강|__||", "__ **a "]) {
  const [, ms] = timed(unit.repeat(Math.ceil(1e5 / unit.length)));
  assert.ok(ms < 1000, `${JSON.stringify(unit)} x1e5 ${ms.toFixed(0)}ms`);
}
// 같은 문단에 짝 없는 열기 수백 개 + 줄바꿈이 섞여도 시간이 제곱으로 늘지 않는다
for (const unit of ["__a ", "||a ", "{빨강|a\n", "__a\n", "||a\n"]) {
  const ms1 = timed(unit.repeat(500))[1], ms2 = timed(unit.repeat(1000))[1];
  assert.ok(ms2 < 4 * ms1 + 200 && ms2 < 1000, `${JSON.stringify(unit)} 500회 ${ms1.toFixed(0)}ms, 1000회 ${ms2.toFixed(0)}ms`);
}
// 변환 결과는 class·data-c·tabindex만 남기고 DOMPurify를 통과한다(style 등은 여전히 금지)
{
  const out = dom(render("||a|| {분홍|b}"));
  assert.ok(out.querySelector('span.md-spoiler[tabindex="0"]') && out.querySelector('span.md-c[data-c="pink"]'));
  assertSafe(render('||<span style="x" id="e-meta" onclick="a()">x</span>||'));
}
console.log("ok");
