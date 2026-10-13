// static/memolink.js 단위 테스트: node --test tests/memolink.test.js (pytest의 test_static.py가 같이 돌린다)
const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const M = require(path.join(__dirname, "..", "static", "memolink.js"));

const MEMO = "https://memo.example.com", CAL = "https://cal.example.com";
const B = { event: CAL, memo: MEMO };
const links = (text, bases = B) => M.parse(text, bases).filter((x) => typeof x !== "string");

test("만든 링크를 다시 읽으면 원래 제목·id·종류가 나온다(이스케이프 왕복)", () => {
  const title = "<img src=x onerror=alert(1)> ] ( test \\ [끝]";
  const text = "앞 " + M.make(title, MEMO, 12) + " 가운데 " + M.make(title, CAL, 3, "event") + " 뒤";
  assert.strictEqual(M.make("a]b", MEMO, 1), "[@a\\]b](https://memo.example.com/?memo=1)");
  assert.strictEqual(M.make("a(b)", CAL, 2, "event"), "[@a\\(b\\)](https://cal.example.com/?event=2)");
  assert.deepStrictEqual(M.parse(text, B), [
    "앞 ", { kind: "memo", id: "12", title, url: MEMO + "/?memo=12" },
    " 가운데 ", { kind: "event", id: "3", title, url: CAL + "/?event=3" }, " 뒤"]);
});

test("제목은 200자까지 자르고, 자른 링크도 다시 읽힌다", () => {
  const long = "가".repeat(250), esc = "]".repeat(250), emoji = "a".repeat(199) + "😀";
  assert.strictEqual(links(M.make(long, MEMO, 1))[0].title, "가".repeat(200));
  assert.strictEqual(links(M.make(esc, MEMO, 1))[0].title, "]".repeat(200)); // 이스케이프로 길어져도 읽힌다
  assert.strictEqual(links(M.make(emoji, MEMO, 1))[0].title, "a".repeat(199)); // 이모지 반쪽은 버린다
});

test("앱 주소로 정확히 시작하고 ?<종류>=<숫자>인 것만 링크", () => {
  for (const url of [
    "https://memo.example.com.evil.com/?memo=1",
    "https://memo.example.com@evil.com/?memo=1",
    "https://memo.example.com/?memo=1x",
    "https://memo.example.com/?memo=",
    "https://memo.example.com/?event=1", // 메모 주소에 일정 종류
    "https://cal.example.com/?memo=1", // 캘린더 주소에 메모 종류
    "https://cal.example.com/x?event=1",
    "https://evil.com/?memo=1",
    "javascript:alert(1)",
  ]) assert.deepStrictEqual(links(`[@t](${url})`), [], url);
  assert.strictEqual(links(`[@t](${MEMO}/?memo=7)`).length, 1);
  assert.strictEqual(links(`[@t](${CAL}/?event=7)`)[0].kind, "event");
  assert.strictEqual(links(`[t](${MEMO}/?memo=7)`).length, 0); // @ 없는 링크는 태그가 아니다
});

test("id 앞의 0은 떼어 서버 id와 맞춘다(0 하나는 그대로)", () => {
  assert.strictEqual(links(`[@t](${MEMO}/?memo=007)`)[0].id, "7");
  assert.strictEqual(links(`[@t](${CAL}/?event=0042)`)[0].id, "42");
  assert.strictEqual(links(`[@t](${MEMO}/?memo=0)`)[0].id, "0");
  assert.strictEqual(links(`[@t](${MEMO}/?memo=000)`)[0].id, "0");
  assert.strictEqual(links(`[@t](${MEMO}/?memo=12345678901234567890)`)[0].id, "12345678901234567890"); // 큰 수도 글자 그대로(정밀도 손실 없음)
});

test("앱 주소가 http(s)가 아니면 그 종류는 링크로 보지 않는다", () => {
  for (const base of ["", null, undefined, "javascript:alert(1)", "memo.example.com", "https://a b"]) {
    assert.strictEqual(M.base(base), "");
    assert.deepStrictEqual(M.parse(`[@t](${base}/?memo=1)`, { memo: base }), [`[@t](${base}/?memo=1)`]);
  }
  assert.strictEqual(links(`[@t](${CAL}/?event=1)`, { event: null, memo: MEMO }).length, 0);
});

test("닫히지 않은 [@가 많아도 1초 안에 끝난다", () => {
  for (const s of [
    "[@".repeat(100000),
    "[@a\\]".repeat(100000),
    "[@" + "a".repeat(100000),
    `[@a](${MEMO}/?memo=`.repeat(20000),
  ]) {
    const t = Date.now();
    M.parse(s, B);
    const ms = Date.now() - t;
    assert.ok(ms < 1000, `${s.slice(0, 12)}… ${ms}ms`);
  }
});

test("딥링크 id: 앞의 0을 떼고, 아스키 숫자 1~18자리만 받는다", () => {
  for (const [s, want] of [["7", "7"], ["007", "7"], ["0", "0"], ["000", "0"], ["10", "10"], ["9".repeat(18), "9".repeat(18)], ["0".repeat(17) + "5", "5"]])
    assert.strictEqual(M.deepId(s), want, s);
  for (const s of ["", "a", "1a", "-1", "1.5", " 7", "7\n", "٧", "９", "9".repeat(19), null, undefined])
    assert.strictEqual(M.deepId(s), "", String(s)); // 아랍·전각 숫자, 너무 긴 값, 숫자가 아닌 값은 무시
  assert.strictEqual(links(M.make("x", MEMO, "007"))[0].id, "7"); // 칩 링크는 #007 이든 #7 이든 같은 id
});

test("사람 태그 [@이름](user:id): 만들고 읽으면 이름·id가 돌아오고, 앱 주소가 없어도 읽힌다", () => {
  const name = "홍 [길]동 \ <b>", id = "123456789012345678";
  for (const bases of [B, {}]) {
    const got = links(M.make(name, "", id, "user"), bases);
    assert.deepStrictEqual(got.map((x) => [x.kind, x.id, x.title]), [["user", id, name]]);
  }
  // 위험한 값은 사람 태그로 읽지 않는다: 공백·괄호·스킴 섞인 id, 너무 긴 id
  for (const bad of ["user:a b", "user:a/b", "user:javascript:1", "user:" + "1".repeat(41), "user:"])
    assert.deepStrictEqual(links(`[@x](${bad})`), [], bad);
  // 일정·메모 링크와 한 글에 섞여도 각각 읽힌다
  const mixed = links(M.make("회의", CAL, 3, "event") + M.make("사람", "", "u1", "user") + M.make("메모", MEMO, 9, "memo"));
  assert.deepStrictEqual(mixed.map((x) => x.kind), ["event", "user", "memo"]);
});
