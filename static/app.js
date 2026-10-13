// 목록(개인|공동 탭·분류 필터·검색)과 편집 화면. 주소의 #번호가 열린 메모라 휴대폰 뒤로 가기로 목록에 돌아온다
let cats = [], me = null, memos = [], shown = new Set(); // shown: 범례에서 고른 분류(비어 있으면 전체)
let tab = "shared", cur = null, ed = null, openReq = 0, titleTimer = null, deleting = false, focusTitle = false;
try { tab = localStorage.getItem("tab") || tab; } catch { /* 저장이 막혀 있으면 공동 탭부터 */ }
const saveTab = () => { try { localStorage.setItem("tab", tab); } catch { /* 이번 화면에서만 기억 */ } };
const canEdit = () => me && me.role !== "viewer";
const canEditMemo = (m) => m.kind === "personal" || canEdit(); // 서버 ws.can_edit와 같은 규칙
const catOf = (id) => cats.find((c) => c.id === id);
// 서버는 시간대 없는 서버 현지 시각(한국)으로 저장한다 -> 그대로 현지 시각으로 읽는다
const when = (iso) => new Date(iso).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
const el = (tag, props = {}, ...kids) => {
  const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n;
};
// 같이 쓰는 사람의 커서 색. 사용자 id마다 선호 색이 있고, 같이 접속한 사람과 겹치면 assignDistinctColor가 빈 색으로 바꾼다.
// 흰 이름표 글자·라이트·다크 배경 모두와 명암비 3.3 이상(에디터가 #rrggbb + 투명도 두 자리를 붙여 쓴다)
const PEER = ["#e03131", "#c2255c", "#ae3ec9", "#7048e8", "#4263eb", "#1c7ed6", "#0c8599", "#099268", "#2f9e44", "#5c940d", "#e8590c", "#b35c00"];
const colorOf = (id) => PEER[[...String(id)].reduce((h, c) => (h * 31 + c.codePointAt(0)) >>> 0, 0) % PEER.length];
const status = (t) => ($("e-status").textContent = t);
// 편집 | 미리보기. 미리보기는 무해화한 HTML(EvasMarkdown)이고 본문이 바뀌면(다른 사람 입력 포함) 잠깐 뒤 다시 그린다
let mode = "edit", previewTimer;
const renderPreview = () => { if (ed && mode === "preview") $("e-preview").innerHTML = EvasMarkdown.render(ed.view.state.doc.toString()); };
function setMode(m) {
  mode = m;
  for (const b of document.querySelectorAll("[data-mode]")) b.setAttribute("aria-pressed", b.dataset.mode === m);
  $("e-body").hidden = m === "preview"; $("e-preview").hidden = m !== "preview";
  renderPreview();
}
for (const b of document.querySelectorAll("[data-mode]")) b.onclick = () => setMode(b.dataset.mode);

// --- 목록 ---
let listReq = 0;
async function refreshList() {
  if (cur) return refreshCur();
  if ($("list-view").hidden) return;
  const n = ++listReq, q = $("search").value.trim(); // n: 늦게 온 옛 응답이 새 결과를 덮지 않게
  let rows;
  try { rows = await api(`/api/memos?kind=${tab}` + (q ? "&q=" + encodeURIComponent(q) : "")); }
  catch (e) { if (n === listReq) toast("목록을 불러오지 못했습니다: " + e.message); return; }
  if (n !== listReq) return;
  memos = rows;
  renderList();
}

function card(m) {
  const c = catOf(m.category_id);
  const a = el("a", { href: "#" + m.id, className: "memo" },
    el("strong", { textContent: m.title || "제목 없음" }),
    el("p", { className: "preview", textContent: m.body_text }),
    el("div", { className: "meta" },
      ...(c ? [el("i", { className: "dot", style: `background:${c.color}` }), c.name + " · "] : []),
      `${m.updated_name || "알 수 없음"} · ${when(m.updated_at)}`));
  if (c) a.style.borderLeftColor = c.color;
  return el("li", {}, a);
}

function renderList() {
  const list = memos.filter((m) => !shown.size || shown.has(m.category_id));
  const empty = shown.size || $("search").value.trim() ? "조건에 맞는 메모가 없습니다"
    : tab === "personal" ? "개인 메모가 없습니다. + 메모로 새로 만드세요." : "공동 메모가 없습니다.";
  $("memos").replaceChildren(...(list.length ? list.map(card) : [el("li", { className: "empty", textContent: empty })]));
}

function syncTabs() {
  for (const b of document.querySelectorAll("[data-tab]")) b.setAttribute("aria-pressed", b.dataset.tab === tab);
}
for (const b of document.querySelectorAll("[data-tab]")) b.onclick = () => {
  tab = b.dataset.tab; saveTab(); syncTabs(); memos = []; renderList(); refreshList();
};
let searchTimer;
$("search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(refreshList, 250); };

$("add").onclick = async () => {
  try {
    const m = await api("/api/memos", { method: "POST", body: JSON.stringify({
      kind: cur ? cur.kind : tab, category_id: shown.size === 1 ? [...shown][0] : null }) }); // 분류 하나로 거르고 있으면 그 분류로
    focusTitle = true;
    location.hash = m.id;
  } catch (e) { toast(e.message); }
};

// --- 편집 ---
async function put(fields, keepalive = false) {
  const id = cur.id;
  status("저장 중…");
  try {
    const m = await api(`/api/memos/${id}`, { method: "PUT", body: JSON.stringify(fields), keepalive });
    if (cur && cur.id === id) { cur = m; paintMemo(); status("저장됨"); }
  } catch (e) { if (cur && cur.id === id) status("저장하지 못했습니다: " + e.message); }
}
// 제목은 잠깐 멈추면 저장한다(마지막 저장이 이김). 화면을 떠날 때는 기다리지 않고 바로 저장한다
async function saveTitle(keepalive) {
  if (!titleTimer || !cur) return;
  clearTimeout(titleTimer); titleTimer = null;
  await put({ title: $("e-title").value }, keepalive);
}
$("e-title").oninput = () => { status("저장 중…"); clearTimeout(titleTimer); titleTimer = setTimeout(saveTitle, 700); };
$("e-cat").onchange = () => put({ category_id: $("e-cat").value ? +$("e-cat").value : null });
addEventListener("pagehide", () => saveTitle(true));

function paintMemo() {
  const m = cur, shared = m.kind === "shared";
  $("e-kind").textContent = shared ? "공동 메모" : "개인 메모";
  $("e-kind").classList.toggle("shared", shared);
  $("e-move").hidden = shared || !canEdit(); // 공동으로 옮기기는 편집자 이상(서버 규칙)
  $("e-copy").hidden = !shared;
  $("e-del").hidden = shared && !canEdit(); // 공동 메모는 작성자·관리자만 지워진다: 아니면 서버가 이유를 알려준다
  $("e-meta").textContent = `작성 ${m.created_name || "알 수 없음"} · 마지막 수정 ${m.updated_name || "알 수 없음"} (${when(m.updated_at)})`;
}

function fillForm() {
  if (!titleTimer && document.activeElement !== $("e-title")) $("e-title").value = cur.title;
  $("e-cat").value = cur.category_id ?? "";
  paintMemo();
}

// 20초 주기: 다른 사람이 바꾼 제목·분류를 편집 중인 화면에도 반영한다(본문은 실시간 연결이 맞춘다)
async function refreshCur() {
  const id = cur.id;
  try { const m = await api(`/api/memos/${id}`); if (cur && cur.id === id) { cur = m; fillForm(); } }
  catch { /* 지워졌으면 실시간 연결이 알려준다 */ }
}

async function openMemo(id) {
  const n = ++openReq;
  let m;
  try { m = await api(`/api/memos/${id}`); } catch { if (n === openReq) leave("메모가 없거나 볼 수 없습니다"); return; }
  if (n !== openReq) return;
  cur = m; tab = m.kind; saveTab(); syncTabs();
  $("e-cat").replaceChildren(new Option("미분류", ""), ...cats.map((c) => new Option(c.name, c.id)));
  $("e-title").value = m.title;
  fillForm();
  const editable = canEditMemo(m);
  $("e-title").disabled = $("e-cat").disabled = !editable;
  $("e-body").inert = !editable; // 보기 전용: 서버가 편집을 버리므로 입력 자체를 막는다
  ed = EvasEditor.create({ parent: $("e-body"), memoId: id, user: { name: me.name, color: colorOf(me.id) } });
  watch(ed, id);
  if (focusTitle) $("e-title").focus();
  focusTitle = false;
}

function watch(e, id) {
  const p = e.provider, aw = e.awareness;
  let idle;
  status("연결 중…");
  p.on("status", ({ status: s }) => ed === e && s !== "connected" && status(s === "connecting" ? "연결 중…" : "연결 끊김 · 다시 연결되면 저장됩니다"));
  p.on("sync", (ok) => ed === e && ok && status("저장됨"));
  p.doc.on("update", (_u, origin) => {
    if (ed !== e) return;
    clearTimeout(previewTimer); previewTimer = setTimeout(renderPreview, 200);
    if (origin === p) return; // origin === p: 서버에서 받은 변경
    if (!p.wsconnected) return status("연결 끊김 · 다시 연결되면 저장됩니다");
    // 서버는 받은 편집을 2초 안에 저장한다(ws.SAVE_DELAY). 확인 응답은 없어 입력이 멎고 3초 뒤 저장됨으로 본다
    status("저장 중…"); clearTimeout(idle);
    idle = setTimeout(() => ed === e && p.wsconnected && status("저장됨"), 3000);
  });
  aw.on("change", () => {
    if (ed !== e) return;
    assignDistinctColor(aw, colorOf(me.id), PEER);
    const names = new Set();
    for (const [client, s] of aw.getStates()) if (client !== aw.clientID && s.user) names.add(s.user.name);
    $("e-peers").textContent = names.size ? "같이 보는 사람: " + [...names].join(", ") : "";
  });
  p.on("connection-close", (ev) => {
    if (ed !== e) return; // 내가 닫은 연결
    const code = ev && ev.code;
    if (code === 4404) return leave(deleting ? "삭제했습니다" : "메모가 삭제되었습니다");
    if (code === 1009) {
      // 넘친 편집은 서버가 버렸다. 그대로 두면 다시 연결할 때마다 같은 편집을 보내 또 끊기므로 서버 내용으로 다시 연다
      toast("본문은 100,000자까지입니다. 넘친 입력은 저장되지 않았습니다");
      return route(); // 주소는 그대로라 같은 메모를 다시 연다
    }
    if (code === 1008 || code === 1003 || code >= 4000) return leave("이 메모를 볼 권한이 없습니다");
    // 그 밖(네트워크 끊김·서버 재시작)은 에디터가 알아서 다시 연결한다.
    // 서버의 접속 거절(권한 없음·지워짐)은 브라우저에 1006으로만 보여 API로 확인한다
    fetch(`/api/memos/${id}`).then((r) => {
      if (ed !== e) return;
      if (r.status === 401) location.href = "/auth/login";
      else if (r.status === 404) leave("메모가 삭제되었거나 볼 수 없습니다");
    }, () => { /* 아직 오프라인 */ });
  });
}

async function closeMemo() {
  ++openReq;
  await saveTitle();
  if (ed) { const e = ed; ed = null; e.destroy(); }
  cur = null; deleting = false;
  clearTimeout(previewTimer); setMode("edit");
  $("e-body").replaceChildren(); $("e-preview").replaceChildren(); $("e-peers").textContent = ""; status("");
}

function leave(text) {
  if (text) toast(text);
  if (location.hash) location.hash = ""; else route();
}

$("e-export").onclick = async () => {
  // 공유창은 누른 직후에만 열리므로 기다리는 일 없이 바로 부른다. 본문은 에디터의 지금 내용
  const r = await exportMemo($("e-title").value.trim() || "제목 없음", ed ? ed.view.state.doc.toString() : "");
  if (r) toast(EXPORTED[r]);
};
$("e-move").onclick = async () => {
  if (!confirm("이 메모를 공동 메모로 옮길까요?\n모든 사람에게 보입니다. 개인 메모에는 남지 않습니다.")) return;
  await saveTitle();
  try {
    cur = await api(`/api/memos/${cur.id}/share`, { method: "POST" });
    tab = "shared"; saveTab(); syncTabs(); paintMemo();
    toast("공동 메모로 옮겼습니다");
  } catch (e) { toast(e.message); }
};
$("e-copy").onclick = async () => {
  if (!confirm("이 공동 메모를 내 개인 메모로 복사할까요?\n원본 공동 메모는 그대로 남고, 사본은 나만 봅니다.")) return;
  await saveTitle();
  try {
    const m = await api(`/api/memos/${cur.id}/copy-to-personal`, { method: "POST" });
    toast("개인 메모로 복사했습니다. 사본을 엽니다");
    location.hash = m.id;
  } catch (e) { toast(e.message); }
};
$("e-del").onclick = async () => {
  if (!confirm(cur.kind === "shared" ? "이 공동 메모를 삭제할까요?\n모든 사람에게서 사라지고 되돌릴 수 없습니다." : "이 메모를 삭제할까요?\n되돌릴 수 없습니다.")) return;
  clearTimeout(titleTimer); titleTimer = null; // 지울 메모의 제목은 저장하지 않는다
  deleting = true;
  try { await api(`/api/memos/${cur.id}`, { method: "DELETE" }); leave("삭제했습니다"); }
  catch (e) { deleting = false; toast(e.message); }
};

// --- 화면 전환 ---
// 한 번에 하나씩 순서대로 처리한다: 제목 저장(네트워크)을 기다리는 사이 다음 전환이 끼어들면
// 서로의 에디터를 닫거나 옛 주소의 메모를 여는 일이 생긴다. 주소는 닫기가 끝난 뒤에 읽는다
let routing = Promise.resolve();
const route = () => (routing = routing.then(routeNow, routeNow));
async function routeNow() {
  await closeMemo();
  const id = parseInt(location.hash.slice(1), 10);
  $("list-view").hidden = !!id; $("edit-view").hidden = !id;
  if (id) openMemo(id); else refreshList();
}
addEventListener("hashchange", route);

$("help").onclick = () => $("help-dlg").showModal();
$("help-close").onclick = () => $("help-dlg").close();
$("help-dlg").onclick = (e) => { if (e.target === $("help-dlg")) $("help-dlg").close(); }; // 바깥을 누르면 닫힘
$("refresh").onclick = () => location.reload(); // 홈 화면에 설치한 앱에는 브라우저 새로고침이 없고, 새 배포 코드도 함께 받는다

async function start() {
  try {
    [me, cats] = await Promise.all([api("/api/me"), api("/api/categories")]);
  } catch (e) {
    $("msg").hidden = false; $("msg").textContent = "불러오지 못했습니다: " + e.message;
    return;
  }
  initBell();
  $("add").hidden = !canEdit();
  $("admin-link").hidden = me.role !== "admin";
  $("who").textContent = me.name;
  $("logout").hidden = false;
  $("logout").onclick = () => fetch("/auth/logout", { method: "POST" }).then(() => location.reload());
  const chips = cats.map((c) => {
    const s = el("button", { type: "button" }, el("i", { style: `background:${c.color}` }), c.name);
    s.setAttribute("aria-pressed", "false");
    s.onclick = () => { shown.has(c.id) ? shown.delete(c.id) : shown.add(c.id); syncLegend(); };
    return s;
  });
  // 고른 분류를 한 번에 푸는 버튼. 고른 게 있을 때만 보인다
  const reset = el("button", { type: "button", className: "reset", textContent: "필터 해제", hidden: true });
  reset.onclick = () => { shown.clear(); syncLegend(); };
  function syncLegend() {
    chips.forEach((b, i) => b.setAttribute("aria-pressed", shown.has(cats[i].id)));
    $("legend").classList.toggle("filtering", shown.size > 0);
    reset.hidden = !shown.size;
    renderList();
  }
  $("legend").replaceChildren(...chips, reset);
  syncTabs();
  route();
}
start();
