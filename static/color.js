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
if (typeof module !== "undefined") module.exports = { parseColor };
