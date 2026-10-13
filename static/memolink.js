// 연동 링크 [@제목](주소) 만들기·찾기. 일정은 CALENDAR_URL/?event=<id>, 메모는 PUBLIC_URL/?memo=<id>.
// 캘린더 레포 static/memolink.js와 같은 규칙(여기는 종류가 event·memo 둘). 브라우저(전역 MemoLink)와 node 테스트(require) 겸용
const MemoLink = (() => {
  // 제목(이스케이프 포함)·주소 길이를 묶어 둬서, 닫히지 않은 "[@"가 수만 번 반복돼도 선형으로 끝난다
  const TAG = /\[@((?:\\.|[^\\\]]){0,200})\]\(([^()\s]{1,500})\)/g;
  // 설정의 앱 주소가 http(s)일 때만 쓴다(아니면 연동 링크를 만들지도, 알아보지도 않는다)
  const base = (url) => (typeof url === "string" && /^https?:\/\/[^\s]+$/.test(url) ? url : "");
  const escape = (title) => title.replace(/[\\[\]()]/g, "\\$&"); // 링크 형식이 깨지지 않게
  // 제목은 200자까지(읽는 쪽 TAG의 상한). 자른 자리가 이모지 반쪽이면 그 반쪽도 뺀다
  const cut = (title) => title.slice(0, 200).replace(/[\uD800-\uDBFF]$/, "");
  const make = (title, url, id, kind = "memo") => `[@${escape(cut(title))}](${url}/?${kind}=${id})`;
  // bases: {종류: 그 앱 주소} 예) {event: 캘린더 주소, memo: 메모 주소}.
  // 글을 [문자열 | {kind, id, title, url}] 조각으로. 주소가 정확히 "<주소>/?<종류>=<숫자>"인 것만 링크, 나머지는 그대로 글자
  function parse(text, bases) {
    const pres = Object.entries(bases).filter(([, u]) => base(u)).map(([k, u]) => [k, u + "/?" + k + "="]);
    const out = [];
    let last = 0;
    for (const m of pres.length ? text.matchAll(TAG) : []) {
      const hit = pres.find(([, p]) => m[2].startsWith(p) && /^\d+$/.test(m[2].slice(p.length)));
      if (!hit) continue;
      // id는 앞의 0을 뗀다(?memo=007 도 7번): 서버 조회 결과(숫자)와 맞춰야 '삭제됨'으로 잘못 보이지 않는다
      const id = m[2].slice(hit[1].length).replace(/^0+(?=\d)/, "");
      out.push(text.slice(last, m.index), { kind: hit[0], id, title: m[1].replace(/\\(.)/g, "$1"), url: m[2] });
      last = m.index + m[0].length;
    }
    out.push(text.slice(last));
    return out.filter((x) => x !== "");
  }
  return { base, escape, make, parse };
})();
if (typeof module !== "undefined") module.exports = MemoLink;
