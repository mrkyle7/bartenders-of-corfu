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

function ingredientLabel(name) {
    if (!name) return '?';
    return INGREDIENT_LABELS[name.toUpperCase()] || name;
}

function ingredientKind(name) {
    if (!name) return 'special';
    const u = name.toUpperCase();
    if (SPIRITS.has(u))  return 'spirit';
    if (MIXERS.has(u))   return 'mixer';
    return 'special';
}

/** Build a coloured ingredient pill element */
function makeIngredientBadge(name) {
    const span = document.createElement('span');
    span.className = `gb-ingredient ${ingredientKind(name)}`;
    span.textContent = ingredientLabel(name);
    span.setAttribute('aria-label', ingredientLabel(name));
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
    if (!game || game.status !== 'STARTED') return;
    const gs = game.game_state || {};
    const myTurn = _me && gs.player_turn === _me.id;
    // Poll only when it's not our turn (opponent waiting), every 3s
    if (!myTurn) {
        _pollTimer = setTimeout(() => refreshGame(true), 3000);
    }
}

// ─────────────────────────────────────────────────────────────
// Master render — dispatches to sub-renderers
// ─────────────────────────────────────────────────────────────
function renderAll(game, replayState = null) {
    const gs = replayState || game.game_state || {};
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
        renderLobby(game);
        schedulePollLobby();
        return;
    }
    el('gbLobbyPanel').classList.add('hidden');

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
// Board panel (open display + card rows)
// ─────────────────────────────────────────────────────────────
function renderBoard(game, gs, isReplay) {
    // Open display
    const dispEl = el('gbOpenDisplay');
    dispEl.innerHTML = '';
    const display = gs.open_display || [];
    if (display.length === 0) {
        const empty = document.createElement('em');
        empty.textContent = 'Empty';
        empty.style.fontSize = '0.8em';
        empty.style.color = '#8a5c2e';
        dispEl.appendChild(empty);
    } else {
        display.forEach(ing => {
            const badge = makeIngredientBadge(ing);
            badge.setAttribute('role', 'listitem');
            dispEl.appendChild(badge);
        });
    }

    // Bag count
    const bagContents = gs.bag_contents || [];
    el('gbBagCount').textContent =
        `Bag: ${bagContents.length} ingredient${bagContents.length !== 1 ? 's' : ''} remaining  |  Deck: ${gs.deck_size ?? '?'} cards`;

    // Card rows
    const rowsEl = el('gbCardRows');
    rowsEl.innerHTML = '';
    const cardRows = gs.card_rows || [];
    const myState  = (_me && gs.player_states) ? gs.player_states[_me.id] : null;
    const bladder  = myState ? (myState.bladder || []) : [];

    cardRows.forEach(row => {
        const rowWrap = document.createElement('div');
        rowWrap.setAttribute('role', 'listitem');

        const rowLabelRow = document.createElement('div');
        rowLabelRow.style.display = 'flex';
        rowLabelRow.style.alignItems = 'center';
        rowLabelRow.style.gap = '8px';
        rowLabelRow.style.marginBottom = '6px';

        const rowLabel = document.createElement('span');
        rowLabel.className = 'gb-card-row-label';
        rowLabel.textContent = `Row ${row.position}`;
        rowLabelRow.appendChild(rowLabel);

        // Refresh row button (needs drunk level >= 3)
        const isMyTurn = _me && gs.player_turn === _me.id;
        const drunkLevel = myState ? (myState.drunk_level || 0) : 0;
        if (!isReplay && isMyTurn && drunkLevel >= 3) {
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
    // Determine if the player can afford this card
    const cost = card.cost || [];
    const affordable = canClaim && canAffordCard(cost, bladder);

    const cardEl = document.createElement('div');
    cardEl.className = 'gb-card' + (card.is_karaoke ? ' karaoke' : '') + (affordable ? ' claimable' : '');
    cardEl.setAttribute('role', affordable ? 'button' : 'article');
    cardEl.setAttribute('aria-label',
        `Card${card.is_karaoke ? ' (Karaoke)' : ''}. Cost: ${cost.map(c => `${c.count} ${c.kind}`).join(', ') || 'free'}`);
    if (affordable) {
        cardEl.setAttribute('tabindex', '0');
        cardEl.onclick = () => doClaimCard(card.id, cardEl);
        cardEl.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); doClaimCard(card.id, cardEl); } };
    }

    if (card.is_karaoke) {
        const badge = document.createElement('span');
        badge.className = 'gb-card-karaoke-badge';
        badge.textContent = 'Karaoke';
        cardEl.appendChild(badge);
    }

    const idEl = document.createElement('div');
    idEl.className = 'gb-card-id';
    idEl.textContent = card.id ? card.id.slice(0, 8) : '—';
    cardEl.appendChild(idEl);

    if (cost.length > 0) {
        const costEl = document.createElement('div');
        costEl.className = 'gb-card-cost';
        cost.forEach(c => costEl.appendChild(makeCostBadge(c)));
        cardEl.appendChild(costEl);
    }

    return cardEl;
}

function canAffordCard(cost, bladder) {
    if (!cost || cost.length === 0) return true;
    // Count bladder contents by kind
    const counts = { spirit: 0, mixer: 0, special: 0 };
    bladder.forEach(ing => {
        counts[ingredientKind(ing)] = (counts[ingredientKind(ing)] || 0) + 1;
    });
    return cost.every(req => {
        const kind = (req.kind || '').toLowerCase();
        return (counts[kind] || 0) >= req.count;
    });
}

// ─────────────────────────────────────────────────────────────
// My player sheet
// ─────────────────────────────────────────────────────────────
function renderMySheet(game, gs, myState, isReplay) {
    const isMyTurn = _me && gs.player_turn === _me.id && game.status === 'STARTED';

    // Name
    const nameEl = el('gbMyName');
    nameEl.textContent = (_me && _me.username) ? _me.username : 'Me';
    nameEl.className = 'gb-sheet-name' + (isMyTurn ? ' active-turn' : '');

    // Stats
    renderMyStats(myState, gs);

    // Cups
    renderMyCups(myState, isMyTurn && !isReplay, game, gs);

    // Special ingredients
    const specialsEl = el('gbMySpecials');
    specialsEl.innerHTML = '';
    const specials = myState.special_ingredients || [];
    if (specials.length === 0) {
        const hint = document.createElement('em');
        hint.style.fontSize = '0.78em';
        hint.style.color = '#8a5c2e';
        hint.textContent = 'None';
        specialsEl.appendChild(hint);
    } else {
        specials.forEach(s => specialsEl.appendChild(makeIngredientBadge(s)));
    }

    // Claimed cards
    const claimedEl = el('gbMyClaimedCards');
    claimedEl.innerHTML = '';
    const cards = myState.cards || [];
    if (cards.length === 0) {
        const hint = document.createElement('em');
        hint.style.fontSize = '0.78em';
        hint.style.color = '#8a5c2e';
        hint.textContent = 'None';
        claimedEl.appendChild(hint);
    } else {
        cards.forEach(c => {
            const div = document.createElement('div');
            div.className = 'gb-claimed-card' + (c.is_karaoke ? ' karaoke' : '');
            div.textContent = c.is_karaoke ? `Karaoke: ${(c.id||'').slice(0,8)}` : (c.id || '').slice(0, 8);
            div.title = c.id || '';
            claimedEl.appendChild(div);
        });
    }

    // Actions
    renderActionButtons(isMyTurn && !isReplay, myState, game, gs);
}

function renderMyStats(myState, gs) {
    const statsEl = el('gbMyStats');
    statsEl.innerHTML = '';

    // Points
    statsEl.appendChild(makeStat('Points', myState.points || 0));

    // Drunk meter
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
    const drunkLabel = document.createElement('span');
    drunkLabel.style.fontSize = '0.75em';
    drunkLabel.style.marginLeft = '4px';
    drunkLabel.textContent = `${drunkLevel}/5`;
    meterEl.appendChild(drunkLabel);
    drunkStat.querySelector('strong').after(meterEl);
    statsEl.appendChild(drunkStat);

    // Bladder
    const bladder = myState.bladder || [];
    const cap = myState.bladder_capacity || 8;
    const pct = cap > 0 ? Math.min(bladder.length / cap, 1) : 0;
    const bladderStat = makeStat('Bladder', '');
    const barWrap = document.createElement('div');
    barWrap.style.display = 'flex';
    barWrap.style.alignItems = 'center';
    barWrap.style.gap = '4px';
    const bar = document.createElement('div');
    bar.className = 'gb-bladder-bar';
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-valuenow', bladder.length);
    bar.setAttribute('aria-valuemax', cap);
    bar.setAttribute('aria-label', `Bladder ${bladder.length} of ${cap}`);
    const fill = document.createElement('div');
    fill.className = 'gb-bladder-fill' + (pct >= 0.85 ? ' danger' : '');
    fill.style.width = `${Math.round(pct * 100)}%`;
    bar.appendChild(fill);
    barWrap.appendChild(bar);
    const bladderLabel = document.createElement('span');
    bladderLabel.style.fontSize = '0.75em';
    bladderLabel.textContent = `${bladder.length}/${cap}`;
    barWrap.appendChild(bladderLabel);
    bladderStat.querySelector('strong').after(barWrap);
    statsEl.appendChild(bladderStat);

    // Toilet tokens
    statsEl.appendChild(makeStat('Toilet Tokens', myState.toilet_tokens ?? 4));

    // Take count
    statsEl.appendChild(makeStat('Must Take', myState.take_count ?? 3));

    // Karaoke cards
    statsEl.appendChild(makeStat('Karaoke', `${myState.karaoke_cards_claimed ?? 0}/3`));
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

    // The API uses cup1, cup2 (arrays of ingredient names)
    const cupData = [
        { index: 0, contents: myState.cup1 || [] },
        { index: 1, contents: myState.cup2 || [] },
    ];

    cupData.forEach(({ index, contents }) => {
        const cupEl = document.createElement('div');
        cupEl.className = 'gb-cup';
        cupEl.setAttribute('aria-label', `Cup ${index + 1}`);

        const title = document.createElement('div');
        title.className = 'gb-cup-title';
        title.textContent = `Cup ${index + 1}`;
        cupEl.appendChild(title);

        const ingArea = document.createElement('div');
        ingArea.className = 'gb-cup-ingredients';
        if (contents.length === 0) {
            const hint = document.createElement('span');
            hint.className = 'gb-cup-empty-hint';
            hint.textContent = 'Empty';
            ingArea.appendChild(hint);
        } else {
            contents.forEach(ing => ingArea.appendChild(makeIngredientBadge(ing)));
        }
        cupEl.appendChild(ingArea);

        if (isMyTurn && contents.length > 0) {
            const actions = document.createElement('div');
            actions.className = 'gb-cup-actions';

            const sellBtn = document.createElement('button');
            sellBtn.className = 'gb-cup-btn sell';
            sellBtn.textContent = 'Sell';
            sellBtn.setAttribute('aria-label', `Sell cup ${index + 1}`);
            sellBtn.onclick = () => openSellModal(index, contents, myState);
            actions.appendChild(sellBtn);

            const drinkBtn = document.createElement('button');
            drinkBtn.className = 'gb-cup-btn drink';
            drinkBtn.textContent = 'Drink';
            drinkBtn.setAttribute('aria-label', `Drink contents of cup ${index + 1}`);
            drinkBtn.onclick = () => openDrinkModal(index, contents);
            actions.appendChild(drinkBtn);

            cupEl.appendChild(actions);
        }

        cupsEl.appendChild(cupEl);
    });
}

function renderActionButtons(isMyTurn, myState, game, gs) {
    const takeBtn = el('gbBtnTakeIngredients');
    const weeBtn  = el('gbBtnWee');

    if (!takeBtn || !weeBtn) return;

    takeBtn.disabled = !isMyTurn;
    weeBtn.disabled  = !isMyTurn;

    // Rebind handlers cleanly
    takeBtn.onclick = isMyTurn ? () => openTakeModal(myState, gs) : null;
    weeBtn.onclick  = isMyTurn ? () => doWee() : null;
}

// ─────────────────────────────────────────────────────────────
// Other players (compact read-only)
// ─────────────────────────────────────────────────────────────
function renderOthers(game, gs, isReplay) {
    const othersEl = el('gbOthers');
    othersEl.innerHTML = '';

    const otherIds = (game.players || []).filter(pid => !_me || pid !== _me.id);
    if (otherIds.length === 0) return;

    const heading = document.createElement('div');
    heading.className = 'gb-section-title';
    heading.textContent = 'Other Players';
    othersEl.appendChild(heading);

    otherIds.forEach(pid => {
        const pState = gs.player_states ? gs.player_states[pid] : null;
        const sheet = buildOtherSheet(pid, pState, gs);
        othersEl.appendChild(sheet);
    });
}

function buildOtherSheet(pid, pState, gs) {
    const div = document.createElement('div');
    div.className = 'gb-other-sheet';
    div.setAttribute('aria-label', `${playerName(pid)}'s player sheet`);

    const isActive = gs.player_turn === pid;
    const nameEl = document.createElement('div');
    nameEl.className = 'gb-other-sheet-name' + (isActive ? ' active-turn' : '');
    nameEl.textContent = playerName(pid);
    if (isActive) nameEl.setAttribute('aria-label', `${playerName(pid)} — current turn`);
    div.appendChild(nameEl);

    if (!pState) {
        const na = document.createElement('em');
        na.style.fontSize = '0.75em';
        na.textContent = 'No data';
        div.appendChild(na);
        return div;
    }

    const stats = document.createElement('div');
    stats.className = 'gb-other-stats';
    stats.innerHTML = `
        <span>Pts: <strong>${pState.points || 0}</strong></span>
        <span>Drunk: <strong>${pState.drunk_level || 0}/5</strong></span>
        <span>Bladder: <strong>${(pState.bladder||[]).length}/${pState.bladder_capacity||8}</strong></span>
        <span>Karaoke: <strong>${pState.karaoke_cards_claimed||0}/3</strong></span>
        <span>Cards: <strong>${(pState.cards||[]).length}</strong></span>
    `;
    div.appendChild(stats);

    // Compact cup display
    const cupRow = document.createElement('div');
    cupRow.className = 'gb-other-cup-row';
    [pState.cup1 || [], pState.cup2 || []].forEach((cup, i) => {
        const cupBadge = document.createElement('span');
        cupBadge.style.cssText = 'font-size:0.72em;color:#6b3a0f;margin-right:8px';
        cupBadge.textContent = `Cup${i+1}: `;
        cupRow.appendChild(cupBadge);
        if (cup.length === 0) {
            const e = document.createElement('em');
            e.style.cssText = 'font-size:0.72em;color:#8a5c2e';
            e.textContent = 'empty ';
            cupRow.appendChild(e);
        } else {
            cup.forEach(ing => {
                const b = makeIngredientBadge(ing);
                b.style.fontSize = '0.65em';
                b.style.padding = '1px 5px';
                cupRow.appendChild(b);
            });
        }
    });
    div.appendChild(cupRow);

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

    if (_pendingUndo && _pendingUndo.status === 'PENDING') {
        // Show pending vote UI
        const info = document.createElement('div');
        info.className = 'gb-undo-info';
        info.textContent = `${playerName(_pendingUndo.proposed_by)} proposed an undo.`;
        content.appendChild(info);

        const votes = document.createElement('div');
        votes.className = 'gb-undo-votes';
        votes.textContent =
            `Agree: ${(_pendingUndo.agree_votes || []).length}  •  ` +
            `Disagree: ${(_pendingUndo.disagree_votes || []).length}`;
        content.appendChild(votes);

        const alreadyVoted =
            (_me && (
                (_pendingUndo.agree_votes || []).includes(_me.id) ||
                (_pendingUndo.disagree_votes || []).includes(_me.id)
            ));

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
        const entry = document.createElement('div');
        entry.className = 'gb-history-entry';
        entry.innerHTML =
            `<span class="gb-history-turn">Turn ${move.turn_number}</span> &bull; ` +
            `<span class="gb-history-player">${escHtml(playerName(move.player_id))}</span> &bull; ` +
            `<span class="gb-history-action">${escHtml(formatAction(move))}</span> ` +
            `<span class="gb-history-time">${formatTime(move.created_at)}</span>`;
        log.appendChild(entry);
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
        default:                 return a.type || '?';
    }
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
    if (!lbl) return;
    if (!_replayMode) {
        lbl.textContent = `Turns: ${_replayTurns.length}`;
        return;
    }
    const cur = _replayTurns[_replayCursor];
    lbl.textContent = `Turn ${cur} / ${_replayTurns[_replayTurns.length - 1] || '?'}`;
}

async function replayGo(direction) {
    if (_replayTurns.length === 0) return;

    let newCursor = _replayCursor;
    if (direction === 'first') { newCursor = 0; }
    else if (direction === 'prev') { newCursor = Math.max(0, _replayCursor === -1 ? _replayTurns.length - 2 : _replayCursor - 1); }
    else if (direction === 'next') {
        if (_replayCursor === -1) return; // already live
        newCursor = Math.min(_replayTurns.length - 1, _replayCursor + 1);
        if (newCursor === _replayTurns.length - 1) {
            // At the last recorded turn — jump to live
            exitReplay();
            return;
        }
    }
    else if (direction === 'last') { exitReplay(); return; }

    _replayCursor = newCursor;
    _replayMode = true;

    el('gbReplayBanner').classList.add('visible');
    el('gbBoardPanel').classList.add('replay-mode');

    const turn = _replayTurns[_replayCursor];
    updateReplayLabel();

    // Fetch historical state
    try {
        const resp = await fetch(`/v1/games/${_gameId}/history/${turn}`);
        if (!resp.ok) { showError('Failed to load replay state.'); return; }
        const data = await resp.json();
        const replayGs = data.game_state;
        if (replayGs && _game) {
            renderAll(_game, replayGs);
        }
    } catch (e) {
        showError('Failed to load replay state.');
        console.error(e);
    }
}

function exitReplay() {
    _replayMode = false;
    _replayCursor = -1;
    el('gbReplayBanner').classList.remove('visible');
    el('gbBoardPanel').classList.remove('replay-mode');
    updateReplayLabel();
    if (_game) renderAll(_game);
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

async function doWee() {
    const btn = el('gbBtnWee');
    setButtonBusy(btn, true, 'Going…');
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
        setButtonBusy(btn, false);
    }
}

async function doClaimCard(cardId, cardEl) {
    if (cardEl) { cardEl.style.pointerEvents = 'none'; cardEl.style.opacity = '0.6'; }
    clearError();
    try {
        const resp = await gameAction('claim-card', { card_id: cardId });
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

    [{ key: 'cup1', label: 'Cup 1' }, { key: 'cup2', label: 'Cup 2' }].forEach(({ key, label: cupLabel }) => {
        const cup = myState[key] || [];
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

    const cup1Count = myState ? (myState.cup1 || []).length : 0;
    const cup2Count = myState ? (myState.cup2 || []).length : 0;
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
            const status = (data.undo_request || {}).status;
            if (status === 'APPROVED') {
                flash('gbUndoFlash', 'success', 'Undo applied!', 2000);
                _pendingUndo = null;
                setTimeout(async () => { await refreshGame(); await refreshHistory(); }, 2100);
            } else if (status === 'REJECTED') {
                flash('gbUndoFlash', 'error', 'Undo rejected.', 2000);
                _pendingUndo = null;
                setTimeout(() => { if (_game) renderUndoSection(_game, false); }, 2100);
            } else {
                _pendingUndo = data.undo_request || _pendingUndo;
                if (_game) renderUndoSection(_game, false);
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
    // Return focus to take button
    const focusReturn = el('gbBtnTakeIngredients');
    if (focusReturn && !focusReturn.disabled) focusReturn.focus();
}

// ─────────────────────────────────────────────────────────────
// Backward-compat stubs (called from existing HTML scaffolding)
// ─────────────────────────────────────────────────────────────

// These were in the old game.js — keep stubs to avoid errors
function showGameError(msg) { showError(msg); }
function clearGameError()   { clearError(); }
