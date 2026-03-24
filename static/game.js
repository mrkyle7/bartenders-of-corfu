/**
 * game.js — Bartenders of Corfu game board (entry point module).
 * Vanilla ES2022.
 */

import { SPIRITS, CARD_COST_TOKEN, CARD_COST_COUNT, MAX_SLOTS } from './constants.js';
import { ingredientLabel, ingredientIcon, ingredientKind, makeIngredientBadge, makeCostBadge } from './ingredients.js';
import { h, text, el, showError, clearError, showModalError, clearModalError,
         setButtonBusy, formatTime, flash, switchTab, openModal, closeModal } from './dom.js';
import { detectBestDrink, getCocktailRecipes, getValidPairings, SPECIAL_TYPES, cocktailsForSpecial } from './drinks.js';
import S from './state.js';

// ─────────────────────────────────────────────────────────────
// Initial load + polling
// ─────────────────────────────────────────────────────────────
async function load() {
    const sp = new URLSearchParams(window.location.search);
    S.gameId = sp.get('id');
    if (!S.gameId) {
        showError('No game ID found in URL. Return to home page.');
        return;
    }

    // Fetch current user
    try {
        const meResp = await fetch('/userDetails');
        if (meResp.status === 401 || meResp.status === 403) {
            window.location.href = '/';
            return;
        }
        if (meResp.ok) {
            S.me = await meResp.json();
            if (typeof applyTheme === 'function') applyTheme(S.me.theme || 'taverna');
        }
    } catch (e) {
        console.warn('Could not fetch user details:', e);
    }

    // Register service worker for PWA + notification click handling
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    }

    // Request browser notification permission (no-op if already granted/denied)
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }

    // Background polling: tell SW to poll all games when tab is hidden
    document.addEventListener('visibilitychange', () => {
        if (!navigator.serviceWorker?.controller) return;
        if (document.visibilityState === 'hidden') {
            const turns = {};
            if (S.gameId && S.lastKnownTurn) turns[S.gameId] = S.lastKnownTurn;
            navigator.serviceWorker.controller.postMessage({
                type: 'START_POLL',
                playerId: S.me?.id,
                knownTurns: turns,
            });
        } else {
            navigator.serviceWorker.controller.postMessage({ type: 'STOP_POLL' });
        }
    });

    await refreshGame();
    await refreshHistory();
    refreshNotificationBell();

    // Auto-enter replay if ?turn= is in the URL
    const turnParam = sp.get('turn');
    if (turnParam !== null && S.replayTurns.length > 0) {
        const turnNumber = parseInt(turnParam, 10) - 1;  // convert display (1-indexed) to stored turn_number
        const cursor = S.replayTurns.indexOf(turnNumber);
        if (cursor !== -1) await replayGoTo(cursor);
    }
}

async function refreshGame(quiet = false) {
    if (!quiet) clearError();
    try {
        const resp = await fetch(`/v1/games/${S.gameId}`);
        if (resp.status === 401 || resp.status === 403) {
            window.location.href = '/';
            return;
        }
        if (!resp.ok) {
            showError('Failed to load game. Please refresh.');
            return;
        }
        const game = await resp.json();
        await resolvePlayerNames(game.players);
        S.game = game;
        S.pendingUndo = game.pending_undo || null;
        const newTurn = game.game_state && game.game_state.player_turn;
        const isMyTurn = S.me && newTurn === S.me.id;
        const turnChanged = S.lastKnownTurn !== null && newTurn !== S.lastKnownTurn;
        if (isMyTurn && turnChanged) notifyMyTurn();
        if (turnChanged) refreshNotificationBell();
        S.lastKnownTurn = newTurn;
        // Keep SW in sync with current turn
        if (turnChanged && navigator.serviceWorker?.controller) {
            navigator.serviceWorker.controller.postMessage({
                type: 'UPDATE_TURN', gameId: S.gameId, lastKnownTurn: newTurn
            });
        }
        renderAll(game);
        schedulePoll(game);
    } catch (e) {
        if (!quiet) showError('Network error loading game. Retrying…');
        console.error(e);
        schedulePoll({ status: 'STARTED', game_state: {} });
    }
}

async function resolvePlayerNames(playerIds) {
    const toFetch = playerIds.filter(pid => !S.players[pid]);
    if (toFetch.length === 0) return;
    await Promise.all(toFetch.map(async pid => {
        try {
            const r = await fetch(`/v1/users/${encodeURIComponent(pid)}`);
            if (r.ok) {
                const u = await r.json();
                S.players[pid] = { id: pid, username: u.username || pid };
            } else {
                S.players[pid] = { id: pid, username: pid.slice(0, 8) };
            }
        } catch {
            S.players[pid] = { id: pid, username: pid.slice(0, 8) };
        }
    }));
}

function playerName(pid) {
    if (!pid) return 'Unknown';
    if (S.players[pid]) return S.players[pid].username;
    return pid.slice(0, 8);
}

async function notifyMyTurn() {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    if (document.visibilityState === 'visible') return;

    // Prefer SW-based notification (supports click-to-focus)
    const reg = await navigator.serviceWorker?.ready;
    if (reg) {
        await reg.showNotification('Bartenders of Corfu', {
            body: "It's your turn!",
            icon: '/static/favicon.ico',
            tag: 'turn-notification',
            data: { url: window.location.href },
        });
    } else {
        new Notification("Bartenders of Corfu", {
            body: "It's your turn!",
            icon: '/static/favicon.ico',
        });
    }

    // Keep SW in sync so it doesn't re-notify
    if (navigator.serviceWorker?.controller) {
        navigator.serviceWorker.controller.postMessage({
            type: 'UPDATE_TURN', lastKnownTurn: S.lastKnownTurn
        });
    }
}

async function refreshNotificationBell() {
    if (!S.me) return;
    try {
        const resp = await fetch(`/v1/games?player_id=${encodeURIComponent(S.me.id)}&page=1&page_size=100`);
        if (!resp.ok) return;
        const data = await resp.json();
        const count = data.games.filter(g =>
            g.status === 'STARTED' && g.game_state && g.game_state.player_turn === S.me.id
        ).length;
        const bell = document.getElementById('gbNotificationBell');
        if (!bell) return;
        const badge = bell.querySelector('.notif-badge');
        if (count > 0) {
            bell.classList.remove('hidden');
            badge.textContent = count;
            bell.setAttribute('aria-label', `${count} game${count === 1 ? '' : 's'} waiting for your turn`);
        } else {
            bell.classList.add('hidden');
        }
    } catch { /* ignore */ }
}

function schedulePoll(game) {
    if (S.pollTimer) clearTimeout(S.pollTimer);
    if (S.replayMode) return;  // pause polling while replaying
    if (!game || game.status !== 'STARTED') return;
    const gs = game.game_state || {};
    const myTurn = S.me && gs.player_turn === S.me.id;
    // Poll when it's not our turn, or when an undo vote is pending (any player needs updates)
    if (!myTurn || S.pendingUndo) {
        S.pollTimer = setTimeout(() => refreshGame(true), 3000);
    }

    // Periodic token refresh (every 6 hours)
    const now = Date.now();
    if (!S._lastTokenRefresh) S._lastTokenRefresh = now;
    if (now - S._lastTokenRefresh > 6 * 60 * 60 * 1000) {
        S._lastTokenRefresh = now;
        fetch('/refresh-token', { method: 'POST' }).catch(() => {});
    }
}

// ─────────────────────────────────────────────────────────────
// Master render — dispatches to sub-renderers
// ─────────────────────────────────────────────────────────────
function renderAll(game, replayState = null) {
    const gs = replayState || game.game_state || {};
    S.currentGs = gs;
    const isReplay = !!replayState;

    // Header
    el('gbGameId').textContent = game.id;
    el('gbGameId').title = `Game ID: ${game.id}`;
    renderTurnIndicator(game, gs);

    // Lobby view for NEW games
    if (game.status === 'NEW' && !isReplay) {
        el('gbLobbyPanel').classList.remove('hidden');
        el('gbBoardLoading').classList.add('hidden');
        el('gbBoardContent').classList.add('hidden');
        el('gbMySheetLoading').classList.add('hidden');
        el('gbMySheetContent').classList.add('hidden');
        el('gbUndoSection').classList.add('hidden');
        el('gbPlayerStatsBar').classList.add('hidden');
        el('gbPlayerMats').classList.add('hidden');
        renderLobby(game);
        schedulePollLobby();
        return;
    }
    el('gbLobbyPanel').classList.add('hidden');

    // Stats bar (all players compact)
    renderAllStats(game, gs);

    // Board
    renderBoard(game, gs, isReplay);

    // My sheet
    if (S.me && gs.player_states) {
        const myState = gs.player_states[S.me.id];
        if (myState) {
            renderMySheet(game, gs, myState, isReplay);
        }
    }

    // Other players
    renderOthers(game, gs, isReplay);

    // Undo
    renderUndoSection(game, isReplay);

    // Winner
    const winnerBanner = el('gbWinnerBanner');
    if (gs.winner) {
        const ws = gs.player_states ? gs.player_states[gs.winner] : null;
        let reason = '';
        if (ws) {
            if ((ws.points || 0) >= 40) reason = ' (40+ points)';
            else if ((ws.karaoke_cards_claimed || 0) >= 3) reason = ' (3 karaoke cards)';
            else {
                // Last player standing — check if all others are eliminated
                const others = Object.entries(gs.player_states || {}).filter(([id]) => id !== gs.winner);
                if (others.length > 0 && others.every(([, ps]) => ps.status === 'hospitalised' || ps.status === 'wet')) {
                    reason = ' (last one standing)';
                }
            }
        }
        winnerBanner.textContent = `\uD83C\uDFC6 ${playerName(gs.winner)} wins${reason}! Congratulations!`;
        winnerBanner.classList.add('visible');
    } else {
        winnerBanner.classList.remove('visible');
    }

    // Show content
    el('gbBoardLoading').classList.add('hidden');
    el('gbBoardContent').classList.remove('hidden');
    el('gbMySheetLoading').classList.add('hidden');
    el('gbMySheetContent').classList.remove('hidden');
    el('gbPlayerStatsBar').classList.remove('hidden');
    el('gbPlayerMats').classList.remove('hidden');

    // Auto-open staging area if mid-taking (handles page refresh and batch continuation)
    _maybeAutoOpenStaging(game, gs, isReplay);

    // Render action bar
    renderActionBar(game, gs, isReplay);
}

function renderAllStats(game, gs) {
    const bar = el('gbPlayerStatsBar');
    if (!bar) return;
    bar.replaceChildren();
    const gameEnded = game.status === 'ENDED';
    (game.players || []).forEach(pid => {
        const pState = gs.player_states ? gs.player_states[pid] : null;
        const isMe = S.me && pid === S.me.id;
        const isActive = !gameEnded && gs.player_turn === pid;

        const isEliminated = pState && (pState.status === 'hospitalised' || pState.status === 'wet');

        const strip = document.createElement('div');
        strip.className = 'gb-stats-strip' +
            (isActive ? ' active-turn' : '') +
            (isMe ? ' is-me' : '') +
            (isEliminated ? ' eliminated' : '');

        const nameSpan = document.createElement('span');
        nameSpan.className = 'gb-stats-strip-name';
        nameSpan.textContent = playerName(pid);
        strip.appendChild(nameSpan);

        if (isEliminated) {
            const tag = document.createElement('span');
            tag.className = 'gb-stats-strip-elim-tag';
            if (pState.status === 'hospitalised') {
                tag.textContent = '\uD83C\uDFE5 HOSPITALISED';
                tag.title = 'Drunk level exceeded 5 — eliminated!';
            } else {
                tag.textContent = '\uD83D\uDCA6 WET';
                tag.title = 'Bladder overflowed — eliminated!';
            }
            strip.appendChild(tag);
        } else if (isActive) {
            const tag = document.createElement('span');
            tag.className = 'gb-stats-strip-turn-tag';
            tag.textContent = isMe ? 'YOUR TURN' : 'THEIR TURN';
            strip.appendChild(tag);
        }

        if (pState) {
            [
                `${pState.points || 0}/40 pts`,
                `Drunk: ${pState.drunk_level || 0}/5`,
                `Bladder: ${(pState.bladder || []).length}/${pState.bladder_capacity || 8}`,
                `Karaoke: ${pState.karaoke_cards_claimed || 0}/3`,
            ].forEach(text => {
                const s = document.createElement('span');
                s.className = 'gb-stats-strip-stat';
                s.textContent = text;
                strip.appendChild(s);
            });
        }

        bar.appendChild(strip);
    });
}

function renderTurnIndicator(game, gs) {
    const ind = el('gbTurnIndicator');
    if (game.status === 'ENDED') {
        ind.textContent = 'Game Over';
        ind.className = 'gb-turn-indicator gb-ended';
        return;
    }
    if (game.status !== 'STARTED') {
        ind.textContent = 'Waiting to start';
        ind.className = 'gb-turn-indicator';
        return;
    }
    const currentPlayer = gs.player_turn;
    const isMyTurn = S.me && currentPlayer === S.me.id;
    const turnDisplay = gs.turn_number !== null ? gs.turn_number + 1 : '?';
    if (isMyTurn) {
        ind.textContent = `Your turn  •  Turn ${turnDisplay}`;
        ind.className = 'gb-turn-indicator gb-my-turn';
    } else {
        const name = playerName(currentPlayer);
        ind.textContent = `${name}'s turn  •  Turn ${turnDisplay}`;
        ind.className = 'gb-turn-indicator';
    }
}

// ─────────────────────────────────────────────────────────────
// Lobby view (NEW game — waiting for players)
// ─────────────────────────────────────────────────────────────
function renderLobby(game) {
    const list = el('playerList');
    if (!list) return;
    list.replaceChildren();
    const isHost = S.me && S.me.id === game.host;
    (game.players || []).forEach(pid => {
        const entry = document.createElement('li');
        entry.className = 'player-entry';
        entry.classList.add('gb-lobby-entry');

        const nameSpan = document.createElement('span');
        nameSpan.textContent = playerName(pid);
        if (pid === game.host) {
            nameSpan.textContent += ' (host)';
        }
        entry.appendChild(nameSpan);

        if (isHost && pid !== game.host) {
            const btn = document.createElement('button');
            btn.className = 'remove-player-btn';
            btn.textContent = 'Remove';
            btn.setAttribute('aria-label', `Remove ${playerName(pid)}`);
            btn.dataset.playerId = pid;
            btn.onclick = async () => {
                btn.disabled = true;
                try {
                    const resp = await fetch(`/v1/games/${S.gameId}/players/${encodeURIComponent(pid)}`, { method: 'DELETE' });
                    if (resp.ok) {
                        await refreshGame();
                    } else {
                        btn.disabled = false;
                        const d = await resp.json().catch(() => ({}));
                        showError(d.error || 'Failed to remove player');
                    }
                } catch (e) {
                    btn.disabled = false;
                    showError('Network error removing player');
                }
            };
            entry.appendChild(btn);
        }

        list.appendChild(entry);
    });

    // Start Game button — host only
    const section = el('gbStartGameSection');
    if (!section) return;
    section.replaceChildren();
    if (isHost) {
        const btn = document.createElement('button');
        btn.id = 'gbBtnStartGame';
        btn.className = 'gb-action-btn';
        btn.textContent = 'Start Game';
        btn.setAttribute('aria-label', 'Start the game');
        btn.onclick = startGame;
        section.appendChild(btn);
    }
}

async function startGame() {
    const btn = el('gbBtnStartGame');
    setButtonBusy(btn, true, 'Starting…');
    clearError();
    try {
        const resp = await fetch(`/v1/games/${S.gameId}/start`, { method: 'POST' });
        if (resp.ok) {
            await refreshGame();
        } else {
            setButtonBusy(btn, false);
            const d = await resp.json().catch(() => ({}));
            showError(d.error || 'Failed to start game');
        }
    } catch (e) {
        setButtonBusy(btn, false);
        showError('Network error starting game');
    }
}

function schedulePollLobby() {
    if (S.pollTimer) clearTimeout(S.pollTimer);
    S.pollTimer = setTimeout(() => refreshGame(true), 3000);
}

// ─────────────────────────────────────────────────────────────
// Bag visual (SVG drawstring bag)
// ─────────────────────────────────────────────────────────────
function renderBagVisual(bagCount, isMyTurn, myState, gs) {
    const existing = el('gbBagVisual');
    if (existing) existing.remove();
    // Remove old inline draw selector
    const oldDraw = el('gbBagDrawInline');
    if (oldDraw) oldDraw.remove();

    const wrap = document.createElement('div');
    wrap.id = 'gbBagVisual';
    wrap.className = 'gb-bag-visual' + (isMyTurn ? ' interactive' : '');
    const svgTmpl = document.getElementById('tmplBagSvg');
    if (svgTmpl) wrap.appendChild(svgTmpl.content.cloneNode(true));
    wrap.appendChild(h('div', { className: 'gb-bag-count-badge', textContent: String(bagCount) }));

    const bagCountEl = el('gbBagCount');

    if (isMyTurn && myState) {
        const totalLimit = myState.take_count || 3;
        const alreadyTaken = gs.ingredients_taken_this_turn || 0;
        const batchLimit = totalLimit - alreadyTaken;
        const maxDraw = Math.min(batchLimit - S.stagingItems.filter(s => s.source === 'display').length, bagCount);

        // Inline bag draw selector: [bag icon] [-] N [+] [Take]
        const drawRow = document.createElement('div');
        drawRow.id = 'gbBagDrawInline';
        drawRow.className = 'gb-bag-draw-inline';

        const minusBtn = h('button', { className: 'gb-bag-draw-pm', 'aria-label': 'Decrease draw count' }, '\u2212');
        const countSpan = h('span', { className: 'gb-bag-draw-num', textContent: String(Math.max(1, maxDraw)) });
        const plusBtn = h('button', { className: 'gb-bag-draw-pm', 'aria-label': 'Increase draw count' }, '+');
        const takeBtn = h('button', { className: 'gb-bag-draw-take', textContent: 'Take' });

        let drawCount = Math.max(1, maxDraw);
        const updateCount = () => { countSpan.textContent = drawCount; };

        minusBtn.onclick = e => { e.stopPropagation(); if (drawCount > 1) { drawCount--; updateCount(); } };
        plusBtn.onclick = e => { e.stopPropagation(); if (drawCount < maxDraw) { drawCount++; updateCount(); } };
        takeBtn.onclick = async (e) => {
            e.stopPropagation();
            takeBtn.disabled = true;
            takeBtn.textContent = 'Drawing\u2026';
            try {
                const resp = await gameAction('draw-from-bag', { count: drawCount });
                if (!resp.ok) {
                    const d = await resp.json().catch(() => ({}));
                    showError(d.error || 'Failed to draw from bag.');
                    takeBtn.disabled = false;
                    takeBtn.textContent = 'Take';
                    return;
                }
                const data = await resp.json();
                const drawn = data.drawn || [];
                // Add drawn items to staging area
                drawn.forEach(ing => {
                    S.stagingItems.push({ ingredient: ing, source: 'pending', disposition: null, cup_index: null });
                });
                S.stagingActive = true;
                renderStagingArea();
                // Refresh board to update bag count
                await refreshGame();
            } catch (e2) {
                if (e2.message !== 'Unauthorized') showError('Network error drawing from bag.');
                takeBtn.disabled = false;
                takeBtn.textContent = 'Take';
            }
        };

        if (maxDraw <= 0 || bagCount === 0) {
            takeBtn.disabled = true;
        }

        drawRow.append(minusBtn, countSpan, plusBtn, takeBtn);
        bagCountEl.parentNode.insertBefore(wrap, bagCountEl);
        bagCountEl.parentNode.insertBefore(drawRow, bagCountEl);
    } else {
        bagCountEl.parentNode.insertBefore(wrap, bagCountEl);
    }
}

// ─────────────────────────────────────────────────────────────
// Board panel (open display + card rows)
// ─────────────────────────────────────────────────────────────
function renderBoard(game, gs, isReplay) {
    const isMyTurn = !isReplay && S.me && gs.player_turn === S.me.id && game.status === 'STARTED';
    const myState  = (S.me && gs.player_states) ? gs.player_states[S.me.id] : null;

    // Open display
    const dispEl = el('gbOpenDisplay');
    dispEl.replaceChildren();
    const display = gs.open_display || [];
    if (display.length === 0) {
        const empty = document.createElement('em');
        empty.textContent = 'Empty';
        empty.className = 'gb-empty-text';
        dispEl.appendChild(empty);
    } else {
        display.forEach((ing, idx) => {
            const badge = makeIngredientBadge(ing);
            badge.setAttribute('role', isMyTurn ? 'button' : 'listitem');
            badge.dataset.ingredient = ing;
            badge.dataset.idx = idx;
            if (isMyTurn) {
                badge.classList.add('gb-display-takeable');
                badge.setAttribute('tabindex', '0');
                badge.title = `Take ${ingredientLabel(ing)}`;
                // Add to staging area on click (inline flow, no modal)
                badge.onclick = () => addDisplayToStaging(ing, idx, myState, gs);
                badge.onkeydown = e => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); addDisplayToStaging(ing, idx, myState, gs); }
                };
            }
            dispEl.appendChild(badge);
        });
    }

    // Bag visual + count
    const bagContents = gs.bag_contents || [];
    renderBagVisual(bagContents.length, isMyTurn, myState, gs);
    el('gbBagCount').textContent = `Bag: ${bagContents.length}`;

    // Deck sidebar count (face-down cards next to rows)
    const deckCount = el('gbDeckCount');
    if (deckCount) deckCount.textContent = `${gs.deck_size ?? '?'} cards`;

    // Card rows
    const rowsEl = el('gbCardRows');
    rowsEl.replaceChildren();
    const cardRows = gs.card_rows || [];
    const bladder  = myState ? (myState.bladder || []) : [];

    cardRows.forEach(row => {
        const rowWrap = document.createElement('div');
        rowWrap.setAttribute('role', 'listitem');
        rowWrap.dataset.rowPosition = row.position;

        const rowLabelRow = document.createElement('div');
        rowLabelRow.className = 'gb-card-row-label-row';

        const rowLabel = document.createElement('span');
        rowLabel.className = 'gb-card-row-label';
        rowLabel.textContent = `Row ${row.position}`;
        rowLabelRow.appendChild(rowLabel);

        // Refresh row button (needs drunk level >= 3; row 1 is karaoke row — never refreshable)
        const isMyTurn = S.me && gs.player_turn === S.me.id;
        const drunkLevel = myState ? (myState.drunk_level || 0) : 0;
        if (!isReplay && isMyTurn && row.position !== 1) {
            if (drunkLevel >= 3) {
                const refreshBtn = document.createElement('button');
                refreshBtn.className = 'gb-refresh-row-btn';
                refreshBtn.textContent = 'Refresh Row';
                refreshBtn.setAttribute('aria-label', `Refresh card row ${row.position}`);
                refreshBtn.onclick = () => doRefreshRow(row.position, refreshBtn);
                rowLabelRow.appendChild(refreshBtn);
            } else {
                const hasStoredSpirits = (myState.cards || []).some(c => c.card_type === 'store' && (c.stored_spirits || []).length > 0);
                if (hasStoredSpirits) {
                    const hint = document.createElement('span');
                    hint.className = 'gb-refresh-hint';
                    hint.textContent = `Drunk ${drunkLevel}/3 — drink stored spirits to refresh`;
                    rowLabelRow.appendChild(hint);
                }
            }
        }

        rowWrap.appendChild(rowLabelRow);

        const cardsRow = document.createElement('div');
        cardsRow.className = 'gb-card-row';

        (row.cards || []).forEach(card => {
            const cardEl = buildCardElement(card, bladder, isMyTurn && !isReplay, gs);
            cardsRow.appendChild(cardEl);
        });

        if ((row.cards || []).length === 0) {
            const empty = document.createElement('em');
            empty.className = 'gb-empty-hint';
            empty.textContent = 'No cards in this row';
            cardsRow.appendChild(empty);
        }

        rowWrap.appendChild(cardsRow);
        rowsEl.appendChild(rowWrap);
    });
}

function _cloneCardIcon(cardType) {
    const tmpl = document.getElementById(`tmplCardIcon-${cardType}`);
    return tmpl ? tmpl.content.cloneNode(true) : null;
}
function buildCardElement(card, bladder, canClaim, gs) {
    const cardType = card.card_type || (card.is_karaoke ? 'karaoke' : 'store');
    const affordable = canClaim && canAffordCard(card, bladder, gs);

    const cardEl = document.createElement('div');
    cardEl.className = `gb-card ${cardType}` + (affordable ? ' claimable' : '');
    cardEl.setAttribute('role', affordable ? 'button' : 'article');
    const typeLabel = { karaoke: 'Karaoke', store: 'Store', refresher: 'Refresher', cup_doubler: 'Cup Doubler', specialist: 'Specialist' }[cardType] || cardType;
    const costDesc = _cardCostDesc(card);
    cardEl.setAttribute('aria-label', `${card.name || typeLabel}. ${costDesc}`);
    if (affordable) {
        cardEl.setAttribute('tabindex', '0');
        cardEl.onclick = () => doClaimCard(card, cardEl);
        cardEl.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); doClaimCard(card, cardEl); } };
    }

    // Header row: points (left) + cost as words (right)
    const header = document.createElement('div');
    header.className = 'gb-card-header';

    const ptsEl = document.createElement('span');
    ptsEl.className = 'gb-card-pts';
    const cardPts = { karaoke: 5, store: 1, refresher: 1, cup_doubler: 2, specialist: 2 }[cardType] ?? 0;
    ptsEl.textContent = `${cardPts} pt${cardPts !== 1 ? 's' : ''}`;
    header.appendChild(ptsEl);

    const costEl = document.createElement('span');
    costEl.className = `gb-card-cost-words ${CARD_COST_TOKEN[cardType] || 'spirit'}`;
    const costCount = CARD_COST_COUNT[cardType] ?? '?';
    let costIngName = '';
    if (card.spirit_type) costIngName = ingredientLabel(card.spirit_type);
    else if (card.mixer_type) costIngName = ingredientLabel(card.mixer_type);
    else costIngName = CARD_COST_TOKEN[cardType] === 'mixer' ? 'Mixer' : 'Spirit';
    costEl.textContent = `${costCount} ${costIngName}`;
    costEl.title = _cardCostDesc(card);
    header.appendChild(costEl);

    cardEl.appendChild(header);

    // Art: centred type icon
    const artEl = document.createElement('div');
    artEl.className = 'gb-card-art';
    const iconContent = _cloneCardIcon(cardType);
    if (iconContent) artEl.appendChild(iconContent);
    cardEl.appendChild(artEl);

    // Title: card name centred below image
    const titleEl = document.createElement('div');
    titleEl.className = 'gb-card-title';
    titleEl.textContent = card.name || typeLabel;
    cardEl.appendChild(titleEl);

    // Description: ability text with horizontal line above
    const descEl = document.createElement('div');
    descEl.className = 'gb-card-desc';
    const descTexts = {
        karaoke: 'Counts toward karaoke victory',
        store: 'Stores spirits for later use',
        refresher: 'Mixer always sobers, even with spirits',
        cup_doubler: 'Doubles non-cocktail cup points',
        specialist: '+2 pts on non-cocktail sells with this spirit',
    };
    descEl.textContent = descTexts[cardType] || '';
    cardEl.appendChild(descEl);

    return cardEl;
}

function _cardCostDesc(card) {
    const cardType = card.card_type || (card.is_karaoke ? 'karaoke' : 'store');
    const spirit = card.spirit_type ? ingredientLabel(card.spirit_type) : 'any';
    const mixer = card.mixer_type ? ingredientLabel(card.mixer_type) : 'any';
    if (cardType === 'karaoke') return `Cost: 3 ${spirit}`;
    if (cardType === 'store') return `Cost: 1 ${spirit}`;
    if (cardType === 'refresher') return `Cost: 2 ${mixer}`;
    if (cardType === 'cup_doubler') return 'Cost: 3 of same spirit';
    if (cardType === 'specialist') return `Cost: 2 ${spirit}`;
    return '';
}

function canAffordCard(card, bladder, gs) {
    const cardType = card.card_type || (card.is_karaoke ? 'karaoke' : 'store');
    const myState = (S.me && gs && gs.player_states) ? gs.player_states[S.me.id] : null;
    const myCards = myState ? (myState.cards || []) : [];

    function bladderCountOf(type) {
        return bladder.filter(i => i.toUpperCase() === type.toUpperCase()).length;
    }
    function storeCountOf(spiritType) {
        return myCards
            .filter(c => c.card_type === 'store' && (c.spirit_type || '').toUpperCase() === spiritType.toUpperCase())
            .reduce((sum, c) => sum + (c.stored_spirits || []).length, 0);
    }

    if (cardType === 'karaoke') {
        if (!card.spirit_type) return false;
        return bladderCountOf(card.spirit_type) + storeCountOf(card.spirit_type) >= 3;
    }
    if (cardType === 'store') {
        if (!card.spirit_type) return false;
        return bladderCountOf(card.spirit_type) >= 1;
    }
    if (cardType === 'refresher') {
        if (!card.mixer_type) return false;
        return bladderCountOf(card.mixer_type) >= 2;
    }
    if (cardType === 'cup_doubler') {
        // Spec: cost is bladder-only (cannot spend store card spirits)
        for (const spirit of SPIRITS) {
            if (bladderCountOf(spirit) >= 3) return true;
        }
        return false;
    }
    if (cardType === 'specialist') {
        // Spec: bladder only, 2 matching spirits
        if (!card.spirit_type) return false;
        return bladderCountOf(card.spirit_type) >= 2;
    }
    return false;
}

// ─────────────────────────────────────────────────────────────
// My player sheet
// ─────────────────────────────────────────────────────────────
function renderMySheet(game, gs, myState, isReplay) {
    const isMyTurn = S.me && gs.player_turn === S.me.id && game.status === 'STARTED';
    const gameEnded = game.status === 'ENDED';

    // BGA-style player strip
    const nameEl = el('gbMyName');
    nameEl.replaceChildren();
    const strip = document.createElement('div');
    const stripClass = gameEnded ? 'game-ended' : (isMyTurn ? 'my-turn' : 'waiting');
    strip.className = `gb-player-strip ${stripClass}`;
    strip.setAttribute('aria-live', 'polite');

    const stripName = document.createElement('span');
    stripName.className = 'gb-player-strip-name';
    stripName.textContent = (S.me && S.me.username) ? S.me.username : 'Me';
    strip.appendChild(stripName);

    if (isMyTurn && !gameEnded) {
        const tag = document.createElement('span');
        tag.className = 'gb-player-strip-turn-tag';
        tag.textContent = '▶ YOUR TURN';
        strip.appendChild(tag);
    }

    const karaokeTag = document.createElement('span');
    karaokeTag.className = 'gb-player-strip-karaoke';
    karaokeTag.textContent = `🎤 ${myState.karaoke_cards_claimed ?? 0}/3`;
    karaokeTag.title = 'Karaoke cards claimed';
    strip.appendChild(karaokeTag);

    const score = document.createElement('span');
    score.className = 'gb-player-strip-score';
    score.textContent = `${myState.points || 0} / 40 pts`;
    strip.appendChild(score);

    nameEl.appendChild(strip);

    // Drunk track (vertical, left side) + must-take
    renderDrunkTrackVertical(myState, gs);

    // Bladder + Wee row
    renderBladderWeeRow(myState, isMyTurn && !isReplay, game, gs);

    // Cups
    renderMyCups(myState, isMyTurn && !isReplay, game, gs);

    // Drink combinations quick-reference (rendered once, then toggled)
    renderDrinkCombinations();

    // Special ingredients — only show section if non-empty
    const specialsEl = el('gbMySpecials');
    specialsEl.replaceChildren();
    const specials = myState.special_ingredients || [];
    if (specials.length > 0) {
        const specialsTitle = document.createElement('div');
        specialsTitle.className = 'gb-section-title';
        specialsTitle.classList.add('gb-section-title--mt');
        specialsTitle.textContent = 'Specials on Mat';
        specialsEl.appendChild(specialsTitle);
        specials.forEach(s => specialsEl.appendChild(makeIngredientBadge(s)));
    }

    // Claimed cards — only show section if non-empty
    renderClaimedCards(myState, isMyTurn && !isReplay, isReplay);
}

function renderDrunkTrackVertical(myState, gs) {
    const container = el('gbMatLeft');
    if (!container) return;
    container.replaceChildren();

    const drunkLevel = myState.drunk_level || 0;

    const track = document.createElement('div');
    track.className = 'gb-drunk-track-v';
    track.setAttribute('aria-label', `Drunk level ${drunkLevel} of 5`);

    // Title
    const title = document.createElement('div');
    title.className = 'gb-drunk-track-title';
    title.textContent = 'DRUNK';
    track.appendChild(title);

    // Vertical pips (top = level 5, bottom = level 1)
    for (let i = 4; i >= 0; i--) {
        const pip = document.createElement('div');
        const filled = i < drunkLevel;
        pip.className = 'gb-drunk-pip-v' + (filled ? (drunkLevel >= 4 ? ' danger' : ' filled') : '');
        const level = i + 1;
        pip.setAttribute('aria-hidden', 'true');

        // Fun labels
        const labels = ['', '', '', '🥴', '🤢'];
        if (labels[i]) {
            const emoji = document.createElement('span');
            emoji.className = 'gb-drunk-pip-emoji';
            emoji.textContent = labels[i];
            pip.appendChild(emoji);
        }

        const num = document.createElement('span');
        num.className = 'gb-drunk-pip-num';
        num.textContent = level;
        pip.appendChild(num);

        track.appendChild(pip);
    }

    // Level indicator
    const levelLabel = document.createElement('div');
    levelLabel.className = 'gb-drunk-level-label';
    const drunkEmojis = ['🙂', '😊', '😄', '🥴', '😵', '🤮'];
    levelLabel.textContent = drunkEmojis[Math.min(drunkLevel, 5)];
    track.appendChild(levelLabel);

    container.appendChild(track);

    // Must Take — next to drunk track
    const mustTake = document.createElement('div');
    mustTake.className = 'gb-must-take-badge';
    mustTake.setAttribute('aria-label', `Must take ${myState.take_count ?? 3} ingredients`);
    const mtLabel = document.createElement('div');
    mtLabel.className = 'gb-must-take-label';
    mtLabel.textContent = 'MUST TAKE';
    mustTake.appendChild(mtLabel);
    const mtVal = document.createElement('div');
    mtVal.className = 'gb-must-take-value';
    mtVal.textContent = myState.take_count ?? 3;
    mustTake.appendChild(mtVal);
    container.appendChild(mustTake);
}

// renderPointsKaraoke removed — points shown in strip, karaoke moved to strip

function renderBladderWeeRow(myState, isMyTurn, game, gs) {
    const container = el('gbBladderWeeRow');
    if (!container) return;
    container.replaceChildren();

    // Bladder slots
    const bladder = myState.bladder || [];
    const cap = myState.bladder_capacity || 8;
    const toiletTokens = myState.toilet_tokens ?? 4;

    const bladderWrap = document.createElement('div');
    bladderWrap.className = 'gb-bladder-section';
    const bLabel = document.createElement('strong');
    bLabel.className = 'gb-stat-label';
    bLabel.textContent = 'Bladder';
    bladderWrap.appendChild(bLabel);
    bladderWrap.appendChild(makeBladderSlots(bladder, cap, toiletTokens));
    container.appendChild(bladderWrap);

    // Wee button (next to bladder)
    if (isMyTurn) {
        const tile = document.createElement('div');
        tile.className = 'gb-wee-tile';
        tile.setAttribute('role', 'button');
        tile.setAttribute('tabindex', '0');
        tile.setAttribute('aria-label', `Go for a wee \u2014 empties bladder, sobers up 1 level (${toiletTokens} tokens left)`);
        tile.append(
            h('span', { className: 'gb-wee-icon' }, '\uD83D\uDEBD'),
            h('span', { className: 'gb-wee-label' }, 'Wee')
        );
        tile.onclick = () => doWee(tile);
        tile.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); doWee(tile); } };
        container.appendChild(tile);
    }

    // Claimable cards — show cards the player can afford, right below bladder
    if (isMyTurn && gs.card_rows) {
        const claimable = [];
        for (const row of gs.card_rows) {
            for (const card of (row.cards || [])) {
                if (canAffordCard(card, bladder, gs)) {
                    claimable.push(card);
                }
            }
        }
        if (claimable.length > 0) {
            const claimSection = document.createElement('div');
            claimSection.className = 'gb-claimable-cards';
            claimSection.appendChild(h('strong', { className: 'gb-stat-label' }, 'Claimable'));
            const cardList = document.createElement('div');
            cardList.className = 'gb-claimable-list';
            claimable.forEach(card => {
                const cardType = card.card_type || (card.is_karaoke ? 'karaoke' : 'store');
                const typeIcons = { karaoke: '\uD83C\uDFA4', store: '\uD83D\uDCE6', refresher: '\uD83D\uDCA7', cup_doubler: '\uD83E\uDD42', specialist: '\u2B50' };
                const btn = document.createElement('button');
                btn.className = `gb-claimable-btn ${cardType}`;
                btn.textContent = `${typeIcons[cardType] || ''} ${card.name || cardType}`;
                btn.title = _cardCostDesc(card);
                btn.onclick = () => doClaimCard(card, btn);
                cardList.appendChild(btn);
            });
            claimSection.appendChild(cardList);
            container.appendChild(claimSection);
        }
    }
}

function renderClaimedCards(myState, isMyTurn, isReplay) {
    const claimedEl = el('gbMyClaimedCards');
    claimedEl.replaceChildren();
    const cards = myState.cards || [];
    if (cards.length > 0) {
        const claimedTitle = document.createElement('div');
        claimedTitle.className = 'gb-section-title';
        claimedTitle.classList.add('gb-section-title--mt');
        claimedTitle.textContent = 'Claimed Cards';
        claimedEl.appendChild(claimedTitle);
        cards.forEach((c, cardIndex) => {
            const cardType = c.card_type || (c.is_karaoke ? 'karaoke' : 'store');
            const typeLabel = { karaoke: 'Karaoke', store: 'Store', refresher: 'Refresher', cup_doubler: 'Cup Doubler', specialist: 'Specialist' }[cardType] || cardType;
            const div = document.createElement('div');
            div.className = `gb-claimed-card ${cardType}`;

            // Card type icon + name (no ID)
            const headerSpan = document.createElement('span');
            headerSpan.className = 'gb-claimed-card-header';
            const typeIcons = { karaoke: '🎤', store: '📦', refresher: '💧', cup_doubler: '🥂', specialist: '⭐' };
            headerSpan.textContent = `${typeIcons[cardType] || ''} ${typeLabel}: ${c.name || typeLabel}`;
            div.appendChild(headerSpan);

            // Show required ingredient type as a token badge
            if (c.spirit_type && cardType !== 'store') {
                div.appendChild(document.createTextNode(' '));
                div.appendChild(makeIngredientBadge(c.spirit_type));
            } else if (c.mixer_type) {
                div.appendChild(document.createTextNode(' '));
                div.appendChild(makeIngredientBadge(c.mixer_type));
            }

            // Store card: show stored ingredients as clickable tokens
            if (c.stored_spirits && c.stored_spirits.length > 0) {
                const stored = document.createElement('div');
                stored.className = 'gb-card-stored';
                const storedLabel = document.createElement('span');
                storedLabel.className = 'gb-card-stored-label';
                storedLabel.textContent = 'Stored: ';
                stored.appendChild(storedLabel);

                const canInteract = isMyTurn && !isReplay && cardType === 'store';

                c.stored_spirits.forEach(s => {
                    const badge = makeIngredientBadge(s);
                    if (canInteract) {
                        badge.classList.add('gb-stored-clickable');
                        badge.setAttribute('role', 'button');
                        badge.setAttribute('tabindex', '0');
                        badge.setAttribute('aria-label', `Use stored ${ingredientLabel(s)} — click for options`);
                        badge.onclick = (e) => {
                            e.stopPropagation();
                            toggleStoredActions(div, cardIndex, c);
                        };
                    }
                    stored.appendChild(badge);
                });
                div.appendChild(stored);
            }
            claimedEl.appendChild(div);
        });
    }
}

// Render a row of INITIAL_BLADDER_CAPACITY (8) physical bladder slots.
// Slots 0..bladder.length-1: filled (emoji icon, ingredient color)
// Slots bladder.length..cap-1: empty open receptors
// Slots cap..7: sealed (spent toilet tokens, from the right)
function makeBladderSlots(bladder, cap, toiletTokens) {
    const INITIAL_SLOTS = 8;
    const wrap = document.createElement('div');
    wrap.className = 'gb-bladder-slots';
    for (let i = 0; i < INITIAL_SLOTS; i++) {
        const slot = document.createElement('div');
        if (i < bladder.length) {
            const ing = bladder[i];
            slot.className = 'gb-bladder-slot filled';
            slot.appendChild(makeIngredientBadge(ing));
            slot.setAttribute('aria-label', ingredientLabel(ing));
        } else if (i < cap) {
            slot.className = 'gb-bladder-slot empty';
            slot.setAttribute('aria-hidden', 'true');
        } else {
            slot.className = 'gb-bladder-slot sealed';
            slot.textContent = '🚽';
            slot.setAttribute('aria-hidden', 'true');
        }
        wrap.appendChild(slot);
    }
    wrap.setAttribute('aria-label', `Bladder: ${bladder.length} of ${cap} slots used`);
    return wrap;
}

function makeStat(label, value) {
    const div = document.createElement('div');
    div.className = 'gb-stat';
    const strong = document.createElement('strong');
    strong.textContent = label;
    div.appendChild(strong);
    if (typeof value === 'object' && value !== null && value.nodeType) {
        div.appendChild(value);
    } else {
        const val = document.createElement('span');
        val.textContent = String(value);
        div.appendChild(val);
    }
    return div;
}

function renderMyCups(myState, isMyTurn, game, gs) {
    const cupsEl = el('gbMyCups');
    cupsEl.replaceChildren();

    const specials = myState.special_ingredients || [];
    const specialistSpiritTypes = (myState.cards || [])
        .filter(c => c.card_type === 'specialist' && c.spirit_type)
        .map(c => c.spirit_type);
    const cupData = [
        { index: 0, contents: (myState.cups?.[0]?.ingredients) || [], hasDoubler: !!(myState.cups?.[0]?.has_cup_doubler) },
        { index: 1, contents: (myState.cups?.[1]?.ingredients) || [], hasDoubler: !!(myState.cups?.[1]?.has_cup_doubler) },
    ];

    cupData.forEach(({ index, contents, hasDoubler }) => {
        const cupEl = document.createElement('div');
        cupEl.className = 'gb-cup';
        cupEl.setAttribute('aria-label', `Cup ${index + 1}${hasDoubler ? ' (doubled)' : ''}`);
        cupEl.dataset.cupIndex = index;

        const title = document.createElement('div');
        title.className = 'gb-cup-title';
        title.append('\uD83E\uDD42 ', h('span', null, `Cup ${index + 1}`));
        if (hasDoubler) {
            title.appendChild(h('span', { className: 'gb-cup-doubler-badge', title: 'Cup Doubler active \u2014 non-cocktail drinks score \xD72', textContent: '\xD72' }));
        }
        cupEl.appendChild(title);

        const ingArea = document.createElement('div');
        ingArea.className = 'gb-cup-ingredients';
        for (let s = 0; s < MAX_SLOTS; s++) {
            const slot = document.createElement('div');
            if (s < contents.length) {
                const ing = contents[s];
                slot.className = 'gb-cup-slot filled';
                slot.appendChild(makeIngredientBadge(ing));
                slot.setAttribute('aria-label', ingredientLabel(ing));
            } else {
                slot.className = 'gb-cup-slot empty';
                slot.setAttribute('aria-hidden', 'true');
            }
            ingArea.appendChild(slot);
        }
        cupEl.appendChild(ingArea);

        // Inline action buttons below cup (no overlay/modal)
        if (isMyTurn) {
            const actions = document.createElement('div');
            actions.className = 'gb-cup-inline-actions';

            // Auto-detect best drink for this cup
            const drink = detectBestDrink(contents, specials, hasDoubler, specialistSpiritTypes);

            if (drink) {
                const sellBtn = document.createElement('button');
                sellBtn.className = 'gb-cup-action-btn sell';
                sellBtn.innerHTML = `\uD83D\uDCB0 Sell \u2014 ${drink.name} (${drink.points}pts)`;
                sellBtn.setAttribute('aria-label', `Sell cup ${index + 1} as ${drink.name} for ${drink.points} points`);
                sellBtn.onclick = () => doSellCup(index, drink.declaredSpecials, sellBtn);
                actions.appendChild(sellBtn);
            }

            if (contents.length > 0) {
                const drinkBtn = document.createElement('button');
                drinkBtn.className = 'gb-cup-action-btn drink';
                const spirits = contents.filter(i => ingredientKind(i) === 'spirit');
                const mixers = contents.filter(i => ingredientKind(i) === 'mixer');
                // Refresher cards make their mixer type always -1, even with spirits
                const refresherMixerTypes = new Set(
                    (myState.cards || [])
                        .filter(c => c.card_type === 'refresher' && c.mixer_type)
                        .map(c => c.mixer_type.toUpperCase())
                );
                const hotMixers = mixers.filter(m => refresherMixerTypes.has(m.toUpperCase()));
                const plainMixers = mixers.filter(m => !refresherMixerTypes.has(m.toUpperCase()));
                // delta = spirits - hotMixers; plainMixers only subtract when no spirits
                let delta = spirits.length - hotMixers.length;
                if (spirits.length === 0) delta -= plainMixers.length;
                if (delta > 0) {
                    drinkBtn.innerHTML = `\uD83C\uDF7A Drink <span class="gb-cup-warning">+${delta} drunk</span>`;
                } else if (delta < 0) {
                    drinkBtn.textContent = `\uD83C\uDF7A Drink (${delta} drunk)`;
                } else {
                    drinkBtn.textContent = '\uD83C\uDF7A Drink (0 drunk)';
                }
                // Check if drinking would overflow bladder (wet elimination)
                const newBladderSize = (myState.bladder || []).length + contents.length;
                const bladderCap = myState.bladder_capacity || 8;
                if (newBladderSize > bladderCap) {
                    drinkBtn.innerHTML += ' <span class="gb-cup-warning">\u26A0 WET!</span>';
                }
                drinkBtn.setAttribute('aria-label', `Drink cup ${index + 1}`);
                drinkBtn.onclick = () => {
                    if (newBladderSize > bladderCap) {
                        if (!confirm(`Drinking this cup will overflow your bladder (${newBladderSize}/${bladderCap}) and eliminate you! Are you sure?`)) return;
                    }
                    doDrinkCup(index, drinkBtn);
                };
                actions.appendChild(drinkBtn);
            }

            cupEl.appendChild(actions);
        }

        cupsEl.appendChild(cupEl);
    });
}

// ─────────────────────────────────────────────────────────────
// Drink Combinations quick-reference (collapsible)
// ─────────────────────────────────────────────────────────────
let _drinkCombosExpanded = false;
let _drinkCombosRendered = false;

function renderDrinkCombinations() {
    const root = el('gbDrinkCombos');
    if (!root) return;

    // Only build once — toggle visibility thereafter
    if (_drinkCombosRendered) return;
    _drinkCombosRendered = true;

    root.replaceChildren();

    const pairings = getValidPairings();
    const recipes = getCocktailRecipes();

    const spiritOrder = ['VODKA', 'WHISKEY', 'RUM', 'GIN', 'TEQUILA'];
    const mixerOrder = ['COLA', 'SODA', 'TONIC', 'CRANBERRY'];
    const spiritLabels = { VODKA: 'Vodka', WHISKEY: 'Whiskey', RUM: 'Rum', GIN: 'Gin', TEQUILA: 'Tequila' };
    const mixerLabels = { COLA: 'Cola', SODA: 'Soda', TONIC: 'Tonic', CRANBERRY: 'Cran' };

    // --- Header (toggle) ---
    const header = h('button', {
        className: 'gb-combos-toggle',
        'aria-expanded': 'false',
        'aria-controls': 'gbCombosBody',
    });
    const arrow = h('span', { className: 'gb-combos-arrow', 'aria-hidden': 'true', textContent: '\u25B8' });
    header.append(
        h('span', { className: 'gb-combos-icon', 'aria-hidden': 'true', textContent: '\uD83C\uDF79' }),
        h('span', { textContent: ' Drink Guide ' }),
        arrow
    );

    // --- Body (hidden by default) ---
    const body = h('div', { className: 'gb-combos-body', id: 'gbCombosBody' });
    body.hidden = true;

    header.onclick = () => {
        _drinkCombosExpanded = !_drinkCombosExpanded;
        body.hidden = !_drinkCombosExpanded;
        arrow.textContent = _drinkCombosExpanded ? '\u25BE' : '\u25B8';
        header.setAttribute('aria-expanded', String(_drinkCombosExpanded));
    };

    // --- Pairing matrix ---
    const table = h('table', { className: 'gb-combos-matrix', 'aria-label': 'Spirit and mixer pairings' });

    // Header row
    const thead = h('thead');
    const headRow = h('tr');
    headRow.appendChild(h('th', { className: 'gb-combos-corner' })); // empty corner
    mixerOrder.forEach(m => {
        const icon = ingredientIcon(m);
        headRow.appendChild(h('th', {
            className: 'gb-combos-mixer-hdr',
            'aria-label': mixerLabels[m],
        }, h('span', { 'aria-hidden': 'true', textContent: icon }), h('br'), mixerLabels[m]));
    });
    // Points column
    headRow.appendChild(h('th', { className: 'gb-combos-pts-hdr', textContent: 'Pts' }));
    thead.appendChild(headRow);
    table.appendChild(thead);

    // Spirit rows
    const tbody = h('tbody');
    spiritOrder.forEach(sp => {
        const tr = h('tr');
        const icon = ingredientIcon(sp);
        tr.appendChild(h('th', {
            className: 'gb-combos-spirit-hdr',
            'aria-label': spiritLabels[sp],
        }, h('span', { 'aria-hidden': 'true', textContent: icon }), ' ', spiritLabels[sp]));

        if (sp === 'TEQUILA') {
            // Tequila gets a special merged cell
            const td = h('td', {
                className: 'gb-combos-slammer',
                colSpan: String(mixerOrder.length),
                'aria-label': 'Tequila Slammer: 2 Tequila for 3 points',
            }, 'Slammer: 2\u00D7', h('span', { 'aria-hidden': 'true', textContent: '\uD83C\uDF35' }), ' = 3pts');
            tr.appendChild(td);
            tr.appendChild(h('td', { className: 'gb-combos-pts-cell', textContent: '1/3' }));
        } else {
            const validSet = pairings[sp] || new Set();
            mixerOrder.forEach(mx => {
                const valid = validSet.has(mx);
                const td = h('td', {
                    className: valid ? 'gb-combos-cell gb-combos-valid' : 'gb-combos-cell',
                    'aria-label': valid ? `${spiritLabels[sp]} pairs with ${mixerLabels[mx]}` : `No pairing`,
                });
                if (valid) {
                    td.appendChild(h('span', { className: 'gb-combos-dot', 'aria-hidden': 'true', textContent: '\u25CF' }));
                }
                tr.appendChild(td);
            });
            tr.appendChild(h('td', { className: 'gb-combos-pts-cell', textContent: '1/3' }));
        }
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    body.appendChild(table);

    // Points legend
    body.appendChild(h('div', { className: 'gb-combos-legend' },
        'Single = 1pt, Double (2\u00D7 same spirit) = 3pts'
    ));

    // --- Cocktail recipes ---
    const cocktailTitle = h('div', { className: 'gb-combos-section-title', textContent: 'Cocktails' });
    body.appendChild(cocktailTitle);

    const cocktailList = h('div', { className: 'gb-combos-cocktails' });
    recipes.forEach(r => {
        const row = h('div', { className: 'gb-combos-cocktail-row' });

        // Name + points
        const nameSpan = h('span', { className: 'gb-combos-cocktail-name' },
            r.name);
        const ptsSpan = h('span', { className: 'gb-combos-cocktail-pts', textContent: `${r.points}pts` });
        row.appendChild(nameSpan);
        row.appendChild(ptsSpan);

        // Ingredients
        const ings = h('span', { className: 'gb-combos-cocktail-ings' });
        // Spirits
        for (const [sp, count] of Object.entries(r.spirits)) {
            const label = count > 1 ? `${count}\u00D7` : '';
            ings.appendChild(h('span', { className: 'gb-combos-ing spirit', textContent: `${label}${ingredientIcon(sp)}` }));
        }
        // Mixers
        for (const [mx, count] of Object.entries(r.mixers)) {
            const label = count > 1 ? `${count}\u00D7` : '';
            ings.appendChild(h('span', { className: 'gb-combos-ing mixer', textContent: `${label}${ingredientIcon(mx)}` }));
        }
        // Specials
        r.specials.forEach(sp => {
            ings.appendChild(h('span', { className: 'gb-combos-ing special', textContent: ingredientIcon(sp) }));
        });
        row.appendChild(ings);
        cocktailList.appendChild(row);
    });
    body.appendChild(cocktailList);

    root.appendChild(header);
    root.appendChild(body);
}

function renderActionButtons(isMyTurn, myState, game, gs) {
    // Wee button is now rendered inline in renderBladderWeeRow
}

// ─────────────────────────────────────────────────────────────
// Other players (compact read-only)
// ─────────────────────────────────────────────────────────────
function renderOthers(game, gs, isReplay) {
    const othersEl = el('gbOthers');
    othersEl.replaceChildren();

    const otherIds = (game.players || []).filter(pid => !S.me || pid !== S.me.id);
    otherIds.forEach(pid => {
        const pState = gs.player_states ? gs.player_states[pid] : null;
        const sheet = buildOtherSheet(pid, pState, gs);
        othersEl.appendChild(sheet);
    });
}

// Other player mat — same visual layout as my mat but read-only
function buildOtherSheet(pid, pState, gs) {
    const div = document.createElement('div');
    div.className = 'gb-other-sheet';
    div.setAttribute('aria-label', `${playerName(pid)}'s player mat`);
    div.dataset.playerId = pid;

    const isActive = gs.player_turn === pid;

    // Player strip (same style as my strip)
    const strip = document.createElement('div');
    strip.className = 'gb-player-strip ' + (isActive ? 'my-turn' : 'waiting');
    strip.setAttribute('aria-live', 'polite');
    if (isActive) strip.setAttribute('aria-label', `${playerName(pid)} — current turn`);

    const stripName = document.createElement('span');
    stripName.className = 'gb-player-strip-name';
    stripName.textContent = playerName(pid);
    strip.appendChild(stripName);

    if (isActive) {
        const tag = document.createElement('span');
        tag.className = 'gb-player-strip-turn-tag';
        tag.textContent = '▶ TURN';
        strip.appendChild(tag);
    }

    if (pState) {
        const karaokeTag = document.createElement('span');
        karaokeTag.className = 'gb-player-strip-karaoke';
        karaokeTag.textContent = `🎤 ${pState.karaoke_cards_claimed ?? 0}/3`;
        karaokeTag.title = 'Karaoke cards claimed';
        strip.appendChild(karaokeTag);
    }

    const scoreEl = document.createElement('span');
    scoreEl.className = 'gb-player-strip-score';
    scoreEl.textContent = `${pState ? (pState.points || 0) : '?'} / 40 pts`;
    strip.appendChild(scoreEl);
    div.appendChild(strip);

    if (!pState) {
        const body = document.createElement('div');
        body.className = 'gb-mat-body';
        const na = document.createElement('em');
        na.className = 'gb-no-data-text';
        na.textContent = 'No data';
        body.appendChild(na);
        div.appendChild(body);
        return div;
    }

    const body = document.createElement('div');
    body.className = 'gb-mat-body';

    // Stats row: drunk pips + compact text stats
    const statsRow = document.createElement('div');
    statsRow.className = 'gb-other-stats';

    // Drunk pips
    const drunkLevel = pState.drunk_level || 0;
    const drunkWrap = document.createElement('span');
    drunkWrap.className = 'gb-other-stat-drunk';
    drunkWrap.setAttribute('aria-label', `Drunk ${drunkLevel}/5`);
    const dMeter = document.createElement('div');
    dMeter.className = 'gb-drunk-meter';
    for (let i = 0; i < 5; i++) {
        const pip = document.createElement('span');
        pip.className = 'gb-drunk-pip' + (i < drunkLevel ? (drunkLevel >= 4 ? ' danger' : ' filled') : '');
        dMeter.appendChild(pip);
    }
    drunkWrap.appendChild(dMeter);
    statsRow.appendChild(drunkWrap);

    [
        `Cards: ${(pState.cards||[]).length}`,
    ].forEach(t => {
        const s = document.createElement('span');
        s.className = 'gb-stats-strip-stat';
        s.textContent = t;
        statsRow.appendChild(s);
    });
    body.appendChild(statsRow);

    // Bladder — physical slots
    const bladderStat = document.createElement('div');
    bladderStat.className = 'gb-other-bladder';
    const bLabel = document.createElement('strong');
    bLabel.className = 'gb-stat-label';
    bLabel.textContent = 'Bladder';
    bladderStat.appendChild(bLabel);
    const bladderContents = pState.bladder || [];
    const bCap = pState.bladder_capacity || 8;
    const bTokens = pState.toilet_tokens ?? 4;
    bladderStat.appendChild(makeBladderSlots(bladderContents, bCap, bTokens));
    body.appendChild(bladderStat);

    // Cups — physical 5-slot cups
    const cupsRow = document.createElement('div');
    cupsRow.className = 'gb-cups';

    [pState.cups?.[0] || {}, pState.cups?.[1] || {}].forEach((cupObj, i) => {
        const cup = cupObj.ingredients || [];
        const hasDoubler = !!(cupObj.has_cup_doubler);
        const cupEl = document.createElement('div');
        cupEl.className = 'gb-cup';
        cupEl.dataset.cupIndex = i;

        const title = document.createElement('div');
        title.className = 'gb-cup-title';
        title.append('🥂 ', h('span', null, `Cup ${i + 1}`));
        if (hasDoubler) {
            title.appendChild(h('span', { className: 'gb-cup-doubler-badge', title: 'Cup Doubler — ×2 non-cocktail pts', textContent: '×2' }));
        }
        cupEl.appendChild(title);

        const ingArea = document.createElement('div');
        ingArea.className = 'gb-cup-ingredients';
        for (let s = 0; s < MAX_SLOTS; s++) {
            const slot = document.createElement('div');
            if (s < cup.length) {
                const ing = cup[s];
                slot.className = 'gb-cup-slot filled';
                slot.appendChild(makeIngredientBadge(ing));
                slot.setAttribute('aria-label', ingredientLabel(ing));
            } else {
                slot.className = 'gb-cup-slot empty';
                slot.setAttribute('aria-hidden', 'true');
            }
            ingArea.appendChild(slot);
        }
        cupEl.appendChild(ingArea);
        cupsRow.appendChild(cupEl);
    });
    body.appendChild(cupsRow);

    // Specials
    const specials = pState.special_ingredients || [];
    if (specials.length > 0) {
        const specialTitle = document.createElement('div');
        specialTitle.className = 'gb-section-title';
        specialTitle.classList.add('gb-section-title--mt');
        specialTitle.textContent = 'Specials on Mat';
        body.appendChild(specialTitle);
        const specialRow = document.createElement('div');
        specialRow.className = 'gb-specials-row';
        specials.forEach(s => specialRow.appendChild(makeIngredientBadge(s)));
        body.appendChild(specialRow);
    }

    // Claimed cards (read-only)
    const cards = pState.cards || [];
    if (cards.length > 0) {
        const claimedTitle = document.createElement('div');
        claimedTitle.className = 'gb-section-title gb-section-title--mt';
        claimedTitle.textContent = 'Claimed Cards';
        body.appendChild(claimedTitle);
        cards.forEach(c => {
            const cardType = c.card_type || (c.is_karaoke ? 'karaoke' : 'store');
            const typeLabel = { karaoke: 'Karaoke', store: 'Store', refresher: 'Refresher', cup_doubler: 'Cup Doubler', specialist: 'Specialist' }[cardType] || cardType;
            const typeIcons = { karaoke: '🎤', store: '📦', refresher: '💧', cup_doubler: '🥂', specialist: '⭐' };
            const cardEl = document.createElement('div');
            cardEl.className = `gb-claimed-card ${cardType}`;

            const headerSpan = document.createElement('span');
            headerSpan.textContent = `${typeIcons[cardType] || ''} ${typeLabel}: ${c.name || typeLabel}`;
            cardEl.appendChild(headerSpan);

            if (c.spirit_type) {
                cardEl.appendChild(document.createTextNode(' '));
                cardEl.appendChild(makeIngredientBadge(c.spirit_type));
            } else if (c.mixer_type) {
                cardEl.appendChild(document.createTextNode(' '));
                cardEl.appendChild(makeIngredientBadge(c.mixer_type));
            }

            if (c.stored_spirits && c.stored_spirits.length > 0) {
                const stored = document.createElement('div');
                stored.className = 'gb-card-stored';
                const storedLabel = document.createElement('span');
                storedLabel.className = 'gb-card-stored-label';
                storedLabel.textContent = 'Stored: ';
                stored.appendChild(storedLabel);
                c.stored_spirits.forEach(s => {
                    stored.appendChild(makeIngredientBadge(s));
                });
                cardEl.appendChild(stored);
            }
            body.appendChild(cardEl);
        });
    }

    div.appendChild(body);
    return div;
}

// ─────────────────────────────────────────────────────────────
// Undo UI
// ─────────────────────────────────────────────────────────────
function renderUndoSection(game, isReplay) {
    const section = el('gbUndoSection');
    if (!section) return;
    if (isReplay || game.status !== 'STARTED') {
        section.classList.add('hidden');
        return;
    }
    section.classList.remove('hidden');

    const content = el('gbUndoContent');
    content.replaceChildren();

    if (S.pendingUndo && S.pendingUndo.status === 'pending') {
        // Show pending vote UI
        const info = document.createElement('div');
        info.className = 'gb-undo-info';
        info.textContent = `${playerName(S.pendingUndo.proposed_by)} proposed to undo turn ${S.pendingUndo.target_turn_number + 1}.`;
        content.appendChild(info);

        // Per-player vote status
        const voteMap = S.pendingUndo.votes || {};
        const votesEl = document.createElement('div');
        votesEl.className = 'gb-undo-votes';
        (game.players || []).forEach(pid => {
            const v = voteMap[pid];
            const row = document.createElement('div');
            row.className = 'gb-undo-vote-row';
            const icon = document.createElement('span');
            icon.className = 'gb-undo-vote-icon ' + (v === 'agree' ? 'agree' : v === 'disagree' ? 'disagree' : 'waiting');
            icon.textContent = v === 'agree' ? '✓' : v === 'disagree' ? '✗' : '…';
            row.appendChild(icon);
            const name = document.createElement('span');
            name.textContent = ' ' + playerName(pid);
            row.appendChild(name);
            votesEl.appendChild(row);
        });
        content.appendChild(votesEl);

        const alreadyVoted = S.me && (S.me.id in voteMap);

        const btns = document.createElement('div');
        btns.className = 'gb-undo-btns';

        if (!alreadyVoted) {
            const agreeBtn = document.createElement('button');
            agreeBtn.className = 'gb-undo-btn agree';
            agreeBtn.textContent = 'Agree';
            agreeBtn.setAttribute('aria-label', 'Vote to agree with undo');
            agreeBtn.onclick = () => voteUndo('agree', agreeBtn, disagreeBtn);
            btns.appendChild(agreeBtn);

            const disagreeBtn = document.createElement('button');
            disagreeBtn.className = 'gb-undo-btn disagree';
            disagreeBtn.textContent = 'Disagree';
            disagreeBtn.setAttribute('aria-label', 'Vote to disagree with undo');
            disagreeBtn.onclick = () => voteUndo('disagree', agreeBtn, disagreeBtn);
            btns.appendChild(disagreeBtn);
        } else {
            const voted = document.createElement('em');
            voted.className = 'gb-text-voted';
            voted.textContent = 'You have voted.';
            btns.appendChild(voted);
        }

        content.appendChild(btns);

        // Flash placeholder
        const flashEl = document.createElement('span');
        flashEl.id = 'gbUndoFlash';
        flashEl.className = 'gb-flash';
        content.appendChild(flashEl);
    } else {
        // Show propose undo button
        const canPropose = S.historyMoves && S.historyMoves.length > 0;
        const proposeBtn = document.createElement('button');
        proposeBtn.className = 'gb-undo-btn agree';
        proposeBtn.textContent = 'Propose Undo';
        proposeBtn.disabled = !canPropose;
        proposeBtn.setAttribute('aria-label', 'Propose to undo the last move');
        proposeBtn.onclick = () => proposeUndo(proposeBtn);
        content.appendChild(proposeBtn);

        const flashEl = document.createElement('span');
        flashEl.id = 'gbUndoFlash';
        flashEl.className = 'gb-flash';
        content.appendChild(flashEl);
    }
}

// ─────────────────────────────────────────────────────────────
// History / Replay
// ─────────────────────────────────────────────────────────────
async function refreshHistory() {
    if (!S.gameId) return;
    try {
        const resp = await fetch(`/v1/games/${S.gameId}/history`);
        if (!resp.ok) return;
        const data = await resp.json();
        S.historyMoves = data.moves || [];
        renderHistoryLog(S.historyMoves);
        buildReplayTurns(S.historyMoves);
    } catch (e) {
        console.warn('History fetch failed:', e);
    }
}

function renderHistoryLog(moves) {
    const log = el('gbHistoryLog');
    if (!log) return;
    log.replaceChildren();
    if (moves.length === 0) {
        const em = document.createElement('em');
        em.className = 'gb-history-empty';
        em.textContent = 'No moves yet.';
        log.appendChild(em);
        return;
    }
    // Show most recent first
    [...moves].reverse().forEach(move => {
        const wrapper = document.createElement('div');
        wrapper.className = 'gb-history-item';

        const entry = document.createElement('div');
        entry.className = 'gb-history-entry gb-history-expandable';
        entry.setAttribute('aria-expanded', 'false');
        entry.setAttribute('role', 'button');
        entry.setAttribute('tabindex', '0');
        entry.append(
            h('span', { className: 'gb-history-chevron', 'aria-hidden': 'true' }, '\u25B6'), ' ',
            h('span', { className: 'gb-history-turn' }, `Turn ${move.turn_number + 1}`), ' \u2022 ',
            h('span', { className: 'gb-history-player' }, playerName(move.player_id)), ' \u2022 ',
            h('span', { className: 'gb-history-action' }, formatAction(move)), ' ',
            h('span', { className: 'gb-history-time' }, formatTime(move.created_at))
        );

        const detail = document.createElement('div');
        detail.className = 'gb-history-detail';
        detail.setAttribute('aria-hidden', 'true');
        detail.appendChild(formatActionDetail(move));

        const toggle = () => {
            const expanded = entry.getAttribute('aria-expanded') === 'true';
            entry.setAttribute('aria-expanded', String(!expanded));
            entry.classList.toggle('expanded', !expanded);
            detail.setAttribute('aria-hidden', String(expanded));
            detail.classList.toggle('open', !expanded);
        };
        entry.addEventListener('click', toggle);
        entry.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
        });

        wrapper.appendChild(entry);
        wrapper.appendChild(detail);
        log.appendChild(wrapper);
    });
}

function formatAction(move) {
    const a = move.action || {};
    switch (a.type) {
        case 'take_ingredients': return 'Took ingredients';
        case 'sell_cup':         return `Sold cup ${(a.cup_index ?? '') + 1}`;
        case 'drink_cup':        return `Drank cup ${(a.cup_index ?? '') + 1}`;
        case 'go_for_a_wee':    return 'Went for a wee';
        case 'claim_card':       return `Claimed ${a.card_name || 'a card'}`;
        case 'refresh_card_row': return `Refreshed row ${a.row_position ?? ''}`;
        case 'undo':             return `Undo (turn ${(a.target_turn_number ?? 0) + 1})`;
        case 'draw_from_bag':    return 'Drew from bag';
        default:                 return a.type || '?';
    }
}

/** Returns a DocumentFragment with the detail content for a move. */
function formatActionDetail(move) {
    const a = move.action || {};
    switch (a.type) {
        case 'take_ingredients': return _detailTakeIngredients(a);
        case 'sell_cup':         return _detailSellCup(a);
        case 'drink_cup':        return _detailDrinkCup(a);
        case 'go_for_a_wee':    return _detailGoForAWee(a);
        case 'claim_card':       return _detailClaimCard(a);
        case 'refresh_card_row': return _detailRefreshCardRow(a);
        case 'undo':             return _frag(h('em', null, `Undid turn ${(a.target_turn_number ?? 0) + 1}`));
        case 'draw_from_bag':    return _frag(h('em', null, `Drew ${(a.drawn || []).length} item(s) from the bag`));
        default:                 return _frag(h('em', null, 'No details available'));
    }
}

/** Wrap one or more nodes in a DocumentFragment. */
function _frag(...nodes) {
    const f = document.createDocumentFragment();
    for (const n of nodes) f.appendChild(n);
    return f;
}

/** Build ingredient badge spans, returns a DocumentFragment. */
function _ingBadges(names) {
    if (!names || names.length === 0) return _frag(h('em', null, 'none'));
    const f = document.createDocumentFragment();
    names.forEach((n, i) => {
        if (i > 0) f.appendChild(text(' '));
        f.appendChild(h('span', { className: `gb-ingredient gb-ing-${ingredientKind(n)}` }, ingredientLabel(n)));
    });
    return f;
}

/** Build a detail row: label span + content fragment, returns a div element. */
function _detailRow(label, contentFrag) {
    const row = h('div', { className: 'gb-detail-row' },
        h('span', { className: 'gb-detail-label' }, label)
    );
    row.appendChild(contentFrag);
    return row;
}

function _specialBadges(specials) {
    const f = document.createDocumentFragment();
    specials.forEach((s, i) => {
        if (i > 0) f.appendChild(text(' '));
        f.appendChild(h('span', { className: 'gb-special-badge' }, s));
    });
    return f;
}

function _detailTakeIngredients(a) {
    const taken = a.taken || [];
    if (taken.length === 0) return _frag(h('em', null, 'No ingredients recorded'));
    const cups = [[], []];
    const drunk = [];
    const specials = [];
    taken.forEach(t => {
        if (t.disposition === 'cup') cups[t.cup_index || 0].push(t.ingredient);
        else if (t.disposition === 'drink') drunk.push(t.ingredient);
        else if (t.disposition === 'special') specials.push(t.special_type || t.ingredient);
    });
    const f = document.createDocumentFragment();
    if (cups[0].length) f.appendChild(_detailRow('Cup 1:', _ingBadges(cups[0])));
    if (cups[1].length) f.appendChild(_detailRow('Cup 2:', _ingBadges(cups[1])));
    if (drunk.length)   f.appendChild(_detailRow('Drank:', _ingBadges(drunk)));
    if (specials.length) f.appendChild(_detailRow('Special rolls:', _specialBadges(specials)));
    return f;
}

function _detailSellCup(a) {
    const cupNum = (a.cup_index ?? 0) + 1;
    const pts = a.points_earned ?? 0;
    const specials = a.declared_specials || [];
    const f = document.createDocumentFragment();
    f.appendChild(_detailRow(`Cup ${cupNum}:`, _ingBadges(a.ingredients)));
    if (specials.length) f.appendChild(_detailRow('Specials:', _specialBadges(specials)));
    f.appendChild(_detailRow('Earned:', _frag(h('span', { className: 'gb-points-badge' }, `+${pts} pts`))));
    return f;
}

function _detailDrinkCup(a) {
    const cupNum = (a.cup_index ?? 0) + 1;
    return _frag(_detailRow(`Cup ${cupNum}:`, _ingBadges(a.ingredients)));
}

function _detailGoForAWee(a) {
    const excreted = a.excreted || [];
    if (excreted.length === 0) return _frag(h('div', { className: 'gb-detail-row' }, h('em', null, 'Bladder was empty')));
    return _frag(_detailRow('Flushed:', _ingBadges(excreted)));
}

function _detailClaimCard(a) {
    const typeIcons = { karaoke: '\uD83C\uDFA4', store: '\uD83D\uDCE6', refresher: '\uD83D\uDCA7', cup_doubler: '\uD83E\uDD42', specialist: '\u2B50' };
    const typeLabels = { karaoke: 'Karaoke', store: 'Store', refresher: 'Refresher', cup_doubler: 'Cup Doubler', specialist: 'Specialist' };
    const icon = typeIcons[a.card_type] || '';
    const typeLabel = typeLabels[a.card_type] || a.card_type || '';
    const cardName = a.card_name || 'Unknown';
    const row = a.row_position ?? '?';
    return _frag(
        _detailRow('Card:', text(`${icon} ${cardName}`)),
        _detailRow('Type:', text(typeLabel)),
        _detailRow('Row:', text(String(row)))
    );
}

function _detailRefreshCardRow(a) {
    const row = a.row_position ?? '?';
    const n = a.cards_removed ?? '?';
    const content = document.createDocumentFragment();
    content.appendChild(text(`${row} \u2014 ${n} card${n !== 1 ? 's' : ''} swapped out`));
    return _frag(_detailRow('Row:', content));
}


function buildReplayTurns(moves) {
    // Unique turn numbers
    const turns = [...new Set(moves.map(m => m.turn_number))].sort((a,b) => a-b);
    S.replayTurns = turns;
    updateReplayLabel();
}

function updateReplayLabel() {
    const lbl = el('gbReplayLabel');
    const barLbl = el('gbReplayBarLabel');
    if (!S.replayMode) {
        const txt = `Turns: ${S.replayTurns.length}`;
        if (lbl) lbl.textContent = txt;
        if (barLbl) barLbl.textContent = txt;
        return;
    }
    const cur = S.replayTurns[S.replayCursor];
    const last = S.replayTurns[S.replayTurns.length - 1];
    const txt = `Turn ${(cur ?? 0) + 1} / ${(last ?? 0) + 1}`;
    if (lbl) lbl.textContent = txt;
    if (barLbl) barLbl.textContent = txt;
}

async function replayGo(direction) {
    if (S.replayTurns.length === 0) return;

    let newCursor = S.replayCursor;
    if (direction === 'first') { newCursor = 0; }
    else if (direction === 'prev') { newCursor = Math.max(0, S.replayCursor === -1 ? S.replayTurns.length - 1 : S.replayCursor - 1); }
    else if (direction === 'next') {
        if (S.replayCursor === -1) return; // already live
        if (S.replayCursor >= S.replayTurns.length - 1) {
            exitReplay();
            return;
        }
        newCursor = S.replayCursor + 1;
    }
    else if (direction === 'last') { exitReplay(); return; }

    await replayGoTo(newCursor);
}

async function replayGoTo(cursor) {
    S.replayCursor = cursor;
    S.replayMode = true;

    el('gbReplayBar').classList.add('visible');
    el('gbBoardPanel').classList.add('replay-mode');

    const turn = S.replayTurns[S.replayCursor];
    updateReplayLabel();
    renderReplayBarMoves(turn);
    clearReplayHighlights();

    // Update URL so this turn is shareable
    const sp = new URLSearchParams(window.location.search);
    sp.set('turn', turn + 1);  // 1-indexed for readability
    history.replaceState(null, '', `?${sp.toString()}`);

    // Fetch historical state
    try {
        const resp = await fetch(`/v1/games/${S.gameId}/history/${turn}`);
        if (!resp.ok) { showError('Failed to load replay state.'); return; }
        const data = await resp.json();
        const replayGs = data.game_state;
        if (replayGs && S.game) {
            renderAll(S.game, replayGs);
            applyReplayHighlights(S.historyMoves.filter(m => m.turn_number === turn));
        }
    } catch (e) {
        showError('Failed to load replay state.');
        console.error(e);
    }
}

function exitReplay() {
    S.replayMode = false;
    S.replayCursor = -1;
    el('gbReplayBar').classList.remove('visible');
    el('gbBoardPanel').classList.remove('replay-mode');
    clearReplayHighlights();
    updateReplayLabel();
    // Remove turn param from URL
    const spExit = new URLSearchParams(window.location.search);
    spExit.delete('turn');
    const qsExit = spExit.toString();
    history.replaceState(null, '', qsExit ? `?${qsExit}` : window.location.pathname);
    if (S.game) {
        renderAll(S.game);
        schedulePoll(S.game);
    }
}

function clearReplayHighlights() {
    document.querySelectorAll('.gb-replay-highlight').forEach(el => el.classList.remove('gb-replay-highlight'));
}

function _replayFindCup(playerId, cupIndex) {
    if (S.me && playerId === S.me.id) {
        const cupsEl = document.getElementById('gbMyCups');
        return cupsEl ? cupsEl.querySelector(`[data-cup-index="${cupIndex}"]`) : null;
    }
    const sheet = document.querySelector(`#gbOthers [data-player-id="${playerId}"]`);
    return sheet ? sheet.querySelector(`[data-cup-index="${cupIndex}"]`) : null;
}

function applyReplayHighlights(moves) {
    if (!moves || moves.length === 0) return;

    const dispEl = document.getElementById('gbOpenDisplay');
    const bagEl  = document.getElementById('gbBagCount');
    const rowsEl = document.getElementById('gbCardRows');

    moves.forEach(m => {
        const a = m.action || {};
        switch (a.type) {
            case 'draw_from_bag':
                if (bagEl) bagEl.classList.add('gb-replay-highlight');
                break;

            case 'take_ingredients': {
                const taken = a.taken || [];
                taken.forEach(t => {
                    if (t.source === 'display' && dispEl) {
                        // Highlight one badge per taken ingredient (by name), skipping already-highlighted ones
                        const badge = [...dispEl.querySelectorAll(`[data-ingredient="${t.ingredient}"]`)]
                            .find(b => !b.classList.contains('gb-replay-highlight'));
                        if (badge) badge.classList.add('gb-replay-highlight');
                    } else if ((t.source === 'pending' || t.source === 'bag') && bagEl) {
                        bagEl.classList.add('gb-replay-highlight');
                    }
                    if (t.disposition === 'cup') {
                        const cup = _replayFindCup(m.player_id, t.cup_index);
                        if (cup) cup.classList.add('gb-replay-highlight');
                    }
                });
                break;
            }

            case 'sell_cup':
            case 'drink_cup': {
                const cup = _replayFindCup(m.player_id, a.cup_index);
                if (cup) cup.classList.add('gb-replay-highlight');
                break;
            }

            case 'claim_card':
            case 'refresh_card_row':
                if (rowsEl) {
                    const row = rowsEl.querySelector(`[data-row-position="${a.row_position}"]`);
                    if (row) row.classList.add('gb-replay-highlight');
                }
                break;
        }
    });
}

function renderReplayBarMoves(turnNumber) {
    const container = el('gbReplayBarMoves');
    if (!container) return;
    const moves = S.historyMoves.filter(m => m.turn_number === turnNumber);
    if (moves.length === 0) {
        container.replaceChildren(h('em', { className: 'gb-no-data-text' }, 'No moves recorded for this turn'));
        return;
    }
    const frag = document.createDocumentFragment();
    for (const m of moves) {
        const card = h('div', { className: 'gb-replay-move-card' },
            h('div', { className: 'gb-replay-move-card-header' },
                h('strong', null, playerName(m.player_id)),
                h('span', { className: 'gb-replay-move-card-action' }, formatAction(m))
            ),
            h('div', { className: 'gb-replay-move-card-detail' })
        );
        card.querySelector('.gb-replay-move-card-detail').appendChild(formatActionDetail(m));
        frag.appendChild(card);
    }
    container.replaceChildren(frag);
}

// ─────────────────────────────────────────────────────────────
// Game actions
// ─────────────────────────────────────────────────────────────

/** POST to /v1/games/:id/actions/:action with JSON body */
async function gameAction(action, body = null) {
    const opts = {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : {},
    };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(`/v1/games/${S.gameId}/actions/${action}`, opts);
    if (resp.status === 401 || resp.status === 403) {
        window.location.href = '/';
        throw new Error('Unauthorized');
    }
    return resp;
}

async function doWee(tile) {
    if (tile) tile.classList.add('is-busy');
    clearError();
    try {
        const resp = await gameAction('go-for-a-wee');
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showError(d.detail || d.error || 'Failed to go for a wee.');
        } else {
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showError('Network error. Please try again.');
    } finally {
        if (tile) tile.classList.remove('is-busy');
    }
}

async function doClaimCard(card, cardEl) {
    const cardType = (card.card_type) || (card.is_karaoke ? 'karaoke' : 'store');

    if (cardType === 'cup_doubler') {
        openCupDoublerModal(card, cardEl);
        return;
    }

    if (cardEl) cardEl.classList.add('is-busy');
    clearError();
    try {
        const resp = await gameAction('claim-card', { card_id: card.id || card });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showError(d.detail || d.error || 'Cannot claim that card right now.');
        } else {
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showError('Network error. Please try again.');
    } finally {
        if (cardEl) cardEl.classList.remove('is-busy');
    }
}

function openCupDoublerModal(card, cardEl) {
    S.cupDoublerCard   = card;
    S.cupDoublerCardEl = cardEl;
    clearModalError('gbCupDoublerModalError');

    // Populate spirit dropdown with spirits that have >= 3 in bladder
    const spiritSel = el('gbCupDoublerSpiritSelect');
    spiritSel.replaceChildren();
    const bladder = (S.currentGs && S.me)
        ? (S.currentGs.player_states?.[S.me.id]?.bladder || [])
        : [];

    const countOf = s => bladder.filter(i => i === s).length;
    const eligible = [...SPIRITS].filter(s => countOf(s) >= 3);

    if (eligible.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'No spirit with ≥ 3 in bladder';
        spiritSel.appendChild(opt);
    } else {
        eligible.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s;
            opt.textContent = `${ingredientLabel(s)} (${countOf(s)} in bladder)`;
            spiritSel.appendChild(opt);
        });
    }

    openModal('gbCupDoublerModal');
}

function closeCupDoublerModal() {
    closeModal('gbCupDoublerModal');
    if (S.cupDoublerCardEl) S.cupDoublerCardEl.classList.remove('is-busy');
    S.cupDoublerCard   = null;
    S.cupDoublerCardEl = null;
}

async function confirmCupDoubler() {
    const card = S.cupDoublerCard;
    if (!card) return;

    const cupIndex   = parseInt(el('gbCupDoublerCupSelect').value, 10);
    const spiritType = el('gbCupDoublerSpiritSelect').value;
    if (!spiritType) { showModalError('gbCupDoublerModalError', 'You need at least 3 of the same spirit in your bladder.'); return; }

    const btn = el('gbCupDoublerConfirmBtn');
    setButtonBusy(btn, true, 'Claiming…');
    clearModalError('gbCupDoublerModalError');

    try {
        const resp = await gameAction('claim-card', { card_id: card.id, cup_index: cupIndex, spirit_type: spiritType });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showModalError('gbCupDoublerModalError', d.detail || d.error || 'Cannot claim that card right now.');
        } else {
            closeCupDoublerModal();
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showModalError('gbCupDoublerModalError', 'Network error. Please try again.');
    } finally {
        setButtonBusy(btn, false);
    }
}

async function doRefreshRow(rowPosition, btn) {
    setButtonBusy(btn, true, 'Refreshing…');
    clearError();
    try {
        const resp = await gameAction('refresh-card-row', { row_position: rowPosition });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showError(d.detail || d.error || 'Cannot refresh that row.');
        } else {
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showError('Network error. Please try again.');
    } finally {
        setButtonBusy(btn, false);
    }
}

function toggleStoredActions(cardDiv, cardIndex, card) {
    // If actions already shown, toggle off
    const existing = cardDiv.querySelector('.gb-store-card-actions');
    if (existing) {
        existing.remove();
        return;
    }
    // Close any other open store actions
    document.querySelectorAll('.gb-store-card-actions').forEach(el => el.remove());

    const actions = document.createElement('div');
    actions.className = 'gb-store-card-actions';

    const cup1Btn = document.createElement('button');
    cup1Btn.className = 'gb-store-action-btn use';
    cup1Btn.textContent = '\u2192 Cup 1';
    cup1Btn.setAttribute('aria-label', `Add stored ${ingredientLabel(card.spirit_type)} to Cup 1`);
    cup1Btn.onclick = (e) => { e.stopPropagation(); doUseStoredSpirit(cardIndex, 0, cup1Btn); };
    actions.appendChild(cup1Btn);

    const cup2Btn = document.createElement('button');
    cup2Btn.className = 'gb-store-action-btn use';
    cup2Btn.textContent = '\u2192 Cup 2';
    cup2Btn.setAttribute('aria-label', `Add stored ${ingredientLabel(card.spirit_type)} to Cup 2`);
    cup2Btn.onclick = (e) => { e.stopPropagation(); doUseStoredSpirit(cardIndex, 1, cup2Btn); };
    actions.appendChild(cup2Btn);

    const drinkBtn = document.createElement('button');
    drinkBtn.className = 'gb-store-action-btn drink';
    drinkBtn.textContent = 'Drink';
    drinkBtn.setAttribute('aria-label', `Drink a stored ${ingredientLabel(card.spirit_type)} spirit`);
    drinkBtn.onclick = (e) => { e.stopPropagation(); doDrinkStoredSpirit(cardIndex, card); };
    actions.appendChild(drinkBtn);

    cardDiv.appendChild(actions);
}

async function doDrinkStoredSpirit(cardIndex, card) {
    const spiritLabel = ingredientLabel(card.spirit_type);
    const storedCount = (card.stored_spirits || []).length;
    let count = 1;
    if (storedCount > 1) {
        const input = prompt(`How many ${spiritLabel} spirits to drink? (1-${storedCount})\nWarning: this will increase your drunk level!`, '1');
        if (input === null) return;
        count = parseInt(input, 10);
        if (isNaN(count) || count < 1 || count > storedCount) {
            showError(`Must drink between 1 and ${storedCount} spirits.`);
            return;
        }
    }
    clearError();
    try {
        const resp = await gameAction('drink-stored-spirit', { store_card_index: cardIndex, count });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showError(d.detail || d.error || 'Cannot drink stored spirits right now.');
        } else {
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showError('Network error. Please try again.');
    }
}

// openUseStoredSpiritModal / confirmUseStoredSpirit removed — now inline via doUseStoredSpirit

// ─────────────────────────────────────────────────────────────
// Take Ingredients modal
// ─────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────
// Inline Take Ingredients (staging area replaces modal)
// ─────────────────────────────────────────────────────────────

function _maybeAutoOpenStaging(game, gs, isReplay) {
    if (isReplay || !S.me || game.status !== 'STARTED') return;
    if (gs.player_turn !== S.me.id) return;
    const myState = gs.player_states?.[S.me.id];
    if (!myState) return;
    const totalLimit = myState.take_count || 3;
    const alreadyTaken = gs.ingredients_taken_this_turn || 0;
    const bagDrawPending = (gs.bag_draw_pending || []).length > 0;
    if (bagDrawPending) {
        // Re-hydrate pending bag draws into staging
        const serverPending = gs.bag_draw_pending || [];
        S.stagingItems = serverPending.map(ing => ({ ingredient: ing, source: 'pending', disposition: null, cup_index: null }));
        S.stagingActive = true;
        S.stagingTakeCount = totalLimit;
        S.stagingAlreadyTaken = alreadyTaken;
        renderStagingArea();
    } else if (alreadyTaken > 0 && alreadyTaken < totalLimit && S.stagingItems.length > 0) {
        S.stagingActive = true;
        renderStagingArea();
    }
}

/** Add a display ingredient to the staging area */
function addDisplayToStaging(ing, idx, myState, gs) {
    const totalLimit = myState.take_count || 3;
    const alreadyTaken = gs.ingredients_taken_this_turn || 0;
    const batchLimit = totalLimit - alreadyTaken;

    // Check if already selected
    if (S.stagingItems.some(s => s.source === 'display' && s.idx === idx)) {
        showError('Already selected that ingredient.');
        return;
    }

    if (S.stagingItems.length >= batchLimit) {
        showError(`You can only take ${batchLimit} ingredients this batch.`);
        return;
    }

    clearError();
    S.stagingItems.push({ ingredient: ing, source: 'display', idx, disposition: null, cup_index: null });
    S.stagingActive = true;
    S.stagingTakeCount = totalLimit;
    S.stagingAlreadyTaken = alreadyTaken;
    renderStagingArea();
}

/** Render the inline staging area */
function renderStagingArea() {
    const area = el('gbStagingArea');
    if (!area) return;

    const mat = el('gbMySheet');
    if (!S.stagingActive || S.stagingItems.length === 0) {
        area.classList.add('hidden');
        if (mat) mat.classList.remove('gb-staging-active');
        return;
    }
    area.classList.remove('hidden');
    if (mat) mat.classList.add('gb-staging-active');

    const batchLimit = S.stagingTakeCount - S.stagingAlreadyTaken;
    el('gbStagingCount').textContent = `${S.stagingItems.length} / ${batchLimit}`;

    const itemsEl = el('gbStagingItems');
    itemsEl.replaceChildren();

    const myState = S.me && S.game && S.game.game_state
        ? S.game.game_state.player_states[S.me.id]
        : null;
    const cup1Count = myState ? ((myState.cups?.[0]?.ingredients) || []).length : 0;
    const cup2Count = myState ? ((myState.cups?.[1]?.ingredients) || []).length : 0;

    S.stagingItems.forEach((item, i) => {
        const row = document.createElement('div');
        row.className = 'gb-staging-item';

        // Ingredient badge
        const badge = makeIngredientBadge(item.ingredient);
        row.appendChild(badge);

        const src = document.createElement('span');
        src.className = 'gb-staging-src';
        src.textContent = item.source === 'pending' ? '(bag)' : '(display)';
        row.appendChild(src);

        const kind = ingredientKind(item.ingredient);

        if (kind === 'special') {
            const note = document.createElement('em');
            note.className = 'gb-staging-note';
            note.textContent = 'Special \u2014 auto-placed on mat';
            row.appendChild(note);
            item.disposition = 'drink'; // Server handles special resolution
            item.cup_index = null;
        } else {
            // Assignment buttons: Cup 1, Cup 2, Drink
            const btns = document.createElement('div');
            btns.className = 'gb-staging-assign-btns';

            if (cup1Count < 5) {
                const c1 = h('button', {
                    className: 'gb-staging-assign-btn' + (item.disposition === 'cup' && item.cup_index === 0 ? ' active' : ''),
                    textContent: 'Cup 1',
                });
                c1.onclick = () => { item.disposition = 'cup'; item.cup_index = 0; renderStagingArea(); };
                btns.appendChild(c1);
            }
            if (cup2Count < 5) {
                const c2 = h('button', {
                    className: 'gb-staging-assign-btn' + (item.disposition === 'cup' && item.cup_index === 1 ? ' active' : ''),
                    textContent: 'Cup 2',
                });
                c2.onclick = () => { item.disposition = 'cup'; item.cup_index = 1; renderStagingArea(); };
                btns.appendChild(c2);
            }
            const dk = h('button', {
                className: 'gb-staging-assign-btn drink' + (item.disposition === 'drink' ? ' active' : ''),
                textContent: 'Drink',
            });
            dk.onclick = () => { item.disposition = 'drink'; item.cup_index = null; renderStagingArea(); };
            btns.appendChild(dk);

            // Remove button (only for display items, not bag-drawn)
            if (item.source === 'display') {
                const rm = h('button', { className: 'gb-staging-remove', 'aria-label': 'Remove', textContent: '\u2715' });
                rm.onclick = () => {
                    S.stagingItems.splice(i, 1);
                    if (S.stagingItems.length === 0) S.stagingActive = false;
                    renderStagingArea();
                };
                btns.appendChild(rm);
            }

            row.appendChild(btns);
        }

        itemsEl.appendChild(row);
    });

    // Wire up submit/cancel
    const submitBtn = el('gbStagingSubmit');
    const cancelBtn = el('gbStagingCancel');

    // Hide cancel when all items are bag-drawn (can't cancel those)
    const hasBag = S.stagingItems.some(s => s.source === 'pending');
    const hasDisplay = S.stagingItems.some(s => s.source === 'display');
    cancelBtn.classList.toggle('hidden', hasBag && !hasDisplay);

    // Can submit only if all items have an assignment
    const allAssigned = S.stagingItems.every(item => item.disposition !== null);
    submitBtn.disabled = !allAssigned;
    submitBtn.onclick = submitStagingItems;
    cancelBtn.onclick = cancelStaging;
}

async function submitStagingItems() {
    const btn = el('gbStagingSubmit');
    setButtonBusy(btn, true, 'Submitting\u2026');
    clearError();

    const assignments = S.stagingItems.map(sel => {
        const a = {
            ingredient: sel.ingredient,
            source: sel.source,
            disposition: sel.disposition || 'cup',
        };
        if (sel.cup_index != null) a.cup_index = sel.cup_index;
        return a;
    });

    try {
        const resp = await gameAction('take-ingredients', { assignments });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showError(d.error || 'Failed to take ingredients.');
        } else {
            closeStaging();
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showError('Network error. Please try again.');
    } finally {
        setButtonBusy(btn, false);
    }
}

function cancelStaging() {
    // Can only cancel display-selected items; bag-drawn items must be assigned
    const hasBag = S.stagingItems.some(s => s.source === 'pending');
    if (hasBag) {
        showError('You must assign bag-drawn ingredients before cancelling.');
        return;
    }
    closeStaging();
}

function closeStaging() {
    S.stagingItems = [];
    S.stagingActive = false;
    const area = el('gbStagingArea');
    if (area) area.classList.add('hidden');
    const mat = el('gbMySheet');
    if (mat) mat.classList.remove('gb-staging-active');
}

// ─────────────────────────────────────────────────────────────
// Cocktail Menu modal (JS-rendered, grouped by specials)
// ─────────────────────────────────────────────────────────────
function openMenu() {
    renderMenuContent();
    openModal('gbMenuModal');
}
function closeMenu() { closeModal('gbMenuModal'); }

function renderMenuContent() {
    const container = el('gbMenuContent');
    if (!container) return;
    container.replaceChildren();

    const myState = (S.me && S.game && S.game.game_state)
        ? S.game.game_state.player_states?.[S.me.id]
        : null;
    const playerSpecials = myState ? (myState.special_ingredients || []) : [];
    const playerCups = myState ? (myState.cups || []) : [];
    const playerBladder = myState ? (myState.bladder || []) : [];

    // Count all ingredients the player has (cups + bladder + stored)
    const allIngredients = [];
    playerCups.forEach(cup => allIngredients.push(...(cup.ingredients || [])));
    allIngredients.push(...playerBladder);
    if (myState) {
        (myState.cards || []).forEach(c => {
            if (c.stored_spirits) allIngredients.push(...c.stored_spirits);
        });
    }
    const ingCounts = {};
    allIngredients.forEach(i => { const u = i.toUpperCase(); ingCounts[u] = (ingCounts[u] || 0) + 1; });
    const specialCounts = {};
    playerSpecials.forEach(s => { const l = s.toLowerCase(); specialCounts[l] = (specialCounts[l] || 0) + 1; });

    // Section 1: Specials & Cocktails grouped by special type
    const specialsSection = document.createElement('div');
    specialsSection.className = 'gb-modal-section';
    specialsSection.appendChild(h('div', { className: 'gb-modal-section-title' }, 'Specials & Cocktails'));

    const specialLabels = { bitters: 'Bitters', cointreau: 'Cointreau', lemon: 'Lemon', sugar: 'Sugar', vermouth: 'Vermouth' };
    const specialIcons = { bitters: '\u2728', cointreau: '\uD83C\uDF4A', lemon: '\uD83C\uDF4B', sugar: '\uD83C\uDF6C', vermouth: '\uD83C\uDF39' };

    SPECIAL_TYPES.forEach(spType => {
        const group = document.createElement('div');
        group.className = 'gb-menu-special-group';

        // Special header with slots
        const header = document.createElement('div');
        header.className = 'gb-menu-special-header';
        const owned = specialCounts[spType] || 0;

        header.appendChild(h('span', { className: 'gb-ingredient special gb-menu-special-name' },
            `${specialIcons[spType] || ''} ${specialLabels[spType]}`));

        // Slots showing how many player has
        const slots = document.createElement('span');
        slots.className = 'gb-menu-special-slots';
        for (let i = 0; i < 3; i++) {
            const slot = document.createElement('span');
            slot.className = 'gb-menu-special-slot' + (i < owned ? ' filled' : '');
            slot.textContent = i < owned ? '\u25CF' : '\u25CB';
            slots.appendChild(slot);
        }
        header.appendChild(slots);
        group.appendChild(header);

        // Cocktails using this special
        const cocktails = cocktailsForSpecial(spType);
        cocktails.forEach(recipe => {
            const row = document.createElement('div');
            row.className = 'gb-menu-cocktail-row';

            const name = h('span', { className: 'gb-menu-cocktail-name' }, recipe.name);
            const pts = h('span', { className: 'gb-menu-pts' }, `${recipe.points}pts`);

            const ingredients = document.createElement('span');
            ingredients.className = 'gb-menu-cocktail-ings';

            // Spirits
            for (const [spirit, count] of Object.entries(recipe.spirits)) {
                for (let i = 0; i < count; i++) {
                    const badge = makeIngredientBadge(spirit);
                    if (ingCounts[spirit] && ingCounts[spirit] > 0) badge.classList.add('gb-menu-has');
                    ingredients.appendChild(badge);
                }
            }
            // Mixers
            for (const [mixer, count] of Object.entries(recipe.mixers)) {
                for (let i = 0; i < count; i++) {
                    const badge = makeIngredientBadge(mixer);
                    if (ingCounts[mixer] && ingCounts[mixer] > 0) badge.classList.add('gb-menu-has');
                    ingredients.appendChild(badge);
                }
            }
            // Specials
            recipe.specials.forEach(sp => {
                const badge = makeIngredientBadge(sp);
                if (specialCounts[sp.toLowerCase()] && specialCounts[sp.toLowerCase()] > 0) badge.classList.add('gb-menu-has');
                ingredients.appendChild(badge);
            });

            row.append(name, ingredients, pts);
            group.appendChild(row);
        });

        specialsSection.appendChild(group);
    });
    container.appendChild(specialsSection);

    // Section 2: Simple drinks
    const simpleSection = document.createElement('div');
    simpleSection.className = 'gb-modal-section';
    simpleSection.appendChild(h('div', { className: 'gb-modal-section-title' }, 'Simple Drinks'));
    const simpleList = document.createElement('div');
    simpleList.className = 'gb-menu-simple-list';
    [
        { name: 'Tequila Slammer', desc: 'Exactly 2\xD7Tequila, no mixers, no specials', pts: '3' },
        { name: 'Double Spirit', desc: '2 spirits (same type) + \u22651 valid mixer', pts: '3' },
        { name: 'Single Spirit', desc: '1 spirit + \u22651 valid mixer', pts: '1' },
    ].forEach(d => {
        const row = document.createElement('div');
        row.className = 'gb-menu-simple-row';
        row.append(
            h('span', { className: 'gb-menu-simple-name' }, d.name),
            h('span', { className: 'gb-menu-simple-desc' }, d.desc),
            h('span', { className: 'gb-menu-pts' }, d.pts)
        );
        simpleList.appendChild(row);
    });
    simpleSection.appendChild(simpleList);
    container.appendChild(simpleSection);

    // Section 3: Valid pairings
    const pairSection = document.createElement('div');
    pairSection.className = 'gb-modal-section';
    pairSection.appendChild(h('div', { className: 'gb-modal-section-title' }, 'Valid Spirit \u2192 Mixer Pairings'));
    const pairings = document.createElement('div');
    pairings.className = 'gb-menu-pairings';
    const pairingData = getValidPairings();
    for (const spirit of ['VODKA', 'RUM', 'WHISKEY', 'GIN', 'TEQUILA']) {
        const row = document.createElement('div');
        row.className = 'gb-menu-pairing-row';
        row.appendChild(h('span', { className: 'gb-ingredient spirit gb-menu-spirit' }, ingredientLabel(spirit)));
        row.appendChild(h('span', { className: 'gb-menu-arrow' }, '\u2192'));
        const mixers = pairingData[spirit];
        if (mixers && mixers.size > 0) {
            for (const m of mixers) {
                row.appendChild(h('span', { className: 'gb-ingredient mixer' }, ingredientLabel(m)));
            }
        } else {
            row.appendChild(h('em', { className: 'gb-menu-slammer-note' }, 'Slammer only (no valid mixer)'));
        }
        pairings.appendChild(row);
    }
    pairSection.appendChild(pairings);
    container.appendChild(pairSection);
}

// ─────────────────────────────────────────────────────────────
// Rules modal
// ─────────────────────────────────────────────────────────────
function openRules() { openModal('gbRulesModal'); }
function closeRules() { closeModal('gbRulesModal'); }

// ─────────────────────────────────────────────────────────────
// Inline Sell Cup (no modal — auto-detects drink, single click)
// ─────────────────────────────────────────────────────────────
async function doSellCup(cupIndex, declaredSpecials, btn) {
    if (btn) setButtonBusy(btn, true, 'Selling\u2026');
    clearError();

    try {
        const resp = await gameAction('sell-cup', {
            cup_index: cupIndex,
            declared_specials: declaredSpecials,
        });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showError(d.detail || d.error || 'Cannot sell that cup.');
        } else {
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showError('Network error. Please try again.');
    } finally {
        if (btn) setButtonBusy(btn, false);
    }
}

// ─────────────────────────────────────────────────────────────
// Inline Drink Cup (no modal — single click)
// ─────────────────────────────────────────────────────────────
async function doDrinkCup(cupIndex, btn) {
    if (btn) setButtonBusy(btn, true, 'Drinking\u2026');
    clearError();

    try {
        const resp = await gameAction('drink-cup', { cup_index: cupIndex });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showError(d.detail || d.error || 'Cannot drink that cup.');
        } else {
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showError('Network error. Please try again.');
    } finally {
        if (btn) setButtonBusy(btn, false);
    }
}

// ─────────────────────────────────────────────────────────────
// Inline Use Stored Spirit (no modal — direct action)
// ─────────────────────────────────────────────────────────────
async function doUseStoredSpirit(cardIndex, cupIndex, btn) {
    if (btn) setButtonBusy(btn, true, '\u2026');
    clearError();
    try {
        const resp = await gameAction('use-stored-spirit', { store_card_index: cardIndex, cup_index: cupIndex });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showError(d.detail || d.error || 'Cannot use stored spirit right now.');
        } else {
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showError('Network error. Please try again.');
    } finally {
        if (btn) setButtonBusy(btn, false);
    }
}

// ─────────────────────────────────────────────────────────────
// Undo actions
// ─────────────────────────────────────────────────────────────
async function proposeUndo(btn) {
    setButtonBusy(btn, true, 'Proposing…');
    clearError();
    try {
        const resp = await fetch(`/v1/games/${S.gameId}/undo`, { method: 'POST' });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showError(d.detail || d.error || 'Failed to propose undo.');
        } else {
            const data = await resp.json();
            S.pendingUndo = data.undo_request || null;
            if (S.game) renderUndoSection(S.game, false);
        }
    } catch (e) {
        showError('Network error proposing undo.');
    } finally {
        setButtonBusy(btn, false);
    }
}

async function voteUndo(vote, agreeBtn, disagreeBtn) {
    if (!S.pendingUndo) return;
    const activeBtn = vote === 'agree' ? agreeBtn : disagreeBtn;
    setButtonBusy(agreeBtn, true);
    setButtonBusy(disagreeBtn, true);
    clearError();
    try {
        const resp = await fetch(`/v1/games/${S.gameId}/undo/vote`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ request_id: S.pendingUndo.id, vote }),
        });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showError(d.detail || d.error || 'Failed to vote on undo.');
            setButtonBusy(agreeBtn, false);
            setButtonBusy(disagreeBtn, false);
        } else {
            const data = await resp.json();
            const status = data.status;
            if (status === 'approved') {
                flash('gbUndoFlash', 'success', 'Undo applied!', 2000);
                S.pendingUndo = null;
                setTimeout(async () => { await refreshGame(); await refreshHistory(); }, 2100);
            } else if (status === 'rejected') {
                flash('gbUndoFlash', 'error', 'Undo rejected.', 2000);
                S.pendingUndo = null;
                setTimeout(async () => { await refreshGame(); }, 2100);
            } else {
                // Still pending — refresh from server to get updated vote counts
                await refreshGame();
            }
        }
    } catch (e) {
        showError('Network error voting on undo.');
        setButtonBusy(agreeBtn, false);
        setButtonBusy(disagreeBtn, false);
    }
}

// ─────────────────────────────────────────────────────────────
// Action bar (quick-nav + availability indicators)
// ─────────────────────────────────────────────────────────────
function renderActionBar(game, gs, isReplay) {
    const bar = el('gbActionBar');
    if (!bar) return;
    const isMyTurn = !isReplay && S.me && gs.player_turn === S.me.id && game.status === 'STARTED';
    if (!isMyTurn) {
        bar.classList.add('hidden');
        return;
    }
    bar.classList.remove('hidden');

    const myState = gs.player_states?.[S.me.id];
    if (!myState) return;

    const bladder = myState.bladder || [];
    const specials = myState.special_ingredients || [];
    const bagCount = (gs.bag_contents || []).length;
    const displayCount = (gs.open_display || []).length;
    const totalAvail = bagCount + displayCount;
    const takeCount = myState.take_count || 3;

    // Take: available if enough ingredients
    const takeBtn = el('gbActionTake');
    takeBtn.disabled = totalAvail < takeCount;
    takeBtn.onclick = () => {
        document.querySelector('.gb-bar-inline')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };

    // Sell: available if either cup has a valid drink
    const sellBtn = el('gbActionSell');
    const cup0 = (myState.cups?.[0]?.ingredients) || [];
    const cup1 = (myState.cups?.[1]?.ingredients) || [];
    const hasDoubler0 = !!(myState.cups?.[0]?.has_cup_doubler);
    const hasDoubler1 = !!(myState.cups?.[1]?.has_cup_doubler);
    const specSpiritTypes = (myState.cards || [])
        .filter(c => c.card_type === 'specialist' && c.spirit_type)
        .map(c => c.spirit_type);
    const canSell = detectBestDrink(cup0, specials, hasDoubler0, specSpiritTypes) || detectBestDrink(cup1, specials, hasDoubler1, specSpiritTypes);
    sellBtn.disabled = !canSell;
    sellBtn.onclick = () => {
        el('gbMyCups')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };

    // Drink: available if either cup is non-empty
    const drinkBtn = el('gbActionDrink');
    drinkBtn.disabled = cup0.length === 0 && cup1.length === 0;
    drinkBtn.onclick = () => {
        el('gbMyCups')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };

    // Wee: always available on your turn
    const weeBtn = el('gbActionWee');
    weeBtn.disabled = false;
    weeBtn.onclick = () => {
        el('gbBladderWeeRow')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };

    // Claim: available if any card is affordable
    const claimBtn = el('gbActionClaim');
    let canClaim = false;
    for (const row of (gs.card_rows || [])) {
        for (const card of (row.cards || [])) {
            if (canAffordCard(card, bladder, gs)) { canClaim = true; break; }
        }
        if (canClaim) break;
    }
    claimBtn.disabled = !canClaim;
    claimBtn.onclick = () => {
        el('gbCardRows')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };
}

// ─────────────────────────────────────────────────────────────
// Window exports for HTML onclick handlers
// ─────────────────────────────────────────────────────────────
Object.assign(window, {
    openMenu, closeMenu, openRules, closeRules,
    switchTab, replayGo, exitReplay,
    closeCupDoublerModal, confirmCupDoubler,
    showGameError: showError, clearGameError: clearError,
});

// Auto-start
load();
