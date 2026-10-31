// 업데이트 안내: static/changes.json(최신이 맨 앞)에서 이 브라우저가 아직 못 본 버전을 첫 접속 때 한 번 보여준다.
// 닫을 때 본 버전을 기억한다(localStorage). 처음 오는 브라우저는 가장 최근 것만 보여준다.
(async () => {
  const KEY = "evas-seen-release";
  try {
    const list = await (await fetch("/changes.json", { cache: "no-store" })).json();
    if (!list.length) return;
    let seen = null;
    try { seen = localStorage.getItem(KEY); } catch { /* 저장소를 못 쓰면 접속할 때마다 보인다 */ }
    const admin = (await api("/api/me")).role === "admin";
    const news = (seen ? list.filter((r) => r.id > seen) : list.slice(0, 1))
      .map((r) => ({ ...r, items: r.items.filter((i) => !i.admin || admin) })).filter((r) => r.items.length);
    const done = () => { try { localStorage.setItem(KEY, list[0].id); } catch { /* 위와 같다 */ } };
    if (!news.length) return done();
    const el = (tag, props, ...kids) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };
    const dlg = el("dialog", { className: "whatsnew" },
      el("h2", {}, "업데이트 안내"),
      ...news.flatMap((r) => [el("h3", {}, r.title, el("span", { className: "meta" }, ` ${r.id.slice(0, 10)}`)),
        el("ul", {}, ...r.items.map((i) => el("li", {}, i.admin ? "[관리자] " : "", i.text)))]),
      el("div", { className: "btns" }, el("span"), el("button", { className: "btn primary", type: "button", onclick: () => dlg.close() }, "확인")));
    dlg.style.cssText = "max-height:80dvh;overflow-y:auto;word-break:keep-all"; // 긴 안내는 스크롤, 한글이 단어 중간에서 끊기지 않게
    dlg.onclose = () => { done(); dlg.remove(); };
    document.body.append(dlg);
    dlg.showModal();
  } catch { /* 안내는 없어도 앱 사용에 지장이 없다 */ }
})();
