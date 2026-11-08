// 업데이트 안내: static/changes.json(최신이 맨 앞)을 읽어 두 가지를 한다.
// 1) 이 브라우저가 아직 못 본 버전을 첫 접속 때 한 번 팝업으로 보여준다(닫을 때 본 버전을 localStorage에 기억, 처음 오는 브라우저는 가장 최근 것만).
// 2) 알림(종 모양) 창에 '업데이트 내역'을 붙여 지난 업데이트를 날짜별로 언제든 다시 보게 한다.
(async () => {
  const KEY = "evas-seen-release";
  const el = (tag, props, ...kids) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };
  // 팝업: heading 아래에 버전별 제목과 항목을 보여준다
  const show = (heading, releases, onClose) => {
    const dlg = el("dialog", { className: "whatsnew" }, el("h2", {}, heading),
      ...releases.flatMap((r) => [el("h3", {}, r.title, el("span", { className: "meta" }, ` ${r.id.slice(0, 10)}`)),
        el("ul", {}, ...r.items.map((i) => el("li", {}, i.admin ? "[관리자] " : "", i.text)))]),
      el("div", { className: "btns" }, el("span"), el("button", { className: "btn primary", type: "button", onclick: () => dlg.close() }, "확인")));
    dlg.style.cssText = "max-height:80dvh;overflow-y:auto;word-break:keep-all"; // 긴 안내는 스크롤, 한글이 단어 중간에서 끊기지 않게
    dlg.onclose = () => { dlg.remove(); onClose && onClose(); };
    document.body.append(dlg);
    dlg.showModal();
  };
  try {
    const list = await (await fetch("/changes.json", { cache: "no-store" })).json();
    if (!list.length) return;
    const admin = (await api("/api/me")).role === "admin";
    // 관리자 전용 항목은 일반 사용자에게 빼고, 남는 항목이 없는 버전은 감춘다
    const visible = list.map((r) => ({ ...r, items: r.items.filter((i) => !i.admin || admin) })).filter((r) => r.items.length);

    // 알림 창: '업데이트 내역' 접이식 목록. 누르면 그 버전의 안내가 다시 뜬다
    const notif = document.getElementById("notif");
    if (notif && visible.length) {
      const box = el("details", { className: "n-releases" }, el("summary", {}, `업데이트 내역 (${visible.length})`),
        el("ul", { className: "n-list" }, ...visible.map((r) => el("li", {}, el("button", {
          type: "button", className: "btn ghost", style: "width:100%;justify-content:flex-start",
          onclick: () => show(`${r.id.slice(0, 10)} 업데이트 내역`, [r]),
        }, `${r.id.slice(0, 10)} 업데이트 내역`)))));
      box.style.margin = "10px 0";
      (notif.querySelector(".btns") || notif.lastElementChild).before(box);
    }

    // 첫 접속 팝업
    let seen = null;
    try { seen = localStorage.getItem(KEY); } catch { /* 저장소를 못 쓰면 접속할 때마다 보인다 */ }
    const news = seen ? visible.filter((r) => r.id > seen) : visible.slice(0, 1);
    const done = () => { try { localStorage.setItem(KEY, list[0].id); } catch { /* 위와 같다 */ } };
    if (news.length) show("업데이트 안내", news, done); else done();
  } catch (e) { console.warn("업데이트 안내를 불러오지 못했습니다", e); /* 안내는 없어도 앱 사용에 지장이 없다 */ }
})();
