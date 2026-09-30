/**
 * sw.js — Service worker for Bartenders of Corfu PWA.
 * Shows the server's Web Push notifications (your turn, game over) and
 * opens the game when one is clicked. The server decides when to send them
 * (app/api.py), so nothing here polls.
 */

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

// ─── Web Push notifications ──────────────────────────────────────────────────

self.addEventListener('push', (e) => {
    let payload = { title: 'Bartenders of Corfu', body: "It's your turn!", url: '/' };
    try { payload = { ...payload, ...JSON.parse(e.data.text()) }; } catch (_) {}
    e.waitUntil(
        self.registration.showNotification(payload.title, {
            body: payload.body,
            icon: '/static/favicon.ico',
            // One notification per game, the latest replacing the last
            tag: payload.tag || 'turn-push',
            renotify: true,
            data: { url: payload.url },
        })
    );
});

// ─── Notification click → focus or open game tab ────────────────────────────

self.addEventListener('notificationclick', (e) => {
    e.notification.close();
    const url = new URL(e.notification.data?.url || '/', self.location.origin);
    const gameId = url.searchParams.get('id');
    // Any of the three game views (/game, /play, /bar) of the same game
    const isGamePage = (u) => ['/game', '/play', '/bar'].includes(u.pathname);
    e.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (tabs) => {
            for (const tab of tabs) {
                const u = new URL(tab.url);
                if (gameId && isGamePage(u) && u.searchParams.get('id') === gameId) {
                    return tab.focus();
                }
            }
            // Otherwise reuse a game or home tab, then open a new one
            for (const tab of tabs) {
                const u = new URL(tab.url);
                if ((isGamePage(u) || u.pathname === '/') && 'navigate' in tab) {
                    const moved = await tab.navigate(url.href).catch(() => null);
                    if (moved) return moved.focus();
                }
            }
            return self.clients.openWindow(url.href);
        })
    );
});
