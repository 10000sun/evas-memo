const $ = (id) => document.getElementById(id);
async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { "content-type": "application/json" } });
  // 로그인이 안 된 상태면 디스코드 로그인으로 보낸다
  if (r.status === 401) { location.href = "/auth/login"; return new Promise(() => {}); }
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join(", ") : `오류 ${r.status}`);
  }
  return r.status === 204 ? null : r.json();
}

// 화면 아래에 잠깐 떴다 사라지는 안내
function toast(text) {
  let t = $("toast");
  if (!t) document.body.append(t = Object.assign(document.createElement("div"), { id: "toast", role: "status" }));
  t.textContent = text; t.classList.add("on");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("on"), 4000);
}

// 내보내기: 휴대폰 공유창(아이폰 메모·안드로이드 메모앱) -> 안 되면 클립보드 -> 그것도 막히면 .txt 다운로드.
// 공유창을 사용자가 닫으면(AbortError) 아무것도 하지 않고 null로 끝난다
async function exportMemo(title, text) {
  if (navigator.share) {
    try { await navigator.share({ title, text }); return "shared"; }
    catch (e) { if (e.name === "AbortError") return null; }
  }
  try { await navigator.clipboard.writeText(title + "\n\n" + text); return "copied"; }
  catch { /* http 주소·권한 거부 등: 파일로 대신한다 */ }
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(new Blob([title + "\n\n" + text], { type: "text/plain;charset=utf-8" })),
    download: (title.replace(/[\\/:*?"<>|]/g, "_") || "메모") + ".txt",
  });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  return "downloaded";
}
const EXPORTED = { shared: "공유창을 열었습니다", copied: "복사했습니다", downloaded: "파일로 저장했습니다" };

// 다크/라이트 전환. 고른 적이 없으면 기기 설정을 따른다(색은 style.css의 변수가 바꾼다)
const SVG = (d) => `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const MOON = SVG('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>');
const SUN = SVG('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>');
const isDark = () => (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
(function initTheme() {
  const b = $("theme");
  if (!b) return;
  const paint = () => {
    b.innerHTML = isDark() ? SUN : MOON;
    b.setAttribute("aria-label", isDark() ? "라이트 모드로 바꾸기" : "다크 모드로 바꾸기");
    b.title = b.getAttribute("aria-label");
  };
  b.onclick = () => {
    const t = isDark() ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("theme", t); } catch { /* 저장이 막혀도 이번 화면에서는 바뀐다 */ }
    paint();
  };
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paint);
  paint();
})();
