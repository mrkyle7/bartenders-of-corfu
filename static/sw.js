/**
 * sw.js — Service worker for Bartenders of Corfu PWA.
 * Handles notification click-to-focus and background turn polling.
 */

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

// ─── Notification click → focus or open game tab ────────────────────────────

self.addEventListener('notificationclick', (e) => {
    e.notification.close();
    const url = e.notification.data?.url || '/';
    e.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((tabs) => {
            for (const tab of tabs) {
                if (new URL(tab.url).pathname.startsWith('/game')) {
                    return tab.focus();
                }
            }
            return self.clients.openWindow(url);
        })
    );
});

// ─── Background polling state ───────────────────────────────────────────────

let pollInterval = null;
let pollGameId = null;
let pollPlayerId = null;
let lastKnownTurn = null;
let lastTokenRefresh = 0;

const POLL_MS = 10_000;
const TOKEN_REFRESH_MS = 6 * 60 * 60 * 1000; // 6 hours

self.addEventListener('message', (e) => {
    const { type } = e.data;
    if (type === 'START_POLL') {
        pollGameId = e.data.gameId;
        pollPlayerId = e.data.playerId;
        lastKnownTurn = e.data.lastKnownTurn;
        startPoll();
    } else if (type === 'STOP_POLL') {
        stopPoll();
    } else if (type === 'UPDATE_TURN') {
        lastKnownTurn = e.data.lastKnownTurn;
    }
});

function startPoll() {
    stopPoll();
    pollInterval = setInterval(checkTurn, POLL_MS);
}

function stopPoll() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

async function checkTurn() {
    if (!pollGameId || !pollPlayerId) return;
    try {
        const resp = await fetch(`/v1/games/${pollGameId}`);
        if (!resp.ok) return;
        const game = await resp.json();
        const gs = game.game_state;
        if (!gs) return;

        const newTurn = gs.player_turn;
        const isMyTurn = newTurn === pollPlayerId;
        const turnChanged = lastKnownTurn !== null && newTurn !== lastKnownTurn;

        if (isMyTurn && turnChanged) {
            await self.registration.showNotification('Bartenders of Corfu', {
                body: "It's your turn!",
                icon: '/static/favicon.ico',
                tag: 'turn-notification',
                data: { url: `/game?id=${pollGameId}` },
            });
        }
        lastKnownTurn = newTurn;
    } catch (_) {
        // Network error — silently skip this cycle
    }

    // Periodic token refresh (every 6 hours)
    const now = Date.now();
    if (now - lastTokenRefresh > TOKEN_REFRESH_MS) {
        lastTokenRefresh = now;
        try {
            await fetch('/refresh-token', { method: 'POST' });
        } catch (_) {
            // ignore
        }
    }
}
