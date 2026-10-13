// 본문 속 주소 규칙. 에디터(↗·Ctrl+클릭)와 미리보기 자동 링크가 함께 쓴다.
// - 주소 문자: ASCII URL 문자 + 한글. 끝의 문장부호(~ 포함)와 짝 없는 닫는 괄호는 뺀다(짝이 맞는 괄호 Foo_(bar)는 유지)
// - 끝의 한글 덩어리가 영숫자·_·-·) 바로 뒤에서 시작하면 조사·문장(…/xyz에서)이라 떼고,
//   구분 문자(/ = # ? & . 등) 뒤에서 시작하면 주소의 일부(…/wiki/한글, ?q=한글, #제목)로 둔다.
//   단 호스트 바로 뒤 / 하나뿐인 주소의 한글(https://www.naver.com/에서)은 문장이라 뗀다
const HANGUL = "\\u1100-\\u11FF\\u3130-\\u318F\\uAC00-\\uD7A3";
const CHARS = `[A-Za-z0-9\\-._~:/?#@!$&'*+,;=%()${HANGUL}]+`;
const URL_RE = new RegExp(`https?://${CHARS}`, "g");
const URL_AT = new RegExp(`(?:https?://|www\\.)${CHARS}`, "iy"); // 위치 0에서만 맞춰 본다(미리보기 토크나이저용)
const IS_HANGUL = new RegExp(`[${HANGUL}]`);

// 붙여 넣은 아주 긴 주소에도 멈추지 않게 괄호는 한 번만 세고 끝에서부터 한 칸씩 깎는다(선형)
function trimUrl(u) {
  let end = u.length, open = 0, close = 0;
  for (const c of u) if (c === "(") open++; else if (c === ")") close++;
  while (end) {
    const c = u[end - 1];
    if (".,;:!?'*~".includes(c)) end--;
    else if (c === ")" && open < close) { close--; end--; }
    else if (IS_HANGUL.test(c)) {
      let j = end - 1;
      while (j && IS_HANGUL.test(u[j - 1])) j--;
      if (!/[A-Za-z0-9_)\-]/.test(u[j - 1]) && !/^(?:https?:\/\/|www\.)[^/?#]*\/$/i.test(u.slice(0, j))) break;
      end = j;
    } else break;
  }
  return u.slice(0, end);
}
const valid = (u) => /^(?:https?:\/\/.|www\.[^.])/i.test(u);

// text 안의 http(s) 주소들 -> {from, to, url} (from·to는 base를 더한 위치). 스킴만 남는 것은 버린다
export function* findUrls(text, base = 0) {
  for (const m of text.matchAll(URL_RE)) {
    const url = trimUrl(m[0]);
    if (valid(url)) yield { from: base + m.index, to: base + m.index + url.length, url };
  }
}

// src 맨 앞의 http(s)·www. 주소(다듬은 원문) 또는 null. 한 번만 맞춰 보고 뒤를 훑지 않는다
export function urlAtStart(src) {
  URL_AT.lastIndex = 0;
  const m = URL_AT.exec(src);
  const url = m && trimUrl(m[0]);
  return url && valid(url) ? url : null;
}
