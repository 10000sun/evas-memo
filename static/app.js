// 목록(개인|공동 탭·분류 필터·검색)과 편집 화면. 주소의 #번호가 열린 메모라 휴대폰 뒤로 가기로 목록에 돌아온다
let cats = [], me = null, memos = [], shown = new Set(); // shown: 범례에서 고른 분류(비어 있으면 전체)
let tab = "shared", cur = null, ed = null, openReq = 0, titleTimer = null, deleting = false, focusTitle = false;
try { tab = localStorage.getItem("tab") || tab; } catch { /* 저장이 막혀 있으면 공동 탭부터 */ }
// 메모 종류별 화면 규칙. 종류가 늘면 여기에 항목 하나를 더한다. 화면의 종류별 판단은 모두 이 표만 본다(서버 규칙과 같게).
// 함수는 (me[, 폴더]) -> bool. scope: 그 종류 본문의 @ 힌트가 부르는 /api/link/memos 범위,
// lookup: 그 종류 본문의 연결 칩이 메모 최신 제목을 물을 때의 범위(내 개인 메모 링크는 어디 있든 내게는 제목이 보인다)
const editor = (u) => !!u && u.role !== "viewer";
const isAdmin = (u) => !!u && u.role === "admin";
const yes = () => true, no = () => false;
const lookupMine = (u) => (isAdmin(u) ? "admin" : "all"); // 관리자에게는 어느 메모에서든 전율 메모 링크의 제목도 보인다
// moves: 편집 화면 'OO로 옮기기' 버튼 {옮길 종류: (me) -> 보일지}. 버튼 글자·확인창 문구는 옮길 종류의 moveLabel·moveNote
const KINDS = {
  personal: {
    label: "개인", name: "개인 메모", empty: "개인 메모가 없습니다. + 메모로 새로 만드세요.", scope: "all", lookup: lookupMine,
    moveLabel: "개인으로 옮기기", moveNote: "나만 볼 수 있게 됩니다(다른 관리자에게도 사라집니다)",
    accent: "", // 편집 화면 종류 표시의 색(style.css .badge.<accent>)
    badge: false, // 메모 카드에 종류 표시. 이 종류의 탭은 기억(localStorage)하지 않는다
    author: true, // 메모 카드에 마지막 수정한 사람 표시
    visible: yes, // 탭을 만들지(아니면 탭 버튼·도움말 항목을 DOM에 만들지 않는다)
    create: editor, // 새 메모(서버 add_memo: 편집자 이상)
    edit: yes, // 제목·분류·폴더·본문 편집(서버 ws.can_edit: 개인은 본인만 보이므로 본인)
    folderCreate: yes, // 폴더 만들기·이름 바꾸기(개인 폴더는 본인 것만 보인다)
    folderDelete: yes,
    moves: { shared: editor, admin: isAdmin }, // 공동으로(서버 /share: 편집자 이상), 전율로(서버 /move: 소유자이면서 관리자)
    toPersonal: no, // '개인으로 복사'
    del: yes, // 삭제 버튼
    delConfirm: "이 메모를 삭제할까요?\n되돌릴 수 없습니다.",
    inRev: false, // /api/activity의 rev에 변경이 잡히는지(안 잡히면 20초마다 목록을 다시 받는다)
  },
  shared: {
    label: "공동", name: "공동 메모", empty: "공동 메모가 없습니다.", scope: "shared", lookup: lookupMine,
    moveLabel: "공동으로 옮기기", moveNote: "모든 사람에게 보입니다",
    accent: "shared", badge: false, author: true, visible: yes, create: editor, edit: editor, folderCreate: editor,
    folderDelete: (u, f) => f.created_by === u.id || u.role === "admin", // 만든 사람·관리자
    moves: { admin: isAdmin }, toPersonal: yes,
    del: editor, // 작성자·관리자만 지워진다: 편집자에게는 보이고 아니면 서버가 이유를 알려준다
    delConfirm: "이 공동 메모를 삭제할까요?\n모든 사람에게서 사라지고 되돌릴 수 없습니다.",
    inRev: true,
  },
  // 전율: 관리자 전원이 보고 고친다(서버는 비관리자에게 종류 자체를 404로 숨긴다). 활동 기록·rev에 없어 20초마다 목록을 받는다
  admin: {
    label: "전율", name: "전율 메모", empty: "전율 메모가 없습니다.", scope: "admin", lookup: () => "admin",
    moveLabel: "전율로 옮기기", moveNote: "관리자만 볼 수 있게 됩니다(공동 메모였다면 다른 사람에게는 사라집니다)",
    accent: "admin", badge: true, author: true, visible: isAdmin, create: isAdmin, edit: isAdmin,
    folderCreate: isAdmin, folderDelete: isAdmin,
    moves: { shared: isAdmin, personal: isAdmin }, toPersonal: no, del: isAdmin,
    delConfirm: "이 전율 메모를 삭제할까요?\n모든 관리자에게서 사라지고 되돌릴 수 없습니다.",
    inRev: false,
  },
};
let conf = {}; // /api/config: 앱 주소들(memo_url·calendar_url)과 캘린더 연동 켜짐(link)
const linkBases = () => ({ event: conf.calendar_url, memo: conf.memo_url }); // MemoLink 종류별 앱 주소
// 딥링크 /?memo=<id> -> #<id>(편집 화면). 새로고침해도 다시 뛰지 않게 쿼리는 지운다
const deep = new URLSearchParams(location.search).get("memo");
if (deep !== null) history.replaceState(null, "", location.pathname + (MemoLink.deepId(deep) ? "#" + MemoLink.deepId(deep) : ""));
if (!KINDS[tab]) tab = "shared";
// 전율 탭(badge)은 기억하지 않는다: 같은 PC를 쓰는 비관리자의 저장소에 흔적을 남기지 않게
const saveTab = () => { try { if (!KINDS[tab].badge) localStorage.setItem("tab", tab); } catch { /* 이번 화면에서만 기억 */ } };
// 탭(종류)이 바뀌면 폴더 선택은 처음(전체)부터
function setTab(k) {
  if (k !== tab) { tab = k; folders = []; fsel = ""; }
  saveTab(); syncTabs();
}
const canEditMemo = (m) => KINDS[m.kind].edit(me); // 서버 ws.can_edit와 같은 규칙
const catOf = (id) => cats.find((c) => c.id === id);
// 폴더 권한은 KINDS의 folderCreate·folderDelete(서버 folders.py와 같은 규칙)
let folders = [], fsel = ""; // folders: 지금 종류의 폴더들. fsel: "" 전체, "none" 폴더 없음, 숫자 = 폴더 id
const canFolder = (kind) => KINDS[kind].folderCreate(me);
const canDelFolder = (f) => KINDS[f.kind].folderDelete(me, f);
const folderOf = (id) => folders.find((f) => f.id === id);
const folderPath = (id) => {
  const f = folderOf(id), p = f && f.parent_id && folderOf(f.parent_id);
  return !f ? "" : p ? `${p.name} / ${f.name}` : f.name;
};
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
  await refreshFolders(); // 보고 있던 폴더가 사라졌으면 여기서 전체로 돌아간다
  if (n !== listReq) return;
  let rows;
  try { rows = await api(`/api/memos?kind=${tab}` + (fsel !== "" ? "&folder_id=" + fsel : "") + (q ? "&q=" + encodeURIComponent(q) : "")); }
  catch (e) {
    // 그 사이 역할이 바뀌어(관리자 강등) 이 탭을 못 쓰게 됐으면 syncMe가 탭을 바꾸고 목록을 다시 받는다
    if (n === listReq && !(await syncMe()) && n === listReq) toast("목록을 불러오지 못했습니다: " + e.message);
    return;
  }
  if (n !== listReq) return;
  memos = rows;
  renderList();
}

function card(m) {
  const c = catOf(m.category_id), k = KINDS[m.kind];
  const a = el("a", { href: "#" + m.id, className: "memo" },
    el("strong", { textContent: m.title || "제목 없음" }),
    el("p", { className: "preview", textContent: m.body_text }),
    ...(folderPath(m.folder_id) ? [el("div", { className: "meta path", textContent: folderPath(m.folder_id) })] : []),
    el("div", { className: "meta" },
      ...(k.badge ? [el("span", { className: "badge " + k.accent, textContent: k.label })] : []),
      ...(c ? [el("i", { className: "dot", style: `background:${c.color}` }), c.name + " · "] : []),
      (k.author ? `${m.updated_name || "알 수 없음"} · ` : "") + when(m.updated_at)));
  if (c) a.style.borderLeftColor = c.color;
  return el("li", {}, a);
}

function renderList() {
  const list = memos.filter((m) => !shown.size || shown.has(m.category_id));
  const empty = shown.size || $("search").value.trim() || fsel !== "" ? "조건에 맞는 메모가 없습니다" : KINDS[tab].empty;
  $("memos").replaceChildren(...(list.length ? list.map(card) : [el("li", { className: "empty", textContent: empty })]));
}

// --- 폴더 ---
let folderReq = 0;
// 지금 종류의 폴더를 다시 받는다. 보던 폴더가 다른 곳에서 지워졌으면 전체로 돌리고 true
async function refreshFolders() {
  const kind = tab, n = ++folderReq; // 편집 중에는 tab이 열린 메모의 종류다
  let rows;
  try { rows = await api(`/api/folders?kind=${kind}`); } catch { return false; } // 다음 주기에 다시
  if (n !== folderReq || kind !== tab) return false;
  folders = rows;
  const gone = typeof fsel === "number" && !folderOf(fsel);
  if (gone) fsel = "";
  paintFolders();
  return gone;
}
function folderBtn(label, pressed, onclick, cls = "") {
  const b = el("button", { type: "button", className: cls, textContent: label, onclick });
  if (pressed != null) b.setAttribute("aria-pressed", pressed);
  return b;
}
function pickFolder(v) { fsel = v; paintFolders(); memos = []; renderList(); refreshList(); }
function paintFolders() {
  const sel = typeof fsel === "number" ? folderOf(fsel) : null;
  const root = sel && (sel.parent_id ? folderOf(sel.parent_id) : sel); // 고른 폴더의 맨 위 폴더
  const make = canFolder(tab);
  $("folders").replaceChildren(
    folderBtn("전체", fsel === "", () => pickFolder("")),
    folderBtn("폴더 없음", fsel === "none", () => pickFolder("none")),
    ...folders.filter((f) => !f.parent_id).map((f) => folderBtn(f.name, f === root, () => pickFolder(f.id))),
    ...(make ? [folderBtn("+ 새 폴더", null, () => newFolder(null), "add")] : []));
  // 맨 위 폴더를 고르면 그 하위 폴더 줄. 하위 폴더 아래로는 만들 수 없어 하위 폴더를 고른 동안에는 + 새 폴더가 없다
  const subs = root ? folders.filter((f) => f.parent_id === root.id) : [];
  const subAdd = make && sel === root && sel;
  $("subfolders").replaceChildren(...subs.map((f) => folderBtn(f.name, f === sel, () => pickFolder(f.id))),
    ...(subAdd ? [folderBtn("+ 새 폴더", null, () => newFolder(root.id), "add")] : []));
  $("subfolders").hidden = !subs.length && !subAdd;
  $("folder-tools").hidden = !sel;
  if (sel) {
    $("folder-name").textContent = folderPath(sel.id);
    $("f-rename").hidden = !canFolder(sel.kind);
    $("f-delete").hidden = !canDelFolder(sel);
  }
  if (cur) paintFolderSelect();
}
async function newFolder(parentId) {
  const name = prompt(parentId ? `'${folderOf(parentId).name}' 안에 만들 하위 폴더 이름 (30자까지)` : "새 폴더 이름 (30자까지)");
  if (!name || !name.trim()) return;
  try {
    const f = await api("/api/folders", { method: "POST", body: JSON.stringify({ kind: tab, name, parent_id: parentId }) });
    pickFolder(f.id);
  } catch (e) { toast(e.message); refreshList(); }
}
$("f-rename").onclick = async () => {
  const f = folderOf(fsel), name = f && prompt("폴더 이름 (30자까지)", f.name);
  if (!name || !name.trim() || name.trim() === f.name) return;
  try { await api(`/api/folders/${f.id}`, { method: "PUT", body: JSON.stringify({ name }) }); }
  catch (e) { toast(e.message); }
  refreshList();
};
$("f-delete").onclick = async () => {
  const f = folderOf(fsel);
  if (!f || !confirm(`'${folderPath(f.id)}' 폴더를 삭제할까요?\n${f.parent_id ? "" : "하위 폴더도 함께 삭제됩니다. "}안의 메모는 '폴더 없음'으로 남습니다.`)) return;
  try { await api(`/api/folders/${f.id}`, { method: "DELETE" }); toast("폴더를 삭제했습니다"); fsel = ""; }
  catch (e) { toast(e.message); }
  refreshList();
};
// 편집 화면의 폴더 선택: 메모와 같은 종류의 폴더만, 하위 폴더는 들여쓰기
// 항목이 바뀐 때만 다시 만든다(20초 갱신이 열려 있는 드롭다운을 닫지 않게)
function paintFolderSelect() {
  const items = [["", "폴더 없음"]];
  for (const f of folders.filter((x) => !x.parent_id)) {
    items.push([String(f.id), f.name]);
    for (const s of folders.filter((x) => x.parent_id === f.id)) items.push([String(s.id), "  └ " + s.name]);
  }
  const sel = $("e-folder"), now = [...sel.options].map((o) => [o.value, o.text]);
  if (JSON.stringify(now) !== JSON.stringify(items)) sel.replaceChildren(...items.map(([v, t]) => new Option(t, v)));
  const v = String(cur.folder_id ?? "");
  if (sel.value !== v) sel.value = v;
}

function syncTabs() {
  for (const b of document.querySelectorAll("[data-tab]")) b.setAttribute("aria-pressed", b.dataset.tab === tab);
  if (me) $("add").hidden = !KINDS[tab].create(me); // 편집 중에는 tab이 열린 메모의 종류
}
function showTab(k) { setTab(k); memos = []; paintFolders(); renderList(); refreshList(); }
$("tabs").onclick = (e) => { const b = e.target.closest("[data-tab]"); if (b) showTab(b.dataset.tab); };
// 역할에 따라 달라지는 화면: 탭 버튼(보이는 종류만 만든다), 관리 링크, 관리자 도움말. 지금 탭을 못 쓰게 됐으면 공동으로
function paintRole() {
  $("tabs").replaceChildren(...Object.entries(KINDS).filter(([, k]) => k.visible(me)).map(([kind, k]) => {
    const b = el("button", { type: "button", textContent: k.label });
    b.dataset.tab = kind;
    return b;
  }));
  $("admin-link").hidden = !isAdmin(me);
  $("help-admin")?.remove(); // 전율 안내는 관리자에게만 DOM에 넣는다
  if (isAdmin(me)) $("help-basic").append(el("li", { id: "help-admin" },
    el("b", { textContent: "전율" }), " 탭은 관리자만 보고 함께 고치는 메모 공간입니다(폴더·분류·검색·미리보기·내보내기는 다른 탭과 같고, 알림·변경 내역에는 남지 않습니다). 편집 화면의 ",
    el("b", { textContent: "전율로 옮기기" }), "로 개인·공동 메모를 전율로, ", el("b", { textContent: "공동으로 옮기기" }), "·",
    el("b", { textContent: "개인으로 옮기기" }), "로 전율 메모를 내보냅니다(복사가 아니라 이동이고 폴더는 '폴더 없음'이 됩니다). 전율 메모 본문의 ",
    el("code", { textContent: "@" }), "는 공동·내 개인·전율 메모를 모두 고를 수 있습니다."));
  const gone = !KINDS[tab].visible(me);
  if (gone) setTab("shared");
  syncTabs();
  return gone;
}
// /api/me를 다시 받아 역할을 반영한다. 지금 탭을 못 쓰게 돼 공동으로 바꿨으면 목록을 다시 받고 true
async function syncMe() {
  try { me = await api("/api/me"); } catch { return false; }
  if (!paintRole()) return false;
  if (!cur) showTab(tab);
  return true;
}
let searchTimer;
$("search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(refreshList, 250); };

$("add").onclick = async () => {
  try {
    const m = await api("/api/memos", { method: "POST", body: JSON.stringify({
      kind: cur ? cur.kind : tab, category_id: shown.size === 1 ? [...shown][0] : null, // 분류 하나로 거르고 있으면 그 분류로
      folder_id: !cur && typeof fsel === "number" ? fsel : null }) }); // 목록에서 폴더를 보고 있으면 그 폴더에
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
$("e-folder").onchange = () => put({ folder_id: $("e-folder").value ? +$("e-folder").value : null }).then(refreshFolders);
addEventListener("pagehide", () => saveTitle(true));

function paintMemo() {
  const m = cur, k = KINDS[m.kind];
  $("e-kind").textContent = k.name;
  $("e-kind").className = "badge " + k.accent;
  // 옮기기 버튼은 보일 것만 만든다(비관리자 화면에는 '전율로 옮기기'가 DOM에도 없다). 같은 목록이면 두어 포커스를 지킨다
  const to = Object.keys(k.moves).filter((t) => k.moves[t](me));
  if ($("e-moves").dataset.to !== to.join()) {
    $("e-moves").dataset.to = to.join();
    $("e-moves").replaceChildren(...to.map((t) => el("button", { type: "button", className: "btn ghost", textContent: KINDS[t].moveLabel, onclick: () => move(t) })));
  }
  $("e-copy").hidden = !k.toPersonal(me);
  $("e-del").hidden = !k.del(me);
  $("e-meta").textContent = `작성 ${m.created_name || "알 수 없음"} · 마지막 수정 ${m.updated_name || "알 수 없음"} (${when(m.updated_at)})`;
}

function fillForm() {
  if (!titleTimer && document.activeElement !== $("e-title")) $("e-title").value = cur.title;
  $("e-cat").value = cur.category_id ?? "";
  paintFolderSelect();
  paintMemo();
}

// 20초 주기: 다른 사람이 바꾼 제목·분류·폴더를 편집 중인 화면에도 반영한다(본문은 실시간 연결이 맞춘다)
async function refreshCur() {
  const id = cur.id;
  refreshFolders();
  paintChips("all"); // 칩의 제목·삭제 여부도 다시 묻는다
  try {
    const m = await api(`/api/memos/${id}`);
    if (cur && cur.id === id) { const moved = m.kind !== cur.kind; cur = m; moved ? kindChanged() : fillForm(); }
  } catch { /* 지워졌거나 못 보게 됐으면 실시간 연결이 알려준다 */ }
}
// 열린 메모의 종류가 바뀜(내가·다른 관리자가 옮김): 탭·폴더·버튼을 새 종류에 맞춘다. 못 고치게 됐으면 목록으로
function kindChanged() {
  if (!canEditMemo(cur)) return leave("이 메모를 고칠 수 없게 되었습니다");
  setTab(cur.kind); fillForm(); refreshFolders(); // 옮기면 폴더는 '폴더 없음'(서버)
}

// --- 일정·메모 연결 ---
// 일정 날짜: 캘린더의 ISO 문자열 그대로(종일이면 날짜만)
const eventDate = (r) => { const s = String(r.start || ""); return s.slice(0, 10) + (r.all_day || s.length < 16 ? "" : " " + s.slice(11, 16)); };
// 에디터 @ 힌트의 목록. 일정은 캘린더 연동이 켜졌을 때만, 메모는 이 메모 종류의 범위에서 자기 자신을 빼고
async function linkSource(kind, q) {
  const m = cur, url = MemoLink.base(linkBases()[kind]);
  if (!m || !url || (kind === "event" && !conf.link)) return [];
  const qs = `q=${encodeURIComponent(q)}&limit=9`; // 9: 자기 자신을 빼도 8개
  const rows = await api(kind === "event" ? `/api/link/events?${qs}` : `/api/link/memos?${qs}&scope=${KINDS[m.kind].scope}`);
  if (!Array.isArray(rows)) throw new Error("응답 형식");
  return rows.filter((r) => /^\d+$/.test(r?.id) && typeof r.title === "string" && !(kind === "memo" && r.id === m.id)).slice(0, 8)
    .map((r) => ({ title: r.title || "제목 없음", detail: kind === "event" ? eventDate(r) : undefined,
      text: MemoLink.make(r.title || "제목 없음", url, r.id, kind) }));
}
// 연결 칩 줄: 본문의 [@제목](일정·메모 주소) 링크를 중복 없이 모아 본문 위에 보인다. 제목은 글의 링크 텍스트를 먼저 쓰고
// 서버 배치 조회(ids=)로 최신 제목·날짜·삭제 여부를 받아 고친다. linkInfo: "종류id" -> 행 | null(삭제됨) | undefined(조회 실패)
const linkInfo = new Map();
let chipTimer, chipSeq = 0;
function paintChips(lookup = true) {
  const seen = new Set(), found = [];
  for (const x of MemoLink.parse(ed ? ed.view.state.doc.toString() : "", linkBases()))
    if (typeof x !== "string" && !seen.has(x.kind + x.id)) { seen.add(x.kind + x.id); found.push(x); }
  $("e-links").hidden = !found.length;
  $("e-links").replaceChildren(...found.map((l) => {
    const info = linkInfo.get(l.kind + l.id);
    // 같은 탭 이동: 일정은 캘린더 주소, 메모는 이 앱 안 #번호
    const a = el("a", { className: "chip", href: l.kind === "memo" ? "#" + l.id : l.url },
      el("span", { className: "k", textContent: l.kind === "event" ? "일정" : "메모" }),
      el("span", { className: "t", textContent: "@" + (info ? info.title || "제목 없음" : l.title) }));
    a.dataset.kind = l.kind;
    if (info && l.kind === "event") a.append(el("span", { className: "d", textContent: eventDate(info) }));
    if (info === null) { a.classList.add("gone"); a.append(el("span", { className: "d", textContent: "삭제됨" })); }
    return a;
  }));
  if (lookup) lookupLinks(found, lookup === "all");
}
// all: 이미 아는 것까지 다시 묻는다(20초 주기). 묻는 동안·실패하면 아는 값(처음이면 글의 제목)을 그대로 둔다
async function lookupLinks(found, all) {
  const seq = chipSeq, m = cur, want = { event: [], memo: [] };
  for (const l of found) if (all || !linkInfo.has(l.kind + l.id)) want[l.kind].push(l.id);
  for (const [kind, ids] of Object.entries(want)) {
    if (seq !== chipSeq) return;
    if (!ids.length || (kind === "event" && !conf.link)) continue;
    for (const id of ids) if (!linkInfo.has(kind + id)) linkInfo.set(kind + id, undefined); // 묻는 중: 같은 것을 또 묻지 않게
    const got = [];
    try {
      for (let i = 0; i < ids.length; i += 50) { // 메모 서버의 ids 상한(50)에 맞춰 나눠 묻는다
        const part = ids.slice(i, i + 50).join(",");
        const rows = await api(kind === "event" ? `/api/link/events?ids=${part}` : `/api/link/memos?scope=${KINDS[m.kind].lookup(me)}&ids=${part}`);
        if (!Array.isArray(rows)) throw new Error("응답 형식");
        got.push(...rows);
      }
    } catch { continue; } // 실패는 조용히 무시, 다음 주기에 다시
    if (seq !== chipSeq) return; // 그 사이 다른 메모로 갔다(위 반복 처음에도 확인)
    const byId = new Map(got.filter((r) => typeof r?.title === "string").map((r) => [String(r.id), r]));
    for (const id of ids) linkInfo.set(kind + id, byId.get(id) || null);
    paintChips(false);
  }
}

async function openMemo(id) {
  const n = ++openReq;
  let m;
  try { m = await api(`/api/memos/${id}`); } catch { if (n === openReq) leave("메모가 없거나 볼 수 없습니다"); return; }
  if (n !== openReq) return;
  cur = m; setTab(m.kind);
  $("e-cat").replaceChildren(new Option("미분류", ""), ...cats.map((c) => new Option(c.name, c.id)));
  $("e-title").value = m.title;
  fillForm();
  refreshFolders();
  const editable = canEditMemo(m);
  $("e-title").disabled = $("e-cat").disabled = $("e-folder").disabled = !editable;
  $("e-body").inert = !editable; // 보기 전용: 서버가 편집을 버리므로 입력 자체를 막는다
  ed = EvasEditor.create({ parent: $("e-body"), memoId: id, user: { name: me.name, color: colorOf(me.id) }, linkSource });
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
    clearTimeout(chipTimer); chipTimer = setTimeout(paintChips, 500);
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
    // 4404: 삭제, 또는 다른 관리자가 옮겨 내가 못 보게 됨(비관리자에게 전율로 옮긴 것을 드러내지 않게 같은 문구)
    if (code === 4404) return leave(deleting ? "삭제했습니다" : "메모가 삭제되었거나 볼 수 없게 되었습니다");
    if (code === 4403) { leave("관리자 권한이 없어 닫혔습니다"); syncMe(); return; } // 강등: 전율 탭도 치운다
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
      if (r.status === 401) location.href = "/auth/login?next=" + encodeURIComponent("/?memo=" + id);
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
  clearTimeout(chipTimer); chipSeq++; linkInfo.clear(); $("e-links").hidden = true;
  $("e-body").replaceChildren(); $("e-preview").replaceChildren(); $("e-links").replaceChildren(); $("e-peers").textContent = ""; status("");
  // 닫은 메모의 흔적(제목·종류·폴더 이름)을 숨은 편집 화면에 남기지 않는다: 관리자에서 내려간 사람에게 전율 내용이 남지 않게
  $("e-title").value = $("e-kind").textContent = $("e-meta").textContent = "";
  $("e-folder").replaceChildren(); $("e-moves").replaceChildren(); $("e-moves").dataset.to = "";
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
// 옮기기(같은 메모·같은 문서, 복사 아님). 개인 -> 공동만 기존 /share, 전율이 끼는 이동은 /move
async function move(to) {
  const from = cur.kind, id = cur.id;
  if (!confirm(`이 메모를 ${KINDS[to].name}로 옮길까요?\n${KINDS[to].moveNote}.\n${KINDS[from].name}에는 남지 않습니다.`)) return;
  await saveTitle();
  try {
    const m = from === "personal" && to === "shared" ? await api(`/api/memos/${id}/share`, { method: "POST" })
      : await api(`/api/memos/${id}/move`, { method: "POST", body: JSON.stringify({ to }) });
    toast(`${KINDS[to].name}로 옮겼습니다`);
    if (cur && cur.id === id) { cur = m; kindChanged(); }
  } catch (e) { toast(e.message); }
}
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
  if (!confirm(KINDS[cur.kind].delConfirm)) return;
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
    [me, cats, conf] = await Promise.all([api("/api/me"), api("/api/categories"), api("/api/config").catch(() => ({}))]);
  } catch (e) {
    $("msg").hidden = false; $("msg").textContent = "불러오지 못했습니다: " + e.message;
    return;
  }
  initBell();
  // 앱 전환: 캘린더 주소가 http(s)로 설정돼 있을 때만 링크(같은 탭)
  if (MemoLink.base(conf.calendar_url)) { $("to-cal").href = conf.calendar_url + "/"; $("apps-other").hidden = false; }
  paintRole();
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
  route();
}
start();
