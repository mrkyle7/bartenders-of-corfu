/**
 * push.js — Web Push notifications, shared by the home page and every game UI.
 *
 * The server sends a notification when it's your turn or a game ends, unless
 * you're looking at that game (see app/presence.py): game pages only poll
 * while visible, and tell the server when they're hidden.
 *
 * Exposes window.bocPush:
 *   supported          whether this browser can have notifications
 *   on                 whether they're on for this device
 *   sync()             if allowed, make sure the server has this device
 *   turnOn()           ask to allow notifications (call from a click), then sync
 *   turnOff()          stop notifications on this device
 *   watchGame(gameId)  tell the server when this page stops showing the game
 */
(function () {
    function keyBytes(base64String) {
        const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
    }

    async function publicKey() {
        try {
            const resp = await fetch('/vapid-public-key');
            if (!resp.ok) return null;
            return (await resp.json()).public_key || null;
        } catch (_) {
            return null;
        }
    }

    const bocPush = {
        supported: 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window,
        on: false,
        publicKey,

        /**
         * Sends this device's subscription to the server every time, so a
         * device the server forgot, or one now signed in to another account,
         * is picked up again. Resolves whether notifications are on.
         */
        async sync() {
            if (!this.supported || Notification.permission !== 'granted') return (this.on = false);
            const key = await publicKey();
            if (!key) return (this.on = false);
            try {
                const reg = await navigator.serviceWorker.ready;
                const serverKey = keyBytes(key);
                let sub = await reg.pushManager.getSubscription();
                // A subscription made with an older key can't be used any more.
                const subKey = sub && sub.options && sub.options.applicationServerKey
                    ? new Uint8Array(sub.options.applicationServerKey) : null;
                if (sub && subKey && subKey.join() !== serverKey.join()) {
                    await sub.unsubscribe();
                    sub = null;
                }
                if (!sub) {
                    sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: serverKey });
                }
                const resp = await fetch('/v1/push-subscriptions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(sub.toJSON()),
                });
                this.on = resp.ok;
            } catch (_) {
                this.on = false;
            }
            return this.on;
        },

        async turnOn() {
            if (!this.supported) return false;
            const permission = await Notification.requestPermission();
            if (permission !== 'granted') return false;
            return this.sync();
        },

        async turnOff() {
            this.on = false;
            try {
                const reg = await navigator.serviceWorker.ready;
                const sub = await reg.pushManager.getSubscription();
                if (!sub) return;
                await fetch('/v1/push-subscriptions', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ endpoint: sub.endpoint }),
                });
                await sub.unsubscribe();
            } catch (_) {
                // Without the subscription nothing arrives anyway.
            }
        },

        /** When the page is hidden, the server stops counting you as watching. */
        watchGame(gameId) {
            if (!gameId) return;
            document.addEventListener('visibilitychange', () => {
                if (document.visibilityState !== 'hidden') return;
                const url = `/v1/games/${encodeURIComponent(gameId)}/away`;
                if (!(navigator.sendBeacon && navigator.sendBeacon(url))) {
                    fetch(url, { method: 'POST', keepalive: true }).catch(() => {});
                }
            });
        },

        /** The installed app's icon shows how many games are waiting for you. */
        setBadge(count) {
            try {
                if (count > 0 && navigator.setAppBadge) navigator.setAppBadge(count).catch(() => {});
                else if (!count && navigator.clearAppBadge) navigator.clearAppBadge().catch(() => {});
            } catch (_) {}
        },
    };

    window.bocPush = bocPush;

    // Keeps the sign-in fresh while Bartenders is open: at most every
    // 6 hours, on page load and while the page stays open. (The service
    // worker used to do this from its background polling.)
    const REFRESH_MS = 6 * 60 * 60 * 1000;
    function refreshSignIn() {
        let last = 0;
        try { last = Number(localStorage.getItem('bocTokenRefreshedAt')) || 0; } catch (_) {}
        if (Date.now() - last < REFRESH_MS) return;
        fetch('/refresh-token', { method: 'POST' }).then((resp) => {
            if (!resp.ok) return;
            try { localStorage.setItem('bocTokenRefreshedAt', String(Date.now())); } catch (_) {}
        }).catch(() => {});
    }
    refreshSignIn();
    setInterval(refreshSignIn, REFRESH_MS);

    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    }
})();
