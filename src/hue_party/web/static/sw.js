// Minimal pass-through service worker: its presence makes the app installable
// (where the browser allows it), while all requests still hit the network so the
// server's cache-busting and no-cache headers stay in charge. Never cache here.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {
  // intentionally empty: default network handling
});
