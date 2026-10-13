// 알림: 종 아이콘, 변경 내역 팝업, 폰·브라우저 푸시 구독
const KIND = { add: "작성", edit: "수정", delete: "삭제" };

const noteRow = (n) => {
  const li = document.createElement("li"), who = document.createElement("div"), what = document.createElement("div");
  li.className = n.unread ? "unread" : "";
  who.textContent = `${n.actor_name}님이 공동 메모를 ${KIND[n.kind]}했습니다`;
  what.className = "meta";
  what.textContent = `${n.title || "제목 없음"} · ${when(n.at)}`;
  li.append(who, what);
  return li;
};

let lastRev = null;
async function refreshBell() {
  try {
    const { items, unread, rev } = await api("/api/activity");
    // 공동 메모가 바뀌었으면 목록을 새로 받는다(첫 호출은 기준만 잡는다). 개인 메모는 rev에 안 잡혀 개인 탭이면 늘 받는다
    // 폴더 변경은 rev에 안 잡혀 폴더 목록은 매번 받는다(보던 폴더가 지워졌으면 refreshFolders가 전체로 돌리고 목록도 새로 받는다)
    if (lastRev !== null && (rev !== lastRev || !KINDS[tab].inRev)) refreshList();
    else if (lastRev !== null) refreshFolders().then((gone) => gone && refreshList());
    lastRev = rev;
    $("bell-dot").hidden = !unread;
    $("bell").setAttribute("aria-label", unread ? `알림, 안 읽음 ${unread}개` : "알림");
    $("n-readall").disabled = !unread;
    $("n-list").replaceChildren(...(items.length ? items.map(noteRow)
      : [Object.assign(document.createElement("li"), { className: "empty", textContent: "아직 변경 내역이 없습니다" })]));
  } catch { /* 네트워크가 잠깐 끊겨도 다음 주기에 다시 시도한다 */ }
}

// --- 폰·브라우저 푸시 ---
const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
const installed = navigator.standalone || matchMedia("(display-mode: standalone)").matches;
const pushSupported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const keyBytes = (b64) => Uint8Array.from(atob(b64.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(b64.length / 4) * 4, "=")), (c) => c.charCodeAt(0));
const subscription = async () => (await navigator.serviceWorker.ready).pushManager.getSubscription();

async function showPushState() {
  const btn = $("n-push"), hint = $("n-hint");
  btn.hidden = true; hint.hidden = true;
  if (!pushSupported) {
    // 아이폰 Safari는 홈 화면에 추가한 앱에서만 푸시를 지원한다
    if (isIos && !installed) { hint.hidden = false; hint.textContent = "아이폰에서 알림을 받으려면 Safari 공유 버튼 → ‘홈 화면에 추가’로 설치한 앱에서 여세요."; }
    return;
  }
  let key;
  try { key = (await api("/api/push/key")).key; } catch { return; }
  if (!key) return; // 서버에 푸시 설정이 없다
  if (Notification.permission === "denied") { hint.hidden = false; hint.textContent = "이 기기에서 알림이 차단되어 있습니다. 브라우저·기기 설정에서 허용해 주세요."; return; }
  btn.hidden = false;
  btn.textContent = (await subscription()) ? "이 기기 알림 끄기" : "이 기기 알림 켜기";
}

async function togglePush() {
  const btn = $("n-push");
  btn.disabled = true;
  try {
    const sub = await subscription();
    if (sub) {
      await api("/api/push/unsubscribe", { method: "POST", body: JSON.stringify(sub.toJSON()) });
      await sub.unsubscribe();
    } else {
      // 허용 창은 버튼을 누른 직후에만 뜨므로, 네트워크 요청보다 먼저 부른다
      if ((await Notification.requestPermission()) !== "granted") return;
      const { key } = await api("/api/push/key");
      const s = await (await navigator.serviceWorker.ready).pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
      await api("/api/push/subscribe", { method: "POST", body: JSON.stringify(s.toJSON()) });
    }
  } catch (e) { $("n-hint").hidden = false; $("n-hint").textContent = "알림을 바꾸지 못했습니다: " + e.message; }
  finally { btn.disabled = false; await showPushState(); }
}

function initBell() {
  $("bell").hidden = false;
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  $("bell").onclick = () => { refreshBell(); showPushState(); $("notif").showModal(); };
  $("n-close").onclick = () => $("notif").close();
  $("notif").onclick = (e) => { if (e.target === $("notif")) $("notif").close(); }; // 바깥을 누르면 닫힘
  $("n-readall").onclick = async () => { await api("/api/activity/read", { method: "POST" }); refreshBell(); };
  $("n-push").onclick = togglePush;
  refreshBell();
  setInterval(() => { if (!document.hidden) refreshBell(); }, 20000); // shortcut: 20초마다 확인(실시간 연결 아님). 더 빠르게 필요하면 SSE로
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshBell(); });
}
