/**
 * game.js — Bartenders of Corfu game board
 * Vanilla ES2022, no external dependencies.
 */

'use strict';

// ─────────────────────────────────────────────────────────────
// Global state
// ─────────────────────────────────────────────────────────────
let _gameId        = null;
let _game          = null;   // live game object from API
let _me            = null;   // current user {id, username}
let _players       = {};     // map pid → {id, username}
let _pollTimer     = null;
let _replayMode    = false;
let _replayTurns   = [];     // list of turn numbers from history
let _replayCursor  = -1;     // index into _replayTurns (-1 = live)
let _historyMoves  = [];     // cached moves from /history
let _pendingUndo   = null;   // current pending undo request object

// Modal state
let _takeStep           = 0;   // 0 = pick, 1 = assign
let _takeDisplaySelected = []; // [{ingredient, source:'display', idx}]
let _takeBagPending      = []; // [{ingredient, source:'pending'}] — server-confirmed draws
let _sellCupIndex        = null;
let _drinkCupIndex       = null;
let _cupDoublerCard      = null;
let _cupDoublerCardEl    = null;
let _currentGs           = null;  // latest rendered game state (for modal use)

// ─────────────────────────────────────────────────────────────
// Constants / helpers
// ─────────────────────────────────────────────────────────────
const SPIRITS  = new Set(['WHISKEY','RUM','VODKA','GIN','TEQUILA']);
const MIXERS   = new Set(['COLA','SODA','TONIC','CRANBERRY']);
// The API may return various casings; normalise for display only
const INGREDIENT_LABELS = {
    WHISKEY:'Whiskey', WHISKY:'Whisky',
    RUM:'Rum', VODKA:'Vodka', GIN:'Gin', TEQUILA:'Tequila',
    COLA:'Cola', SODA:'Soda Water', SODA_WATER:'Soda Water',
    TONIC:'Tonic Water', TONIC_WATER:'Tonic Water',
    CRANBERRY:'Cranberry',
    SPECIAL:'Special',
    BITTERS:'Bitters', COINTREAU:'Cointreau', LEMON:'Lemon',
    SUGAR:'Sugar', VERMOUTH:'Vermouth',
};

// Emoji icons for ingredients — quick visual recognition (BGA-style)
const INGREDIENT_ICONS = {
    WHISKEY:'🥃', WHISKY:'🥃',
    RUM:'🍾', VODKA:'🔮', GIN:'🌿', TEQUILA:'🌵',
    COLA:'🥤', SODA:'🫧', SODA_WATER:'🫧',
    TONIC:'🍶', TONIC_WATER:'🍶',
    CRANBERRY:'🫐',
    BITTERS:'✨', COINTREAU:'🍊', LEMON:'🍋',
    SUGAR:'🍬', VERMOUTH:'🌹',
    SPECIAL:'✨',
};

function ingredientLabel(name) {
    if (!name) return '?';
    return INGREDIENT_LABELS[name.toUpperCase()] || name;
}

function ingredientIcon(name) {
    if (!name) return '';
    return INGREDIENT_ICONS[name.toUpperCase()] || '';
}

function ingredientKind(name) {
    if (!name) return 'special';
    const u = name.toUpperCase();
    if (SPIRITS.has(u))  return 'spirit';
    if (MIXERS.has(u))   return 'mixer';
    return 'special';
}

/** Build a coloured ingredient token element (BGA-style raised token) */
function makeIngredientBadge(name) {
    const span = document.createElement('span');
    span.className = `gb-ingredient ${ingredientKind(name)}`;
    const icon = ingredientIcon(name);
    const label = ingredientLabel(name);
    span.textContent = icon ? `${icon} ${label}` : label;
    span.setAttribute('aria-label', label);
    span.title = label;
    return span;
}

/** Build a cost badge element */
function makeCostBadge(costItem) {
    // costItem: {kind: 'spirit'|'mixer'|'special'|'...' , count: N}
    const span = document.createElement('span');
    const kindNorm = (costItem.kind || '').toLowerCase();
    let cls = 'gb-cost-badge';
    if (kindNorm.includes('spirit'))  cls += ' spirit';
    else if (kindNorm.includes('mixer')) cls += ' mixer';
    else if (kindNorm.includes('special')) cls += ' special';
    span.className = cls;
    span.textContent = `${costItem.count}× ${costItem.kind}`;
    return span;
}

function el(id) { return document.getElementById(id); }

function closeAllCupOverlays() {
    document.querySelectorAll('.gb-cup-action-overlay').forEach(o => o.classList.add('hidden'));
}

// Close cup overlays when clicking outside a cup
document.addEventListener('click', e => {
    if (!e.target.closest('.gb-cup-interactive')) closeAllCupOverlays();
});

function showError(msg) {
    const bar = el('gbErrorBar');
    bar.textContent = msg;
    bar.classList.add('visible');
}

function clearError() {
    const bar = el('gbErrorBar');
    bar.textContent = '';
    bar.classList.remove('visible');
}

function showModalError(elId, msg) {
    const bar = el(elId);
    if (!bar) return;
    bar.textContent = msg;
    bar.classList.add('visible');
    bar.style.display = 'block';
}

function clearModalError(elId) {
    const bar = el(elId);
    if (!bar) return;
    bar.textContent = '';
    bar.classList.remove('visible');
    bar.style.display = 'none';
}

function setButtonBusy(btn, busy, originalText) {
    if (!btn) return;
    if (busy) {
        btn.disabled = true;
        btn._origText = btn.innerHTML;
        btn.innerHTML = `<span class="spinner" aria-hidden="true"></span>${originalText || 'Working…'}`;
    } else {
        btn.disabled = false;
        if (btn._origText) btn.innerHTML = btn._origText;
    }
}

function formatTime(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    } catch { return iso; }
}

function flash(elId, cssClass, msg, durationMs = 2500) {
    const container = el(elId);
    if (!container) return;
    container.className = `gb-flash ${cssClass}`;
    container.textContent = msg;
    setTimeout(() => { container.className = 'gb-flash'; container.textContent = ''; }, durationMs);
}

// ─────────────────────────────────────────────────────────────
// Tab switching (bottom panel)
// ─────────────────────────────────────────────────────────────
function switchTab(name) {
    ['history','replay'].forEach(t => {
        const btn = el(`gbTabBtn${t.charAt(0).toUpperCase()+t.slice(1)}`);
        const pane = el(`gbTab${t.charAt(0).toUpperCase()+t.slice(1)}`);
        const active = t === name;
        if (btn)  { btn.classList.toggle('active', active); btn.setAttribute('aria-selected', String(active)); }
        if (pane) { pane.classList.toggle('active', active); }
    });
}

// ─────────────────────────────────────────────────────────────
// Initial load + polling
// ─────────────────────────────────────────────────────────────
async function load() {
    const sp = new URLSearchParams(window.location.search);
    _gameId = sp.get('id');
    if (!_gameId) {
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
            _me = await meResp.json();
        }
    } catch (e) {
        console.warn('Could not fetch user details:', e);
    }

    await refreshGame();
    await refreshHistory();

    // Auto-enter replay if ?turn= is in the URL
    const turnParam = sp.get('turn');
    if (turnParam !== null && _replayTurns.length > 0) {
        const turnNumber = parseInt(turnParam, 10) - 1;  // convert display (1-indexed) to stored turn_number
        const cursor = _replayTurns.indexOf(turnNumber);
        if (cursor !== -1) await replayGoTo(cursor);
    }
}

async function refreshGame(quiet = false) {
    if (!quiet) clearError();
    try {
        const resp = await fetch(`/v1/games/${_gameId}`);
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
        _game = game;
        _pendingUndo = game.pending_undo || null;
        renderAll(game);
        schedulePoll(game);
    } catch (e) {
        if (!quiet) showError('Network error loading game. Retrying…');
        console.error(e);
        schedulePoll({ status: 'STARTED', game_state: {} });
    }
}

async function resolvePlayerNames(playerIds) {
    const toFetch = playerIds.filter(pid => !_players[pid]);
    if (toFetch.length === 0) return;
    await Promise.all(toFetch.map(async pid => {
        try {
            const r = await fetch(`/v1/users/${encodeURIComponent(pid)}`);
            if (r.ok) {
                const u = await r.json();
                _players[pid] = { id: pid, username: u.username || pid };
            } else {
                _players[pid] = { id: pid, username: pid.slice(0, 8) };
            }
        } catch {
            _players[pid] = { id: pid, username: pid.slice(0, 8) };
        }
    }));
}

function playerName(pid) {
    if (!pid) return 'Unknown';
    if (_players[pid]) return _players[pid].username;
    return pid.slice(0, 8);
}

function schedulePoll(game) {
    if (_pollTimer) clearTimeout(_pollTimer);
    if (_replayMode) return;  // pause polling while replaying
    if (!game || game.status !== 'STARTED') return;
    const gs = game.game_state || {};
    const myTurn = _me && gs.player_turn === _me.id;
    // Poll when it's not our turn, or when an undo vote is pending (any player needs updates)
    if (!myTurn || _pendingUndo) {
        _pollTimer = setTimeout(() => refreshGame(true), 3000);
    }
}

// ─────────────────────────────────────────────────────────────
// Master render — dispatches to sub-renderers
// ─────────────────────────────────────────────────────────────
function renderAll(game, replayState = null) {
    const gs = replayState || game.game_state || {};
    _currentGs = gs;
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
    if (_me && gs.player_states) {
        const myState = gs.player_states[_me.id];
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
        winnerBanner.textContent = `🏆 ${playerName(gs.winner)} wins! Congratulations!`;
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

    // Auto-open take modal if mid-taking (handles page refresh and batch continuation)
    _maybeAutoOpenTakeModal(game, gs, isReplay);
}

function renderAllStats(game, gs) {
    const bar = el('gbPlayerStatsBar');
    if (!bar) return;
    bar.innerHTML = '';
    const gameEnded = game.status === 'ENDED';
    (game.players || []).forEach(pid => {
        const pState = gs.player_states ? gs.player_states[pid] : null;
        const isMe = _me && pid === _me.id;
        const isActive = !gameEnded && gs.player_turn === pid;

        const strip = document.createElement('div');
        strip.className = 'gb-stats-strip' +
            (isActive ? ' active-turn' : '') +
            (isMe ? ' is-me' : '');

        const nameSpan = document.createElement('span');
        nameSpan.className = 'gb-stats-strip-name';
        nameSpan.textContent = playerName(pid);
        strip.appendChild(nameSpan);

        if (isActive) {
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
    const isMyTurn = _me && currentPlayer === _me.id;
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
    list.innerHTML = '';
    const isHost = _me && _me.id === game.host;
    (game.players || []).forEach(pid => {
        const entry = document.createElement('li');
        entry.className = 'player-entry';
        entry.style.cssText = 'display:flex;align-items:center;gap:8px;padding:4px 0;';

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
                    const resp = await fetch(`/v1/games/${_gameId}/players/${encodeURIComponent(pid)}`, { method: 'DELETE' });
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
    section.innerHTML = '';
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
        const resp = await fetch(`/v1/games/${_gameId}/start`, { method: 'POST' });
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
    if (_pollTimer) clearTimeout(_pollTimer);
    _pollTimer = setTimeout(() => refreshGame(true), 3000);
}

// ─────────────────────────────────────────────────────────────
// Bag visual (SVG drawstring bag)
// ─────────────────────────────────────────────────────────────
function renderBagVisual(bagCount, isMyTurn, myState, gs) {
    const existing = el('gbBagVisual');
    if (existing) existing.remove();

    const wrap = document.createElement('div');
    wrap.id = 'gbBagVisual';
    wrap.className = 'gb-bag-visual' + (isMyTurn ? ' interactive' : '');
    if (isMyTurn) {
        wrap.setAttribute('role', 'button');
        wrap.setAttribute('tabindex', '0');
        wrap.title = 'Click to draw from bag';
        wrap.onclick = () => openTakeModal(myState, gs);
        wrap.onkeydown = e => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openTakeModal(myState, gs); }
        };
    }
    wrap.innerHTML = `
        <svg class="gb-bag-svg" viewBox="0 0 80 90" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path d="M15 36 Q7 36 6 47 L10 76 Q10 82 17 82 L63 82 Q70 82 70 76 L74 47 Q73 36 65 36 Z"
                  fill="#7a3810" stroke="#4a1e06" stroke-width="1.5"/>
            <path d="M14 37 Q7 37 6.5 47 L10.5 76 Q10.5 81 17 81 L63 81 Q69.5 81 69.5 76 L73.5 47 Q73 37 66 37 Z"
                  fill="none" stroke="rgba(212,160,23,0.25)" stroke-width="1" stroke-dasharray="5,5"/>
            <rect x="25" y="19" width="30" height="19" rx="5" fill="#6a2f0e" stroke="#4a1e06" stroke-width="1.5"/>
            <path d="M27 30 Q40 25 53 30" fill="none" stroke="#d4a060" stroke-width="2.5" stroke-linecap="round"/>
            <path d="M32 26 Q27 16 25 21" fill="none" stroke="#d4a060" stroke-width="2.5" stroke-linecap="round"/>
            <path d="M48 26 Q53 16 55 21" fill="none" stroke="#d4a060" stroke-width="2.5" stroke-linecap="round"/>
            <circle cx="40" cy="25" r="3.5" fill="#d4a060"/>
            <path d="M21 47 Q20 62 22 74" fill="none" stroke="rgba(255,255,255,0.18)" stroke-width="5" stroke-linecap="round"/>
            <path d="M32 42 Q30 55 31 70" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="3" stroke-linecap="round"/>
        </svg>
        <div class="gb-bag-count-badge">${bagCount}</div>
        ${isMyTurn ? '<div class="gb-bag-hint">draw</div>' : ''}
    `;

    // Insert before gbBagCount
    const bagCountEl = el('gbBagCount');
    bagCountEl.parentNode.insertBefore(wrap, bagCountEl);
}

// ─────────────────────────────────────────────────────────────
// Board panel (open display + card rows)
// ─────────────────────────────────────────────────────────────
function renderBoard(game, gs, isReplay) {
    const isMyTurn = !isReplay && _me && gs.player_turn === _me.id && game.status === 'STARTED';
    const myState  = (_me && gs.player_states) ? gs.player_states[_me.id] : null;

    // Open display
    const dispEl = el('gbOpenDisplay');
    dispEl.innerHTML = '';
    const display = gs.open_display || [];
    if (display.length === 0) {
        const empty = document.createElement('em');
        empty.textContent = 'Empty';
        empty.style.fontSize = '0.9em';
        empty.style.color = '#c8a870';
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
                badge.onclick = () => openTakeModal(myState, gs);
                badge.onkeydown = e => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openTakeModal(myState, gs); }
                };
            }
            dispEl.appendChild(badge);
        });
    }

    // Bag visual + count
    const bagContents = gs.bag_contents || [];
    renderBagVisual(bagContents.length, isMyTurn, myState, gs);
    el('gbBagCount').textContent = `Deck: ${gs.deck_size ?? '?'} cards`;

    // Card rows
    const rowsEl = el('gbCardRows');
    rowsEl.innerHTML = '';
    const cardRows = gs.card_rows || [];
    const bladder  = myState ? (myState.bladder || []) : [];

    cardRows.forEach(row => {
        const rowWrap = document.createElement('div');
        rowWrap.setAttribute('role', 'listitem');
        rowWrap.dataset.rowPosition = row.position;

        const rowLabelRow = document.createElement('div');
        rowLabelRow.style.display = 'flex';
        rowLabelRow.style.alignItems = 'center';
        rowLabelRow.style.gap = '8px';
        rowLabelRow.style.marginBottom = '6px';

        const rowLabel = document.createElement('span');
        rowLabel.className = 'gb-card-row-label';
        rowLabel.textContent = `Row ${row.position}`;
        rowLabelRow.appendChild(rowLabel);

        // Refresh row button (needs drunk level >= 3; row 1 is karaoke row — never refreshable)
        const isMyTurn = _me && gs.player_turn === _me.id;
        const drunkLevel = myState ? (myState.drunk_level || 0) : 0;
        if (!isReplay && isMyTurn && drunkLevel >= 3 && row.position !== 1) {
            const refreshBtn = document.createElement('button');
            refreshBtn.className = 'gb-refresh-row-btn';
            refreshBtn.textContent = 'Refresh Row';
            refreshBtn.setAttribute('aria-label', `Refresh card row ${row.position}`);
            refreshBtn.onclick = () => doRefreshRow(row.position, refreshBtn);
            rowLabelRow.appendChild(refreshBtn);
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
            empty.style.fontSize = '0.78em';
            empty.style.color = '#8a5c2e';
            empty.textContent = 'No cards in this row';
            cardsRow.appendChild(empty);
        }

        rowWrap.appendChild(cardsRow);
        rowsEl.appendChild(rowWrap);
    });
}

function buildCardElement(card, bladder, canClaim, gs) {
    const cardType = card.card_type || (card.is_karaoke ? 'karaoke' : 'store');
    const affordable = canClaim && canAffordCard(card, bladder, gs);

    const cardEl = document.createElement('div');
    cardEl.className = `gb-card ${cardType}` + (affordable ? ' claimable' : '');
    cardEl.setAttribute('role', affordable ? 'button' : 'article');
    const typeLabel = { karaoke: 'Karaoke', store: 'Store', refresher: 'Refresher', cup_doubler: 'Cup Doubler' }[cardType] || cardType;
    const costDesc = _cardCostDesc(card);
    cardEl.setAttribute('aria-label', `${card.name || typeLabel}. ${costDesc}`);
    if (affordable) {
        cardEl.setAttribute('tabindex', '0');
        cardEl.onclick = () => doClaimCard(card, cardEl);
        cardEl.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); doClaimCard(card, cardEl); } };
    }

    const badge = document.createElement('span');
    badge.className = 'gb-card-type-badge';
    badge.textContent = typeLabel;
    cardEl.appendChild(badge);

    // Card name — shown with main's gb-card-id styling
    const idEl = document.createElement('div');
    idEl.className = 'gb-card-id';
    idEl.textContent = card.name || typeLabel;
    cardEl.appendChild(idEl);

    const subEl = document.createElement('div');
    subEl.className = 'gb-card-sub';
    if (card.spirit_type) subEl.textContent = ingredientLabel(card.spirit_type);
    else if (card.mixer_type) subEl.textContent = ingredientLabel(card.mixer_type);
    if (subEl.textContent) cardEl.appendChild(subEl);

    const costEl = document.createElement('div');
    costEl.className = 'gb-card-cost';
    costEl.textContent = costDesc;
    cardEl.appendChild(costEl);

    // Show stored spirits on store cards
    if (cardType === 'store' && card.stored_spirits && card.stored_spirits.length > 0) {
        const storedEl = document.createElement('div');
        storedEl.className = 'gb-card-stored';
        storedEl.textContent = `Stored: ${card.stored_spirits.map(ingredientLabel).join(', ')}`;
        cardEl.appendChild(storedEl);
    }

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
    return '';
}

function canAffordCard(card, bladder, gs) {
    const cardType = card.card_type || (card.is_karaoke ? 'karaoke' : 'store');
    const myState = (_me && gs && gs.player_states) ? gs.player_states[_me.id] : null;
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
    return false;
}

// ─────────────────────────────────────────────────────────────
// My player sheet
// ─────────────────────────────────────────────────────────────
function renderMySheet(game, gs, myState, isReplay) {
    const isMyTurn = _me && gs.player_turn === _me.id && game.status === 'STARTED';
    const gameEnded = game.status === 'ENDED';

    // BGA-style player strip
    const nameEl = el('gbMyName');
    nameEl.innerHTML = '';
    const strip = document.createElement('div');
    const stripClass = gameEnded ? 'game-ended' : (isMyTurn ? 'my-turn' : 'waiting');
    strip.className = `gb-player-strip ${stripClass}`;
    strip.setAttribute('aria-live', 'polite');

    const stripName = document.createElement('span');
    stripName.className = 'gb-player-strip-name';
    stripName.textContent = (_me && _me.username) ? _me.username : 'Me';
    strip.appendChild(stripName);

    if (isMyTurn && !gameEnded) {
        const tag = document.createElement('span');
        tag.className = 'gb-player-strip-turn-tag';
        tag.textContent = '▶ YOUR TURN';
        strip.appendChild(tag);
    }

    const score = document.createElement('span');
    score.className = 'gb-player-strip-score';
    score.textContent = `${myState.points || 0} / 40 pts`;
    strip.appendChild(score);

    nameEl.appendChild(strip);

    // Stats
    renderMyStats(myState, gs);

    // Cups
    renderMyCups(myState, isMyTurn && !isReplay, game, gs);

    // Special ingredients — only show section if non-empty
    const specialsEl = el('gbMySpecials');
    specialsEl.innerHTML = '';
    const specials = myState.special_ingredients || [];
    if (specials.length > 0) {
        const specialsTitle = document.createElement('div');
        specialsTitle.className = 'gb-section-title';
        specialsTitle.style.marginTop = '6px';
        specialsTitle.textContent = 'Specials on Mat';
        specialsEl.appendChild(specialsTitle);
        specials.forEach(s => specialsEl.appendChild(makeIngredientBadge(s)));
    }

    // Claimed cards — only show section if non-empty
    const claimedEl = el('gbMyClaimedCards');
    claimedEl.innerHTML = '';
    const cards = myState.cards || [];
    if (cards.length > 0) {
        const claimedTitle = document.createElement('div');
        claimedTitle.className = 'gb-section-title';
        claimedTitle.style.marginTop = '6px';
        claimedTitle.textContent = 'Claimed Cards';
        claimedEl.appendChild(claimedTitle);
        cards.forEach(c => {
            const cardType = c.card_type || (c.is_karaoke ? 'karaoke' : 'store');
            const typeLabel = { karaoke: 'Karaoke', store: 'Store', refresher: 'Refresher', cup_doubler: 'Cup Doubler' }[cardType] || cardType;
            const div = document.createElement('div');
            div.className = `gb-claimed-card ${cardType}`;
            div.title = c.id || '';
            const namePart = c.name || (c.id || '').slice(0, 8);
            const subPart = c.spirit_type ? ` (${ingredientLabel(c.spirit_type)})` : c.mixer_type ? ` (${ingredientLabel(c.mixer_type)})` : '';
            div.textContent = `${typeLabel}: ${namePart}${subPart}`;
            if (c.stored_spirits && c.stored_spirits.length > 0) {
                const stored = document.createElement('div');
                stored.className = 'gb-card-stored';
                stored.textContent = `Stored: ${c.stored_spirits.map(ingredientLabel).join(', ')}`;
                div.appendChild(stored);
            }
            claimedEl.appendChild(div);
        });
    }

    // Actions
    renderActionButtons(isMyTurn && !isReplay, myState, game, gs);
}

function renderMyStats(myState, gs) {
    const statsEl = el('gbMyStats');
    statsEl.innerHTML = '';

    // Drunk meter (pips only, no fraction label)
    const drunkLevel = myState.drunk_level || 0;
    const drunkStat = makeStat('Drunk', '');
    const meterEl = document.createElement('div');
    meterEl.className = 'gb-drunk-meter';
    meterEl.setAttribute('aria-label', `Drunk level ${drunkLevel} of 5`);
    for (let i = 0; i < 5; i++) {
        const pip = document.createElement('span');
        const filled = i < drunkLevel;
        pip.className = 'gb-drunk-pip' + (filled ? (drunkLevel >= 4 ? ' danger' : ' filled') : '');
        pip.setAttribute('aria-hidden', 'true');
        meterEl.appendChild(pip);
    }
    drunkStat.querySelector('strong').after(meterEl);
    statsEl.appendChild(drunkStat);

    // Bladder — physical slots (filled ingredients + empty + sealed by toilet tokens)
    const bladder = myState.bladder || [];
    const cap = myState.bladder_capacity || 8;
    const toiletTokens = myState.toilet_tokens ?? 4;
    const bladderStat = makeStat('Bladder', '');
    const slotsEl = makeBladderSlots(bladder, cap, toiletTokens);
    bladderStat.querySelector('strong').after(slotsEl);
    statsEl.appendChild(bladderStat);

    // Take count + Karaoke — compact
    statsEl.appendChild(makeStat('Must Take', myState.take_count ?? 3));
    statsEl.appendChild(makeStat('Karaoke', `${myState.karaoke_cards_claimed ?? 0}/3`));
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
    cupsEl.innerHTML = '';
    const MAX_SLOTS = 5;

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
        title.innerHTML = `🥂 <span>Cup ${index + 1}</span>`;
        if (hasDoubler) {
            const badge = document.createElement('span');
            badge.className = 'gb-cup-doubler-badge';
            badge.title = 'Cup Doubler active — non-cocktail drinks score ×2';
            badge.textContent = '×2';
            title.appendChild(badge);
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

        if (isMyTurn && contents.length > 0) {
            cupEl.classList.add('gb-cup-interactive');
            cupEl.setAttribute('role', 'button');
            cupEl.setAttribute('tabindex', '0');
            cupEl.title = 'Click to sell or drink';

            const overlay = document.createElement('div');
            overlay.className = 'gb-cup-action-overlay hidden';
            overlay.setAttribute('aria-label', `Actions for cup ${index + 1}`);

            const sellTile = document.createElement('div');
            sellTile.className = 'gb-cup-action-tile sell';
            sellTile.setAttribute('role', 'button');
            sellTile.setAttribute('tabindex', '0');
            sellTile.setAttribute('aria-label', `Sell cup ${index + 1}`);
            sellTile.innerHTML = `<span class="gb-cup-action-icon">💰</span><span class="gb-cup-action-label">Sell</span>`;
            sellTile.onclick = e => { e.stopPropagation(); closeAllCupOverlays(); openSellModal(index, contents, myState); };
            sellTile.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); closeAllCupOverlays(); openSellModal(index, contents, myState); } };
            overlay.appendChild(sellTile);

            const drinkTile = document.createElement('div');
            drinkTile.className = 'gb-cup-action-tile drink';
            drinkTile.setAttribute('role', 'button');
            drinkTile.setAttribute('tabindex', '0');
            drinkTile.setAttribute('aria-label', `Drink cup ${index + 1}`);
            drinkTile.innerHTML = `<span class="gb-cup-action-icon">🍺</span><span class="gb-cup-action-label">Drink</span>`;
            drinkTile.onclick = e => { e.stopPropagation(); closeAllCupOverlays(); openDrinkModal(index, contents); };
            drinkTile.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); closeAllCupOverlays(); openDrinkModal(index, contents); } };
            overlay.appendChild(drinkTile);

            cupEl.appendChild(overlay);

            cupEl.onclick = e => {
                const wasOpen = !overlay.classList.contains('hidden');
                closeAllCupOverlays();
                if (!wasOpen) overlay.classList.remove('hidden');
            };
            cupEl.onkeydown = e => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    const wasOpen = !overlay.classList.contains('hidden');
                    closeAllCupOverlays();
                    if (!wasOpen) overlay.classList.remove('hidden');
                }
            };
        }

        cupsEl.appendChild(cupEl);
    });
}

function renderActionButtons(isMyTurn, myState, game, gs) {
    // Render the wee tile in the dedicated container
    const weeContainer = el('gbWeeTile');
    if (!weeContainer) return;
    weeContainer.innerHTML = '';

    if (isMyTurn) {
        const tile = document.createElement('div');
        tile.className = 'gb-wee-tile';
        tile.setAttribute('role', 'button');
        tile.setAttribute('tabindex', '0');
        tile.setAttribute('aria-label', 'Go for a wee — empties bladder, sobers up 1 level');
        tile.innerHTML = `<span class="gb-wee-icon">🚽</span><span class="gb-wee-label">Go for a Wee</span>`;
        tile.onclick = () => doWee(tile);
        tile.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); doWee(tile); } };
        weeContainer.appendChild(tile);
    }
}

// ─────────────────────────────────────────────────────────────
// Other players (compact read-only)
// ─────────────────────────────────────────────────────────────
function renderOthers(game, gs, isReplay) {
    const othersEl = el('gbOthers');
    othersEl.innerHTML = '';

    const otherIds = (game.players || []).filter(pid => !_me || pid !== _me.id);
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

    const scoreEl = document.createElement('span');
    scoreEl.className = 'gb-player-strip-score';
    scoreEl.textContent = `${pState ? (pState.points || 0) : '?'} / 40 pts`;
    strip.appendChild(scoreEl);
    div.appendChild(strip);

    if (!pState) {
        const body = document.createElement('div');
        body.className = 'gb-mat-body';
        const na = document.createElement('em');
        na.style.fontSize = '0.75em';
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
        `Karaoke: ${pState.karaoke_cards_claimed||0}/3`,
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
    const MAX_SLOTS = 5;
    [pState.cups?.[0] || {}, pState.cups?.[1] || {}].forEach((cupObj, i) => {
        const cup = cupObj.ingredients || [];
        const hasDoubler = !!(cupObj.has_cup_doubler);
        const cupEl = document.createElement('div');
        cupEl.className = 'gb-cup';
        cupEl.dataset.cupIndex = i;

        const title = document.createElement('div');
        title.className = 'gb-cup-title';
        title.innerHTML = `🥂 <span>Cup ${i + 1}</span>`;
        if (hasDoubler) {
            const badge = document.createElement('span');
            badge.className = 'gb-cup-doubler-badge';
            badge.title = 'Cup Doubler — ×2 non-cocktail pts';
            badge.textContent = '×2';
            title.appendChild(badge);
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
        specialTitle.style.marginTop = '6px';
        specialTitle.textContent = 'Specials on Mat';
        body.appendChild(specialTitle);
        const specialRow = document.createElement('div');
        specialRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:3px;margin:2px 0 4px;';
        specials.forEach(s => specialRow.appendChild(makeIngredientBadge(s)));
        body.appendChild(specialRow);
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
    content.innerHTML = '';

    if (_pendingUndo && _pendingUndo.status === 'pending') {
        // Show pending vote UI
        const info = document.createElement('div');
        info.className = 'gb-undo-info';
        info.textContent = `${playerName(_pendingUndo.proposed_by)} proposed to undo turn ${_pendingUndo.target_turn_number + 1}.`;
        content.appendChild(info);

        // Per-player vote status
        const voteMap = _pendingUndo.votes || {};
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

        const alreadyVoted = _me && (_me.id in voteMap);

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
            voted.style.fontSize = '0.78em';
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
        const canPropose = _historyMoves && _historyMoves.length > 0;
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
    if (!_gameId) return;
    try {
        const resp = await fetch(`/v1/games/${_gameId}/history`);
        if (!resp.ok) return;
        const data = await resp.json();
        _historyMoves = data.moves || [];
        renderHistoryLog(_historyMoves);
        buildReplayTurns(_historyMoves);
    } catch (e) {
        console.warn('History fetch failed:', e);
    }
}

function renderHistoryLog(moves) {
    const log = el('gbHistoryLog');
    if (!log) return;
    log.innerHTML = '';
    if (moves.length === 0) {
        const em = document.createElement('em');
        em.style.fontSize = '0.8em';
        em.style.color = '#8a5c2e';
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
        entry.innerHTML =
            `<span class="gb-history-chevron" aria-hidden="true">&#9654;</span> ` +
            `<span class="gb-history-turn">Turn ${move.turn_number + 1}</span> &bull; ` +
            `<span class="gb-history-player">${escHtml(playerName(move.player_id))}</span> &bull; ` +
            `<span class="gb-history-action">${escHtml(formatAction(move))}</span> ` +
            `<span class="gb-history-time">${formatTime(move.created_at)}</span>`;

        const detail = document.createElement('div');
        detail.className = 'gb-history-detail';
        detail.setAttribute('aria-hidden', 'true');
        detail.innerHTML = formatActionDetail(move);

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
        case 'claim_card':       return 'Claimed a card';
        case 'refresh_card_row': return `Refreshed row ${a.row_position ?? ''}`;
        case 'undo':             return `Undo (turn ${(a.target_turn_number ?? 0) + 1})`;
        case 'draw_from_bag':    return 'Drew from bag';
        default:                 return a.type || '?';
    }
}

function formatActionDetail(move) {
    const a = move.action || {};
    switch (a.type) {
        case 'take_ingredients': return _detailTakeIngredients(a);
        case 'sell_cup':         return _detailSellCup(a);
        case 'drink_cup':        return _detailDrinkCup(a);
        case 'go_for_a_wee':    return _detailGoForAWee(a);
        case 'claim_card':       return _detailClaimCard(a);
        case 'refresh_card_row': return _detailRefreshCardRow(a);
        case 'undo':             return `<em>Undid turn ${(a.target_turn_number ?? 0) + 1}</em>`;
        case 'draw_from_bag':    return `<em>Drew ${(a.drawn || []).length} item(s) from the bag</em>`;
        default:                 return '<em>No details available</em>';
    }
}

function _ingBadgesHtml(names) {
    if (!names || names.length === 0) return '<em>none</em>';
    return names.map(n =>
        `<span class="gb-ingredient gb-ing-${ingredientKind(n)}">${escHtml(ingredientLabel(n))}</span>`
    ).join(' ');
}

function _detailRow(label, content) {
    return `<div class="gb-detail-row"><span class="gb-detail-label">${escHtml(label)}</span>${content}</div>`;
}

function _detailTakeIngredients(a) {
    const taken = a.taken || [];
    if (taken.length === 0) return '<em>No ingredients recorded</em>';
    const cups = [[], []];
    const drunk = [];
    const specials = [];
    taken.forEach(t => {
        if (t.disposition === 'cup') cups[t.cup_index || 0].push(t.ingredient);
        else if (t.disposition === 'drink') drunk.push(t.ingredient);
        else if (t.disposition === 'special') specials.push(t.special_type || t.ingredient);
    });
    const rows = [];
    if (cups[0].length) rows.push(_detailRow('Cup 1:', _ingBadgesHtml(cups[0])));
    if (cups[1].length) rows.push(_detailRow('Cup 2:', _ingBadgesHtml(cups[1])));
    if (drunk.length)   rows.push(_detailRow('Drank:', _ingBadgesHtml(drunk)));
    if (specials.length) rows.push(_detailRow('Special rolls:',
        specials.map(s => `<span class="gb-special-badge">${escHtml(s)}</span>`).join(' ')));
    return rows.join('');
}

function _detailSellCup(a) {
    const cupNum = (a.cup_index ?? 0) + 1;
    const pts = a.points_earned ?? 0;
    const specials = a.declared_specials || [];
    let html = _detailRow(`Cup ${cupNum}:`, _ingBadgesHtml(a.ingredients));
    if (specials.length) html += _detailRow('Specials:',
        specials.map(s => `<span class="gb-special-badge">${escHtml(s)}</span>`).join(' '));
    html += _detailRow('Earned:', `<span class="gb-points-badge">+${pts} pts</span>`);
    return html;
}

function _detailDrinkCup(a) {
    const cupNum = (a.cup_index ?? 0) + 1;
    return _detailRow(`Cup ${cupNum}:`, _ingBadgesHtml(a.ingredients));
}

function _detailGoForAWee(a) {
    const excreted = a.excreted || [];
    if (excreted.length === 0) return '<div class="gb-detail-row"><em>Bladder was empty</em></div>';
    return _detailRow('Flushed:', _ingBadgesHtml(excreted));
}

function _detailClaimCard(a) {
    const row = a.row_position ?? '?';
    const karaokeTag = a.is_karaoke
        ? ' <span class="gb-karaoke-badge">&#127908; Karaoke</span>' : '';
    return _detailRow('Row:', `${row}${karaokeTag}`);
}

function _detailRefreshCardRow(a) {
    const row = a.row_position ?? '?';
    const n = a.cards_removed ?? '?';
    return _detailRow('Row:', `${row} &mdash; ${n} card${n !== 1 ? 's' : ''} swapped out`);
}

function escHtml(str) {
    return String(str)
        .replace(/&/g,'&amp;')
        .replace(/</g,'&lt;')
        .replace(/>/g,'&gt;')
        .replace(/"/g,'&quot;');
}

function buildReplayTurns(moves) {
    // Unique turn numbers
    const turns = [...new Set(moves.map(m => m.turn_number))].sort((a,b) => a-b);
    _replayTurns = turns;
    updateReplayLabel();
}

function updateReplayLabel() {
    const lbl = el('gbReplayLabel');
    const barLbl = el('gbReplayBarLabel');
    if (!_replayMode) {
        const txt = `Turns: ${_replayTurns.length}`;
        if (lbl) lbl.textContent = txt;
        if (barLbl) barLbl.textContent = txt;
        return;
    }
    const cur = _replayTurns[_replayCursor];
    const last = _replayTurns[_replayTurns.length - 1];
    const txt = `Turn ${(cur ?? 0) + 1} / ${(last ?? 0) + 1}`;
    if (lbl) lbl.textContent = txt;
    if (barLbl) barLbl.textContent = txt;
}

async function replayGo(direction) {
    if (_replayTurns.length === 0) return;

    let newCursor = _replayCursor;
    if (direction === 'first') { newCursor = 0; }
    else if (direction === 'prev') { newCursor = Math.max(0, _replayCursor === -1 ? _replayTurns.length - 1 : _replayCursor - 1); }
    else if (direction === 'next') {
        if (_replayCursor === -1) return; // already live
        if (_replayCursor >= _replayTurns.length - 1) {
            exitReplay();
            return;
        }
        newCursor = _replayCursor + 1;
    }
    else if (direction === 'last') { exitReplay(); return; }

    await replayGoTo(newCursor);
}

async function replayGoTo(cursor) {
    _replayCursor = cursor;
    _replayMode = true;

    el('gbReplayBar').classList.add('visible');
    el('gbBoardPanel').classList.add('replay-mode');

    const turn = _replayTurns[_replayCursor];
    updateReplayLabel();
    renderReplayBarMoves(turn);
    clearReplayHighlights();

    // Update URL so this turn is shareable
    const sp = new URLSearchParams(window.location.search);
    sp.set('turn', turn + 1);  // 1-indexed for readability
    history.replaceState(null, '', `?${sp.toString()}`);

    // Fetch historical state
    try {
        const resp = await fetch(`/v1/games/${_gameId}/history/${turn}`);
        if (!resp.ok) { showError('Failed to load replay state.'); return; }
        const data = await resp.json();
        const replayGs = data.game_state;
        if (replayGs && _game) {
            renderAll(_game, replayGs);
            applyReplayHighlights(_historyMoves.filter(m => m.turn_number === turn));
        }
    } catch (e) {
        showError('Failed to load replay state.');
        console.error(e);
    }
}

function exitReplay() {
    _replayMode = false;
    _replayCursor = -1;
    el('gbReplayBar').classList.remove('visible');
    el('gbBoardPanel').classList.remove('replay-mode');
    clearReplayHighlights();
    updateReplayLabel();
    // Remove turn param from URL
    const spExit = new URLSearchParams(window.location.search);
    spExit.delete('turn');
    const qsExit = spExit.toString();
    history.replaceState(null, '', qsExit ? `?${qsExit}` : window.location.pathname);
    if (_game) {
        renderAll(_game);
        schedulePoll(_game);
    }
}

function clearReplayHighlights() {
    document.querySelectorAll('.gb-replay-highlight').forEach(el => el.classList.remove('gb-replay-highlight'));
}

function _replayFindCup(playerId, cupIndex) {
    if (_me && playerId === _me.id) {
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
    const moves = _historyMoves.filter(m => m.turn_number === turnNumber);
    if (moves.length === 0) {
        container.innerHTML = '<em style="opacity:0.6;font-size:0.8em">No moves recorded for this turn</em>';
        return;
    }
    container.innerHTML = moves.map(m =>
        `<div class="gb-replay-move-card">` +
        `<div class="gb-replay-move-card-header">` +
        `<strong>${escHtml(playerName(m.player_id))}</strong>` +
        `<span class="gb-replay-move-card-action">${escHtml(formatAction(m))}</span>` +
        `</div>` +
        `<div class="gb-replay-move-card-detail">${formatActionDetail(m)}</div>` +
        `</div>`
    ).join('');
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
    const resp = await fetch(`/v1/games/${_gameId}/actions/${action}`, opts);
    if (resp.status === 401 || resp.status === 403) {
        window.location.href = '/';
        throw new Error('Unauthorized');
    }
    return resp;
}

async function doWee(tile) {
    if (tile) { tile.style.pointerEvents = 'none'; tile.style.opacity = '0.6'; }
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
        if (tile) { tile.style.pointerEvents = ''; tile.style.opacity = ''; }
    }
}

async function doClaimCard(card, cardEl) {
    const cardType = (card.card_type) || (card.is_karaoke ? 'karaoke' : 'store');

    if (cardType === 'cup_doubler') {
        openCupDoublerModal(card, cardEl);
        return;
    }

    if (cardEl) { cardEl.style.pointerEvents = 'none'; cardEl.style.opacity = '0.6'; }
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
        if (cardEl) { cardEl.style.pointerEvents = ''; cardEl.style.opacity = ''; }
    }
}

function openCupDoublerModal(card, cardEl) {
    _cupDoublerCard   = card;
    _cupDoublerCardEl = cardEl;
    clearModalError('gbCupDoublerModalError');

    // Populate spirit dropdown with spirits that have >= 3 in bladder
    const spiritSel = el('gbCupDoublerSpiritSelect');
    spiritSel.innerHTML = '';
    const bladder = (_currentGs && _me)
        ? (_currentGs.player_states?.[_me.id]?.bladder || [])
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
    if (_cupDoublerCardEl) { _cupDoublerCardEl.style.pointerEvents = ''; _cupDoublerCardEl.style.opacity = ''; }
    _cupDoublerCard   = null;
    _cupDoublerCardEl = null;
}

async function confirmCupDoubler() {
    const card = _cupDoublerCard;
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

// ─────────────────────────────────────────────────────────────
// Take Ingredients modal
// ─────────────────────────────────────────────────────────────

function _maybeAutoOpenTakeModal(game, gs, isReplay) {
    if (isReplay || !_me || game.status !== 'STARTED') return;
    if (gs.player_turn !== _me.id) return;
    // Don't re-open if already visible
    const modal = el('gbTakeModal');
    if (modal && !modal.classList.contains('hidden')) return;
    const myState = gs.player_states?.[_me.id];
    if (!myState) return;
    const totalLimit = myState.take_count || 3;
    const alreadyTaken = gs.ingredients_taken_this_turn || 0;
    const bagDrawPending = (gs.bag_draw_pending || []).length > 0;
    if ((alreadyTaken > 0 && alreadyTaken < totalLimit) || bagDrawPending) {
        openTakeModal(myState, gs);
    }
}

function openTakeModal(myState, gs) {
    _takeStep = 0;
    _takeDisplaySelected = [];
    _takeBagPending = [];
    clearModalError('gbTakeModalError');

    const totalLimit = myState.take_count || 3;
    const alreadyTaken = gs.ingredients_taken_this_turn || 0;
    const batchLimit = totalLimit - alreadyTaken;

    // If the server already has pending bag draws (e.g. modal reopened mid-turn),
    // skip straight to assignment.
    const serverPending = gs.bag_draw_pending || [];
    if (serverPending.length > 0) {
        _takeBagPending = serverPending.map(ing => ({ ingredient: ing, source: 'pending' }));
        _openAssignStep(myState);
        openModal('gbTakeModal');
        return;
    }

    // ── Step 0: select ──────────────────────────────────────────
    el('gbTakeLimit').textContent = alreadyTaken > 0
        ? `${batchLimit} (${alreadyTaken}/${totalLimit} already taken this turn)`
        : batchLimit;
    el('gbTakeCount').textContent = 0;
    el('gbTakeStep0').classList.remove('hidden');
    el('gbTakeStep1').classList.add('hidden');
    el('gbTakeNextBtn').textContent = 'Next →';
    el('gbTakeNextBtn').disabled = false;
    updateStepDots(0);
    renderTakeModalCups(myState);

    // Display picks
    const pickDisplayEl = el('gbPickDisplay');
    pickDisplayEl.innerHTML = '';
    const display = gs.open_display || [];
    if (display.length === 0) {
        const em = document.createElement('em');
        em.style.fontSize = '0.78em'; em.style.color = '#8a5c2e';
        em.textContent = 'Display is empty';
        pickDisplayEl.appendChild(em);
    } else {
        display.forEach((ing, idx) => {
            pickDisplayEl.appendChild(_buildDisplayPickItem(ing, idx, batchLimit));
        });
    }

    // Bag draw controls
    const bagCount = (gs.bag_contents || []).length;
    el('gbBagPickInfo').textContent = `(${bagCount} in bag)`;
    el('gbPickBag').innerHTML = '';
    el('gbBagDrawStatus').textContent = '';

    const drawCountEl = el('gbBagDrawCount');
    drawCountEl.max = batchLimit;
    drawCountEl.min = 1;
    drawCountEl.value = Math.min(batchLimit, bagCount) || 1;
    drawCountEl.disabled = false;

    el('gbBtnDrawBag').disabled = bagCount === 0 || batchLimit === 0;
    el('gbBtnDrawBag').onclick = () => _doDrawFromBag(myState, batchLimit);

    _updateTakeCount();
    el('gbTakeStepLabel').textContent =
        `Step 1: Pick from the display and/or draw from the bag (up to ${batchLimit} total)`;
    openModal('gbTakeModal');
}

function _buildDisplayPickItem(ing, idx, batchLimit) {
    const item = document.createElement('button');
    item.className = `gb-pick-item ${ingredientKind(ing)}`;
    item.setAttribute('type', 'button');
    item.setAttribute('role', 'checkbox');
    item.setAttribute('aria-checked', 'false');
    item.setAttribute('aria-label', `${ingredientLabel(ing)} from display`);
    item.dataset.idx = idx;
    const badge = makeIngredientBadge(ing);
    badge.style.pointerEvents = 'none';
    item.appendChild(badge);
    item.onclick = () => {
        const isSelected = item.classList.contains('selected');
        const total = _takeDisplaySelected.length + _takeBagPending.length;
        if (!isSelected && total >= batchLimit) {
            showModalError('gbTakeModalError', `You can only take ${batchLimit} ingredients total.`);
            return;
        }
        clearModalError('gbTakeModalError');
        if (isSelected) {
            const pos = _takeDisplaySelected.findIndex(s => s.idx === idx);
            if (pos !== -1) _takeDisplaySelected.splice(pos, 1);
            item.classList.remove('selected');
            item.setAttribute('aria-checked', 'false');
        } else {
            _takeDisplaySelected.push({ ingredient: ing, source: 'display', idx });
            item.classList.add('selected');
            item.setAttribute('aria-checked', 'true');
        }
        _updateTakeCount();
    };
    return item;
}

async function _doDrawFromBag(myState, batchLimit) {
    const count = parseInt(el('gbBagDrawCount').value) || 0;
    const alreadySelected = _takeDisplaySelected.length + _takeBagPending.length;
    const remaining = batchLimit - alreadySelected;

    if (count < 1 || count > remaining) {
        showModalError('gbTakeModalError',
            `Enter a number between 1 and ${remaining} (you have ${alreadySelected} already selected).`);
        return;
    }

    clearModalError('gbTakeModalError');
    el('gbBtnDrawBag').disabled = true;
    el('gbBagDrawCount').disabled = true;
    el('gbBagDrawStatus').textContent = 'Drawing…';

    try {
        const resp = await gameAction('draw-from-bag', { count });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showModalError('gbTakeModalError', d.error || 'Failed to draw from bag.');
            el('gbBtnDrawBag').disabled = false;
            el('gbBagDrawCount').disabled = false;
            el('gbBagDrawStatus').textContent = '';
            return;
        }
        const data = await resp.json();
        const drawn = data.drawn || [];

        // Store as pending (server-confirmed, cannot be removed)
        _takeBagPending = drawn.map(ing => ({ ingredient: ing, source: 'pending' }));

        // Show drawn ingredients as locked badges
        const pickBagEl = el('gbPickBag');
        pickBagEl.innerHTML = '';
        drawn.forEach(ing => {
            const wrap = document.createElement('div');
            wrap.style.cssText = 'display:inline-flex;align-items:center;gap:3px;';
            const badge = makeIngredientBadge(ing);
            badge.title = `${ingredientLabel(ing)} (drawn from bag — locked)`;
            wrap.appendChild(badge);
            const lock = document.createElement('span');
            lock.textContent = '🔒';
            lock.style.cssText = 'font-size:0.7em;opacity:0.6;';
            wrap.appendChild(lock);
            pickBagEl.appendChild(wrap);
        });

        el('gbBagDrawStatus').textContent = `Drew ${drawn.length} ingredient${drawn.length !== 1 ? 's' : ''} — now assign them.`;
        _updateTakeCount();

    } catch (e) {
        if (e.message !== 'Unauthorized') showModalError('gbTakeModalError', 'Network error drawing from bag.');
        el('gbBtnDrawBag').disabled = false;
        el('gbBagDrawCount').disabled = false;
        el('gbBagDrawStatus').textContent = '';
    }
}

function _updateTakeCount() {
    el('gbTakeCount').textContent = _takeDisplaySelected.length + _takeBagPending.length;
}

function renderTakeModalCups(myState) {
    const cupsEl = el('gbTakeModalCups');
    if (!cupsEl) return;
    cupsEl.innerHTML = '';

    const label = document.createElement('div');
    label.style.cssText = 'font-weight:600;color:#6b3a0f;margin-bottom:4px;';
    label.textContent = 'Your cups:';
    cupsEl.appendChild(label);

    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:16px;flex-wrap:wrap;';

    [{ index: 0, label: 'Cup 1' }, { index: 1, label: 'Cup 2' }].forEach(({ index, label: cupLabel }) => {
        const cup = (myState.cups?.[index]?.ingredients) || [];
        const div = document.createElement('div');
        div.style.cssText = 'display:flex;align-items:center;gap:4px;flex-wrap:wrap;';
        const lbl = document.createElement('span');
        lbl.style.cssText = 'color:#6b3a0f;white-space:nowrap;';
        lbl.textContent = `${cupLabel} (${cup.length}/5): `;
        div.appendChild(lbl);
        if (cup.length === 0) {
            const em = document.createElement('em');
            em.style.color = '#8a5c2e';
            em.textContent = 'empty';
            div.appendChild(em);
        } else {
            cup.forEach(ing => {
                const b = makeIngredientBadge(ing);
                b.style.fontSize = '0.78em';
                div.appendChild(b);
            });
        }
        row.appendChild(div);
    });
    cupsEl.appendChild(row);
}

function updateStepDots(step) {
    [0, 1].forEach(i => {
        const dot = el(`gbTakeDot${i}`);
        if (!dot) return;
        dot.className = 'gb-step-dot' + (i < step ? ' done' : i === step ? ' active' : '');
    });
}

function takeModalNext() {
    if (_takeStep === 0) {
        const total = _takeDisplaySelected.length + _takeBagPending.length;
        if (total === 0) {
            showModalError('gbTakeModalError', 'Select at least one ingredient before continuing.');
            return;
        }
        clearModalError('gbTakeModalError');
        const myState = _me && _game && _game.game_state
            ? _game.game_state.player_states[_me.id]
            : null;
        _openAssignStep(myState);
    } else {
        submitTakeIngredients();
    }
}

function _openAssignStep(myState) {
    _takeStep = 1;
    el('gbTakeStep0').classList.add('hidden');
    el('gbTakeStep1').classList.remove('hidden');
    el('gbTakeNextBtn').textContent = 'Submit';
    updateStepDots(1);
    el('gbTakeStepLabel').textContent = 'Step 2: Decide what to do with each ingredient.';
    _buildAssignTable(myState);
}

function _buildAssignTable(myState) {
    const tbody = el('gbAssignTableBody');
    tbody.innerHTML = '';

    const cup1Count = myState ? ((myState.cups?.[0]?.ingredients) || []).length : 0;
    const cup2Count = myState ? ((myState.cups?.[1]?.ingredients) || []).length : 0;
    const CUP_MAX = 5;

    const allItems = [..._takeDisplaySelected, ..._takeBagPending];

    allItems.forEach((sel, i) => {
        const tr = document.createElement('tr');

        const tdIng = document.createElement('td');
        tdIng.appendChild(makeIngredientBadge(sel.ingredient));
        const srcLabel = document.createElement('span');
        srcLabel.style.cssText = 'font-size:0.7em;color:#8a5c2e;margin-left:4px;';
        srcLabel.textContent = sel.source === 'pending' ? '(bag)' : '(display)';
        tdIng.appendChild(srcLabel);
        tr.appendChild(tdIng);

        const tdAssign = document.createElement('td');
        const kind = ingredientKind(sel.ingredient);

        if (kind === 'special') {
            const note = document.createElement('em');
            note.style.fontSize = '0.82em';
            note.textContent = 'Auto-placed on mat (server rolls)';
            tdAssign.appendChild(note);
            sel.disposition = 'drink';
            sel.cup_index = null;
        } else {
            const select = document.createElement('select');
            select.setAttribute('aria-label', `Assign ${ingredientLabel(sel.ingredient)}`);
            select.id = `gbAssign_${i}`;

            const opts = [];
            if (cup1Count < CUP_MAX) opts.push({ val: 'cup:0', label: `Cup 1 (${cup1Count}/5)` });
            if (cup2Count < CUP_MAX) opts.push({ val: 'cup:1', label: `Cup 2 (${cup2Count}/5)` });
            opts.push({ val: 'drink', label: 'Drink it' });

            opts.forEach(o => {
                const opt = document.createElement('option');
                opt.value = o.val;
                opt.textContent = o.label;
                select.appendChild(opt);
            });

            if (opts.length > 0) {
                sel.disposition = opts[0].val.startsWith('cup') ? 'cup' : 'drink';
                sel.cup_index   = opts[0].val.startsWith('cup') ? parseInt(opts[0].val.split(':')[1]) : null;
            }

            select.onchange = () => {
                const v = select.value;
                if (v.startsWith('cup:')) {
                    sel.disposition = 'cup';
                    sel.cup_index   = parseInt(v.split(':')[1]);
                } else {
                    sel.disposition = 'drink';
                    sel.cup_index   = null;
                }
            };

            tdAssign.appendChild(select);
        }

        tr.appendChild(tdAssign);
        tbody.appendChild(tr);
    });
}

async function submitTakeIngredients() {
    clearModalError('gbTakeModalError');
    const btn = el('gbTakeNextBtn');
    setButtonBusy(btn, true, 'Submitting…');

    const allItems = [..._takeDisplaySelected, ..._takeBagPending];
    const assignments = allItems.map(sel => {
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
            showModalError('gbTakeModalError', d.error || 'Failed to take ingredients.');
        } else {
            closeTakeModal();
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showModalError('gbTakeModalError', 'Network error. Please try again.');
    } finally {
        setButtonBusy(btn, false);
    }
}

function closeTakeModal() {
    closeModal('gbTakeModal');
    _takeDisplaySelected = [];
    _takeBagPending = [];
    _takeStep = 0;
}

// ─────────────────────────────────────────────────────────────
// Cocktail Menu modal
// ─────────────────────────────────────────────────────────────
function openMenu() { openModal('gbMenuModal'); }
function closeMenu() { closeModal('gbMenuModal'); }

// ─────────────────────────────────────────────────────────────
// Rules modal
// ─────────────────────────────────────────────────────────────
function openRules() { openModal('gbRulesModal'); }
function closeRules() { closeModal('gbRulesModal'); }

// ─────────────────────────────────────────────────────────────
// Sell Cup modal
// ─────────────────────────────────────────────────────────────
function openSellModal(cupIndex, contents, myState) {
    _sellCupIndex = cupIndex;
    clearModalError('gbSellModalError');

    el('gbSellModalDesc').textContent = `Selling Cup ${cupIndex + 1}`;

    // Cup contents display
    const contentsEl = el('gbSellCupContents');
    contentsEl.innerHTML = '';
    contents.forEach(ing => contentsEl.appendChild(makeIngredientBadge(ing)));

    // Specials picker
    const specials = myState.special_ingredients || [];
    const pickerEl = el('gbSellSpecialsPicker');
    pickerEl.innerHTML = '';
    const section = el('gbSellSpecialsSection');

    if (specials.length === 0) {
        section.style.display = 'none';
    } else {
        section.style.display = '';
        specials.forEach((s, i) => {
            const item = document.createElement('button');
            item.className = `gb-pick-item special`;
            item.setAttribute('type', 'button');
            item.setAttribute('role', 'checkbox');
            item.setAttribute('aria-checked', 'false');
            item.setAttribute('aria-label', `Declare ${ingredientLabel(s)}`);
            item.dataset.special = s;
            item.appendChild(makeIngredientBadge(s));
            item.onclick = () => {
                const sel = item.classList.toggle('selected');
                item.setAttribute('aria-checked', String(sel));
            };
            pickerEl.appendChild(item);
        });
    }

    openModal('gbSellModal');
    el('gbSellConfirmBtn').disabled = false;
}

async function confirmSell() {
    clearModalError('gbSellModalError');
    const btn = el('gbSellConfirmBtn');
    setButtonBusy(btn, true, 'Selling…');

    const declaredSpecials = [];
    el('gbSellSpecialsPicker').querySelectorAll('.selected').forEach(item => {
        declaredSpecials.push(item.dataset.special);
    });

    try {
        const resp = await gameAction('sell-cup', {
            cup_index: _sellCupIndex,
            declared_specials: declaredSpecials,
        });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showModalError('gbSellModalError', d.detail || d.error || 'Cannot sell that cup.');
        } else {
            closeSellModal();
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showModalError('gbSellModalError', 'Network error. Please try again.');
    } finally {
        setButtonBusy(btn, false);
    }
}

function closeSellModal() {
    closeModal('gbSellModal');
    _sellCupIndex = null;
}

// ─────────────────────────────────────────────────────────────
// Drink Cup modal
// ─────────────────────────────────────────────────────────────
function openDrinkModal(cupIndex, contents) {
    _drinkCupIndex = cupIndex;
    clearModalError('gbDrinkModalError');

    el('gbDrinkModalTitle').textContent = `Drink Cup ${cupIndex + 1}`;
    const ingNames = contents.map(ingredientLabel).join(', ');
    const spiritCount = contents.filter(i => ingredientKind(i) === 'spirit').length;

    el('gbDrinkModalDesc').innerHTML =
        `Are you sure you want to drink Cup ${cupIndex + 1}?<br>` +
        `<strong>Contents:</strong> ${ingNames || 'empty'}<br>` +
        (spiritCount > 0
            ? `<span style="color:#b91c1c">Warning: contains ${spiritCount} spirit${spiritCount > 1 ? 's' : ''} — your drunk level will increase by ${spiritCount}!</span>`
            : `<span style="color:#4b7ca8">Mixers only — will sober you up.</span>`);

    openModal('gbDrinkModal');
    el('gbDrinkConfirmBtn').disabled = false;
}

async function confirmDrink() {
    clearModalError('gbDrinkModalError');
    const btn = el('gbDrinkConfirmBtn');
    setButtonBusy(btn, true, 'Drinking…');

    try {
        const resp = await gameAction('drink-cup', { cup_index: _drinkCupIndex });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showModalError('gbDrinkModalError', d.detail || d.error || 'Cannot drink that cup.');
        } else {
            closeDrinkModal();
            await refreshGame();
            await refreshHistory();
        }
    } catch (e) {
        if (e.message !== 'Unauthorized') showModalError('gbDrinkModalError', 'Network error. Please try again.');
    } finally {
        setButtonBusy(btn, false);
    }
}

function closeDrinkModal() {
    closeModal('gbDrinkModal');
    _drinkCupIndex = null;
}

// ─────────────────────────────────────────────────────────────
// Undo actions
// ─────────────────────────────────────────────────────────────
async function proposeUndo(btn) {
    setButtonBusy(btn, true, 'Proposing…');
    clearError();
    try {
        const resp = await fetch(`/v1/games/${_gameId}/undo`, { method: 'POST' });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            showError(d.detail || d.error || 'Failed to propose undo.');
        } else {
            const data = await resp.json();
            _pendingUndo = data.undo_request || null;
            if (_game) renderUndoSection(_game, false);
        }
    } catch (e) {
        showError('Network error proposing undo.');
    } finally {
        setButtonBusy(btn, false);
    }
}

async function voteUndo(vote, agreeBtn, disagreeBtn) {
    if (!_pendingUndo) return;
    const activeBtn = vote === 'agree' ? agreeBtn : disagreeBtn;
    setButtonBusy(agreeBtn, true);
    setButtonBusy(disagreeBtn, true);
    clearError();
    try {
        const resp = await fetch(`/v1/games/${_gameId}/undo/vote`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ request_id: _pendingUndo.id, vote }),
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
                _pendingUndo = null;
                setTimeout(async () => { await refreshGame(); await refreshHistory(); }, 2100);
            } else if (status === 'rejected') {
                flash('gbUndoFlash', 'error', 'Undo rejected.', 2000);
                _pendingUndo = null;
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
// Modal open/close helpers + focus trap
// ─────────────────────────────────────────────────────────────
function openModal(id) {
    const overlay = el(id);
    if (!overlay) return;
    overlay.classList.remove('hidden');
    overlay.style.display = 'flex';
    // Focus the modal itself
    setTimeout(() => {
        const focusable = overlay.querySelector('button:not([disabled]), select, [tabindex="0"]');
        if (focusable) focusable.focus();
        else overlay.focus();
    }, 30);

    // ESC to close
    overlay._escHandler = (e) => {
        if (e.key === 'Escape') closeModal(id);
    };
    document.addEventListener('keydown', overlay._escHandler);
}

function closeModal(id) {
    const overlay = el(id);
    if (!overlay) return;
    overlay.classList.add('hidden');
    overlay.style.display = '';
    if (overlay._escHandler) {
        document.removeEventListener('keydown', overlay._escHandler);
        overlay._escHandler = null;
    }
    // Return focus to bag visual if available
    const focusReturn = el('gbBagVisual');
    if (focusReturn) focusReturn.focus();
}

// ─────────────────────────────────────────────────────────────
// Backward-compat stubs (called from existing HTML scaffolding)
// ─────────────────────────────────────────────────────────────

// These were in the old game.js — keep stubs to avoid errors
function showGameError(msg) { showError(msg); }
function clearGameError()   { clearError(); }
