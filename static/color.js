// 사용자가 적은 색(#3b5bdb, 3b5bdb, #fff, rgb(59, 91, 219), 59,91,219)을 "#rrggbb"로 바꾼다. 틀리면 null
function parseColor(text) {
  const s = String(text).trim();
  let m = s.match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (m) {
    const h = m[1].length === 3 ? [...m[1]].map((c) => c + c).join("") : m[1];
    return "#" + h.toLowerCase();
  }
  m = s.match(/^(?:rgb\(\s*)?(\d{1,3})\s*[,\s]\s*(\d{1,3})\s*[,\s]\s*(\d{1,3})\s*\)?$/i);
  if (!m || /^rgb\(/i.test(s) !== /\)$/.test(s)) return null; // 괄호는 열고 닫는 짝이 맞아야 한다
  const rgb = m.slice(1, 4).map(Number);
  return rgb.some((n) => n > 255) ? null : "#" + rgb.map((n) => n.toString(16).padStart(2, "0")).join("");
}
// 같이 편집하는 사람끼리 커서 색이 겹치지 않게 한다(awareness change마다 부른다). 같은 색을 쓰는 다른 접속자 중
// clientID가 내 것보다 작은 사람이 있으면 내가 아무도 안 쓰는 첫 색으로 옮긴다. 작은 쪽은 그대로라 서로 번갈아 바뀌지 않고,
// 안 겹치면 아무것도 바꾸지 않는다(깜빡임 방지)
function assignDistinctColor(awareness, myPreferred, palette) {
  const mine = awareness.getLocalState()?.user;
  if (!mine) return;
  const color = mine.color || myPreferred, used = new Set();
  let clash = false;
  for (const [id, s] of awareness.getStates()) {
    if (id === awareness.clientID || !s.user) continue;
    used.add(s.user.color);
    if (s.user.color === color && id < awareness.clientID) clash = true;
  }
  const free = clash && palette.find((c) => !used.has(c));
  if (free) awareness.setLocalStateField("user", { ...mine, color: free, colorLight: free + "33" }); // 빈 색이 없으면 겹침을 받아들인다
}
if (typeof module !== "undefined") module.exports = { parseColor, assignDistinctColor };
