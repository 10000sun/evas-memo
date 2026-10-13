// 색상 견본. 분류마다 고르는 기준이 흩어지지 않도록 팀이 쓸 후보를 한곳에 둔다
const PRESETS = ["#e57373", "#f06292", "#ffb74d", "#fff176", "#81c784", "#4db6ac",
                 "#4dd0e1", "#64b5f6", "#7986cb", "#ba68c8", "#a1887f", "#90a4ae"];

const say = (text, bad = true) => {
  $("msg").hidden = false; $("msg").className = "notice " + (bad ? "bad" : "ok"); $("msg").textContent = text;
};
// 저장·삭제 공통: 실패하면 서버 메시지를 그대로 보여주고, 성공하면 목록을 다시 그린다
const act = async (fn, okText) => {
  try {
    const r = await fn(); await render();
    // synced === false: 이 앱에서는 바뀌었지만 캘린더에는 못 알렸다(꺼져 있거나 키가 다름) -> 아래 '적용'으로 다시 맞춘다
    say(r && r.synced === false ? okText + " 단, 캘린더에는 반영하지 못했습니다. 아래 ‘캘린더에 이 권한 목록 적용’으로 다시 맞추세요." : okText, false);
  } catch (e) { say(e.message); }
};

const el = (tag, props = {}, ...kids) => {
  const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n;
};

// 색 편집기: 색 선택기·HEX(RGB도 가능)·R/G/B 칸·견본이 한 값을 공유한다. get()은 올바른 색이 아니면 null
function colorEditor(initial) {
  let cur = initial, valid = true;
  const pick = el("input", { type: "color", className: "pick", title: "색 선택", value: initial });
  const hex = el("input", { className: "hex", value: initial, maxLength: 24, placeholder: "#3b5bdb", spellcheck: false });
  hex.setAttribute("aria-label", "HEX 또는 RGB");
  const rgb = ["R", "G", "B"].map((l) => {
    const i = el("input", { type: "number", min: 0, max: 255, className: "rgb", placeholder: l });
    i.setAttribute("aria-label", l); return i;
  });
  const mark = (bad, group) => { valid = !bad; group.forEach((n) => n.classList.toggle("bad", bad)); };
  const set = (c, from) => {
    cur = c; valid = true;
    [hex, ...rgb].forEach((n) => n.classList.remove("bad"));
    if (from !== pick) pick.value = c;
    if (from !== hex) hex.value = c;
    if (from !== rgb) [1, 3, 5].forEach((p, k) => (rgb[k].value = parseInt(c.slice(p, p + 2), 16)));
  };
  pick.oninput = () => set(pick.value, pick);
  hex.oninput = () => { const c = parseColor(hex.value); c ? set(c, hex) : mark(true, [hex]); };
  hex.onblur = () => valid && (hex.value = cur);
  rgb.forEach((i) => (i.oninput = () => {
    const c = parseColor(rgb.map((n) => n.value).join(","));
    c ? set(c, rgb) : mark(true, rgb);
  }));
  set(initial);
  const swatches = el("div", { className: "swatches" }, ...PRESETS.map((p) =>
    el("button", { type: "button", className: "sw", title: p, style: `background:${p}`, onclick: () => set(p) })));
  const wrap = el("div", { className: "cedit" }, el("div", { className: "crow" }, pick, hex, ...rgb), swatches);
  return { el: wrap, get: () => (valid ? cur : null) };
}

const BAD_COLOR = "색 형식이 올바르지 않습니다. 예: #3b5bdb 또는 59, 91, 219";

function catRow(c) {
  const name = el("input", { value: c.name, maxLength: 30, className: "grow", ariaLabel: "분류 이름" });
  const ed = colorEditor(c.color);
  const save = () => {
    const color = ed.get();
    if (!color) return say(BAD_COLOR);
    act(() => api(`/api/categories/${c.id}`, { method: "PUT", body: JSON.stringify({ name: name.value, color }) }), `'${name.value}' 저장했습니다`);
  };
  return el("div", { className: "item" }, name,
    el("button", { className: "btn primary", onclick: save }, "저장"),
    el("button", { className: "btn danger", onclick: () => confirm(`'${c.name}' 분류를 삭제할까요? 이 분류의 메모는 ‘미분류’가 됩니다.`) && act(() => api(`/api/categories/${c.id}`, { method: "DELETE" }), "삭제했습니다") }, "삭제"),
    ed.el);
}

function userRow(u, meId) {
  const role = el("select", {}, new Option("편집자", "editor"), new Option("관리자", "admin"));
  role.value = u.role;
  role.onchange = () => act(() => api(`/api/users/${encodeURIComponent(u.id)}`, { method: "PUT", body: JSON.stringify({ name: u.name, role: role.value }) }), "권한을 바꿨습니다");
  return el("div", { className: "item" },
    el("span", { className: "grow" }, `${u.name} (${u.id})${u.id === meId ? " · 나" : ""}`), role,
    el("button", { className: "btn danger", onclick: () => confirm(`${u.name}님을 목록에서 제거할까요?`) && act(() => api(`/api/users/${encodeURIComponent(u.id)}`, { method: "DELETE" }), "제거했습니다") }, "제거"));
}

const when = (iso) => new Date(iso).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" }); // app.js와 같은 형식

// 접속한 사용자: 권한 지정·기본값 복귀는 위 사용자 권한과 같은 API(PUT/DELETE /api/users/{id})를 쓴다
function memberRow(m, meId) {
  const url = `/api/users/${encodeURIComponent(m.id)}`;
  const role = el("select", {}, new Option("편집자", "editor"), new Option("관리자", "admin"));
  if (m.role === "viewer") role.add(new Option("보기 전용", "viewer"));
  role.value = m.role;
  role.onchange = () => act(() => api(url, { method: "PUT", body: JSON.stringify({ name: m.name, role: role.value }) }), "권한을 바꿨습니다");
  const reset = el("button", { className: "btn", disabled: !m.custom, title: m.custom ? "" : "지정된 권한이 없습니다",
    onclick: () => act(() => api(url, { method: "DELETE" }), "기본값으로 되돌렸습니다") }, "기본값으로");
  return el("div", { className: "item" },
    el("span", { className: "grow" }, `${m.name} (${m.id})${m.id === meId ? " · 나" : ""}`),
    el("span", { className: "hint" }, m.last_seen ? `마지막 접속 ${when(m.last_seen)}` : "접속 기록 없음"), role, reset);
}

async function render() {
  const [cats, users, members, me] = await Promise.all([api("/api/categories"), api("/api/users"), api("/api/members"), api("/api/me")]);
  $("cats").replaceChildren(...cats.map(catRow));
  $("users").replaceChildren(...users.map((u) => userRow(u, me.id)));
  $("members").replaceChildren(...members.map((m) => memberRow(m, me.id)));
}

const newColor = colorEditor("#64b5f6");
$("cn-color").append(newColor.el);
$("cat-new").onsubmit = (e) => {
  e.preventDefault();
  const color = newColor.get();
  if (!color) return say(BAD_COLOR);
  act(() => api("/api/categories", { method: "POST", body: JSON.stringify({ name: $("cn-name").value, color }) }), "추가했습니다")
    .then(() => ($("cn-name").value = ""));
};
$("user-new").onsubmit = (e) => {
  e.preventDefault();
  const id = $("un-id").value.trim();
  act(() => api(`/api/users/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ name: $("un-name").value, role: $("un-role").value }) }), "추가했습니다")
    .then(() => { $("un-id").value = ""; $("un-name").value = ""; });
};

// 두 앱이 연동돼 있을 때만(LINK_API_KEY) 권한 목록을 캘린더에 한 번에 적용하는 버튼
api("/api/config").then((c) => { $("sync-row").hidden = !c.link; }).catch(() => {});
$("sync-btn").onclick = async () => {
  $("sync-btn").disabled = true; $("sync-msg").textContent = "적용 중…";
  try {
    const r = await api("/api/users/sync", { method: "POST" });
    $("sync-msg").textContent = r.failed ? `${r.ok}명 적용, ${r.failed}명 실패(캘린더가 꺼져 있거나 키가 다를 수 있습니다)` : `${r.ok}명 적용했습니다`;
  } catch (e) { $("sync-msg").textContent = e.message; }
  $("sync-btn").disabled = false;
};

(async () => {
  try {
    const me = await api("/api/me");
    if (me.role !== "admin") return say("관리자만 볼 수 있는 페이지입니다.");
    await render(); $("main").hidden = false;
  } catch (e) { say("불러오지 못했습니다: " + e.message); }
})();
