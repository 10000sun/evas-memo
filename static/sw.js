// 푸시 알림 전용 서비스 워커(오프라인 캐시는 하지 않는다)
self.addEventListener("push", (e) => {
  const d = e.data ? e.data.json() : {};
  e.waitUntil(self.registration.showNotification(d.title || "에바스 메모", {
    body: d.body || "", icon: "/icons/icon-192.png", data: { url: "/" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(clients.matchAll({ type: "window" }).then((list) =>
    list.length ? list[0].focus() : clients.openWindow(e.notification.data.url)));
});
