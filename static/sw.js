/**
 * sw.js — Service worker for Bartenders of Corfu PWA.
 * Handles notification click-to-focus and background turn polling
 * across ALL of a player's active games.
 */

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

// ─── Notification click → focus or open game tab ────────────────────────────

self.addEventListener('notificationclick', (e) => {
    e.notification.close();
    const url = e.notification.data?.url || '/';
    e.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((tabs) => {
            // Try to focus an existing tab for this game
            for (const tab of tabs) {
                if (tab.url.includes(url)) {
                    return tab.focus();
                }
            }
            // Otherwise try any game tab, then open new
            for (const tab of tabs) {
                if (new URL(tab.url).pathname.startsWith('/game')) {
                    tab.navigate(url);
                    return tab.focus();
                }
            }
            return self.clients.openWindow(url);
        })
    );
});

// ─── Background polling state ───────────────────────────────────────────────

let pollInterval = null;
let pollPlayerId = null;
// Track last-known turn per game so we only notify on changes
let knownTurns = {}; // { gameId: player_turn_uuid }
let lastTokenRefresh = 0;

const POLL_MS = 10_000;
const TOKEN_REFRESH_MS = 6 * 60 * 60 * 1000; // 6 hours

self.addEventListener('message', (e) => {
    const { type } = e.data;
    if (type === 'START_POLL') {
        pollPlayerId = e.data.playerId;
        // Seed known turns from the page so we don't re-notify immediately
        if (e.data.knownTurns) {
            knownTurns = { ...knownTurns, ...e.data.knownTurns };
        }
        startPoll();
    } else if (type === 'STOP_POLL') {
        stopPoll();
    } else if (type === 'UPDATE_TURN') {
        // Page tells us about a turn change it already handled
        if (e.data.gameId && e.data.lastKnownTurn !== undefined) {
            knownTurns[e.data.gameId] = e.data.lastKnownTurn;
        }
    }
});

function startPoll() {
    stopPoll();
    pollInterval = setInterval(checkAllGames, POLL_MS);
}

function stopPoll() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

async function checkAllGames() {
    if (!pollPlayerId) return;
    try {
        const resp = await fetch(`/v1/games?player_id=${encodeURIComponent(pollPlayerId)}&page=1&page_size=100`);
        if (!resp.ok) return;
        const data = await resp.json();

        for (const game of data.games) {
            if (game.status !== 'STARTED' || !game.game_state) continue;

            const gameId = game.id;
            const newTurn = game.game_state.player_turn;
            const prevTurn = knownTurns[gameId];
            const isMyTurn = newTurn === pollPlayerId;
            const turnChanged = prevTurn !== undefined && newTurn !== prevTurn;

            if (isMyTurn && turnChanged) {
                const hostName = game.host_username || 'a game';
                await self.registration.showNotification('Bartenders of Corfu', {
                    body: `It's your turn in ${hostName}'s game!`,
                    icon: '/static/favicon.ico',
                    tag: `turn-${gameId}`,
                    data: { url: `/game?id=${gameId}` },
                });
            }
            knownTurns[gameId] = newTurn;
        }
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
