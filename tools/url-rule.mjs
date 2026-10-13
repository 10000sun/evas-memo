// 본문 속 http(s) 주소 규칙. 에디터(↗·Ctrl+클릭)와 미리보기 자동 링크가 함께 쓴다.
// 주소는 ASCII URL 문자만이라 한글 조사(…/xyz에)는 들어가지 않고, 끝의 문장부호와 짝 없는 닫는 괄호는 뺀다.
// 짝이 맞는 괄호(위키 주소 Foo_(bar))는 주소로 둔다
const URL_RE = /https?:\/\/[A-Za-z0-9\-._~:/?#@!$&'*+,;=%()]+/g;

function trimUrl(u) {
  for (;;) {
    if (/[.,;:!?'*]$/.test(u)) u = u.slice(0, -1);
    else if (u.endsWith(")") && u.split("(").length < u.split(")").length) u = u.slice(0, -1);
    else return u;
  }
}

// text 안의 주소들 -> {from, to, url} (from·to는 base를 더한 위치). 스킴만 남는 것은 버린다
export function* findUrls(text, base = 0) {
  for (const m of text.matchAll(URL_RE)) {
    const url = trimUrl(m[0]);
    if (/^https?:\/\/./.test(url)) yield { from: base + m.index, to: base + m.index + url.length, url };
  }
}
