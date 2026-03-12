/**
 * game.js — Bartenders of Corfu game board (entry point module).
 * Vanilla ES2022.
 */

import { SPIRITS, CARD_COST_TOKEN, CARD_COST_COUNT, MAX_SLOTS } from './constants.js';
import { ingredientLabel, ingredientIcon, ingredientKind, makeIngredientBadge, makeCostBadge } from './ingredients.js';
import { h, text, el, closeAllCupOverlays, showError, clearError, showModalError, clearModalError,
         setButtonBusy, formatTime, flash, switchTab, openModal, closeModal } from './dom.js';
import S from './state.js';

// Close cup overlays when clicking outside a cup
document.addEventListener('click', e => {
    if (!e.target.closest('.gb-cup-interactive')) closeAllCupOverlays();
});

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
        }
    } catch (e) {
        console.warn('Could not fetch user details:', e);
    }

    await refreshGame();
    await refreshHistory();

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
    bar.replaceChildren();
    const gameEnded = game.status === 'ENDED';
    (game.players || []).forEach(pid => {
        const pState = gs.player_states ? gs.player_states[pid] : null;
        const isMe = S.me && pid === S.me.id;
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
    const svgTmpl = document.getElementById('tmplBagSvg');
    if (svgTmpl) wrap.appendChild(svgTmpl.content.cloneNode(true));
    wrap.appendChild(h('div', { className: 'gb-bag-count-badge', textContent: String(bagCount) }));
    if (isMyTurn) wrap.appendChild(h('div', { className: 'gb-bag-hint', textContent: 'draw' }));

    // Insert before gbBagCount
    const bagCountEl = el('gbBagCount');
    bagCountEl.parentNode.insertBefore(wrap, bagCountEl);
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
    const typeLabel = { karaoke: 'Karaoke', store: 'Store', refresher: 'Refresher', cup_doubler: 'Cup Doubler' }[cardType] || cardType;
    const costDesc = _cardCostDesc(card);
    cardEl.setAttribute('aria-label', `${card.name || typeLabel}. ${costDesc}`);
    if (affordable) {
        cardEl.setAttribute('tabindex', '0');
        cardEl.onclick = () => doClaimCard(card, cardEl);
        cardEl.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); doClaimCard(card, cardEl); } };
    }

    // Header: name (left) + cost pill (right)
    const header = document.createElement('div');
    header.className = 'gb-card-header';

    const nameEl = document.createElement('span');
    nameEl.className = 'gb-card-name';
    nameEl.textContent = card.name || typeLabel;
    header.appendChild(nameEl);

    const costPill = document.createElement('span');
    costPill.className = `gb-card-cost-pill ${CARD_COST_TOKEN[cardType] || 'spirit'}`;
    costPill.textContent = `${CARD_COST_COUNT[cardType] ?? '?'}×`;
    header.appendChild(costPill);

    cardEl.appendChild(header);

    // Art: type icon
    const artEl = document.createElement('div');
    artEl.className = 'gb-card-art';
    const iconContent = _cloneCardIcon(cardType);
    if (iconContent) artEl.appendChild(iconContent);
    cardEl.appendChild(artEl);

    // Description: ingredient type + effect
    const descEl = document.createElement('div');
    descEl.className = 'gb-card-desc';
    const parts = [];
    if (card.spirit_type) parts.push(ingredientLabel(card.spirit_type));
    else if (card.mixer_type) parts.push(ingredientLabel(card.mixer_type));
    if (cardType === 'karaoke') parts.push('+5pts');
    else if (cardType === 'store') {
        const stored = card.stored_spirits ? card.stored_spirits.length : 0;
        parts.push(stored > 0 ? `stored:${stored}` : 'store');
    } else if (cardType === 'refresher') parts.push('+1pt');
    else if (cardType === 'cup_doubler') parts.push('2×cup');
    descEl.textContent = parts.join(' · ');
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
    const claimedEl = el('gbMyClaimedCards');
    claimedEl.replaceChildren();
    const cards = myState.cards || [];
    if (cards.length > 0) {
        const claimedTitle = document.createElement('div');
        claimedTitle.className = 'gb-section-title';
        claimedTitle.classList.add('gb-section-title--mt');
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
    statsEl.replaceChildren();

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
    cupsEl.replaceChildren();


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
        title.append('🥂 ', h('span', null, `Cup ${index + 1}`));
        if (hasDoubler) {
            title.appendChild(h('span', { className: 'gb-cup-doubler-badge', title: 'Cup Doubler active — non-cocktail drinks score ×2', textContent: '×2' }));
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
            sellTile.append(h('span', { className: 'gb-cup-action-icon' }, '💰'), h('span', { className: 'gb-cup-action-label' }, 'Sell'));
            sellTile.onclick = e => { e.stopPropagation(); closeAllCupOverlays(); openSellModal(index, contents, myState); };
            sellTile.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); closeAllCupOverlays(); openSellModal(index, contents, myState); } };
            overlay.appendChild(sellTile);

            const drinkTile = document.createElement('div');
            drinkTile.className = 'gb-cup-action-tile drink';
            drinkTile.setAttribute('role', 'button');
            drinkTile.setAttribute('tabindex', '0');
            drinkTile.setAttribute('aria-label', `Drink cup ${index + 1}`);
            drinkTile.append(h('span', { className: 'gb-cup-action-icon' }, '🍺'), h('span', { className: 'gb-cup-action-label' }, 'Drink'));
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
    weeContainer.replaceChildren();

    if (isMyTurn) {
        const tile = document.createElement('div');
        tile.className = 'gb-wee-tile';
        tile.setAttribute('role', 'button');
        tile.setAttribute('tabindex', '0');
        tile.setAttribute('aria-label', 'Go for a wee — empties bladder, sobers up 1 level');
        tile.append(h('span', { className: 'gb-wee-icon' }, '🚽'), h('span', { className: 'gb-wee-label' }, 'Go for a Wee'));
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
        case 'claim_card':       return 'Claimed a card';
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
    const row = a.row_position ?? '?';
    const content = document.createDocumentFragment();
    content.appendChild(text(String(row)));
    if (a.is_karaoke) {
        content.appendChild(text(' '));
        content.appendChild(h('span', { className: 'gb-karaoke-badge' }, '\uD83C\uDFA4 Karaoke'));
    }
    return _frag(_detailRow('Row:', content));
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

// ─────────────────────────────────────────────────────────────
// Take Ingredients modal
// ─────────────────────────────────────────────────────────────

function _maybeAutoOpenTakeModal(game, gs, isReplay) {
    if (isReplay || !S.me || game.status !== 'STARTED') return;
    if (gs.player_turn !== S.me.id) return;
    // Don't re-open if already visible
    const modal = el('gbTakeModal');
    if (modal && !modal.classList.contains('hidden')) return;
    const myState = gs.player_states?.[S.me.id];
    if (!myState) return;
    const totalLimit = myState.take_count || 3;
    const alreadyTaken = gs.ingredients_taken_this_turn || 0;
    const bagDrawPending = (gs.bag_draw_pending || []).length > 0;
    if ((alreadyTaken > 0 && alreadyTaken < totalLimit) || bagDrawPending) {
        openTakeModal(myState, gs);
    }
}

function openTakeModal(myState, gs) {
    S.takeStep = 0;
    S.takeDisplaySelected = [];
    S.takeBagPending = [];
    clearModalError('gbTakeModalError');

    const totalLimit = myState.take_count || 3;
    const alreadyTaken = gs.ingredients_taken_this_turn || 0;
    const batchLimit = totalLimit - alreadyTaken;

    // If the server already has pending bag draws (e.g. modal reopened mid-turn),
    // skip straight to assignment.
    const serverPending = gs.bag_draw_pending || [];
    if (serverPending.length > 0) {
        S.takeBagPending = serverPending.map(ing => ({ ingredient: ing, source: 'pending' }));
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
    pickDisplayEl.replaceChildren();
    const display = gs.open_display || [];
    if (display.length === 0) {
        const em = document.createElement('em');
        em.className = 'gb-empty-hint';
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
    el('gbPickBag').replaceChildren();
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
    badge.classList.add('gb-no-pointer');
    item.appendChild(badge);
    item.onclick = () => {
        const isSelected = item.classList.contains('selected');
        const total = S.takeDisplaySelected.length + S.takeBagPending.length;
        if (!isSelected && total >= batchLimit) {
            showModalError('gbTakeModalError', `You can only take ${batchLimit} ingredients total.`);
            return;
        }
        clearModalError('gbTakeModalError');
        if (isSelected) {
            const pos = S.takeDisplaySelected.findIndex(s => s.idx === idx);
            if (pos !== -1) S.takeDisplaySelected.splice(pos, 1);
            item.classList.remove('selected');
            item.setAttribute('aria-checked', 'false');
        } else {
            S.takeDisplaySelected.push({ ingredient: ing, source: 'display', idx });
            item.classList.add('selected');
            item.setAttribute('aria-checked', 'true');
        }
        _updateTakeCount();
    };
    return item;
}

async function _doDrawFromBag(myState, batchLimit) {
    const count = parseInt(el('gbBagDrawCount').value) || 0;
    const alreadySelected = S.takeDisplaySelected.length + S.takeBagPending.length;
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
        S.takeBagPending = drawn.map(ing => ({ ingredient: ing, source: 'pending' }));

        // Show drawn ingredients as locked badges
        const pickBagEl = el('gbPickBag');
        pickBagEl.replaceChildren();
        drawn.forEach(ing => {
            const wrap = document.createElement('div');
            wrap.className = 'gb-bag-drawn-wrap';
            const badge = makeIngredientBadge(ing);
            badge.title = `${ingredientLabel(ing)} (drawn from bag — locked)`;
            wrap.appendChild(badge);
            const lock = document.createElement('span');
            lock.textContent = '🔒';
            lock.className = 'gb-bag-drawn-lock';
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
    el('gbTakeCount').textContent = S.takeDisplaySelected.length + S.takeBagPending.length;
}

function renderTakeModalCups(myState) {
    const cupsEl = el('gbTakeModalCups');
    if (!cupsEl) return;
    cupsEl.replaceChildren();

    const label = document.createElement('div');
    label.className = 'gb-take-cups-label';
    label.textContent = 'Your cups:';
    cupsEl.appendChild(label);

    const row = document.createElement('div');
    row.className = 'gb-take-cups-row';

    [{ index: 0, label: 'Cup 1' }, { index: 1, label: 'Cup 2' }].forEach(({ index, label: cupLabel }) => {
        const cup = (myState.cups?.[index]?.ingredients) || [];
        const div = document.createElement('div');
        div.className = 'gb-take-cup-item';
        const lbl = document.createElement('span');
        lbl.className = 'gb-take-cup-lbl';
        lbl.textContent = `${cupLabel} (${cup.length}/5): `;
        div.appendChild(lbl);
        if (cup.length === 0) {
            const em = document.createElement('em');
            em.className = 'gb-empty-hint';
            em.textContent = 'empty';
            div.appendChild(em);
        } else {
            cup.forEach(ing => {
                const b = makeIngredientBadge(ing);
                b.classList.add('gb-badge-sm');
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
    if (S.takeStep === 0) {
        const total = S.takeDisplaySelected.length + S.takeBagPending.length;
        if (total === 0) {
            showModalError('gbTakeModalError', 'Select at least one ingredient before continuing.');
            return;
        }
        clearModalError('gbTakeModalError');
        const myState = S.me && S.game && S.game.game_state
            ? S.game.game_state.player_states[S.me.id]
            : null;
        _openAssignStep(myState);
    } else {
        submitTakeIngredients();
    }
}

function _openAssignStep(myState) {
    S.takeStep = 1;
    el('gbTakeStep0').classList.add('hidden');
    el('gbTakeStep1').classList.remove('hidden');
    el('gbTakeNextBtn').textContent = 'Submit';
    updateStepDots(1);
    el('gbTakeStepLabel').textContent = 'Step 2: Decide what to do with each ingredient.';
    _buildAssignTable(myState);
}

function _buildAssignTable(myState) {
    const tbody = el('gbAssignTableBody');
    tbody.replaceChildren();

    const cup1Count = myState ? ((myState.cups?.[0]?.ingredients) || []).length : 0;
    const cup2Count = myState ? ((myState.cups?.[1]?.ingredients) || []).length : 0;
    const CUP_MAX = 5;

    const allItems = [...S.takeDisplaySelected, ...S.takeBagPending];

    allItems.forEach((sel, i) => {
        const tr = document.createElement('tr');

        const tdIng = document.createElement('td');
        tdIng.appendChild(makeIngredientBadge(sel.ingredient));
        const srcLabel = document.createElement('span');
        srcLabel.className = 'gb-assign-src';
        srcLabel.textContent = sel.source === 'pending' ? '(bag)' : '(display)';
        tdIng.appendChild(srcLabel);
        tr.appendChild(tdIng);

        const tdAssign = document.createElement('td');
        const kind = ingredientKind(sel.ingredient);

        if (kind === 'special') {
            const note = document.createElement('em');
            note.className = 'gb-assign-note';
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

    const allItems = [...S.takeDisplaySelected, ...S.takeBagPending];
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
    S.takeDisplaySelected = [];
    S.takeBagPending = [];
    S.takeStep = 0;
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
    S.sellCupIndex = cupIndex;
    clearModalError('gbSellModalError');

    el('gbSellModalDesc').textContent = `Selling Cup ${cupIndex + 1}`;

    // Cup contents display
    const contentsEl = el('gbSellCupContents');
    contentsEl.replaceChildren();
    contents.forEach(ing => contentsEl.appendChild(makeIngredientBadge(ing)));

    // Specials picker
    const specials = myState.special_ingredients || [];
    const pickerEl = el('gbSellSpecialsPicker');
    pickerEl.replaceChildren();
    const section = el('gbSellSpecialsSection');

    if (specials.length === 0) {
        section.classList.add('hidden');
    } else {
        section.classList.remove('hidden');
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
            cup_index: S.sellCupIndex,
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
    S.sellCupIndex = null;
}

// ─────────────────────────────────────────────────────────────
// Drink Cup modal
// ─────────────────────────────────────────────────────────────
function openDrinkModal(cupIndex, contents) {
    S.drinkCupIndex = cupIndex;
    clearModalError('gbDrinkModalError');

    el('gbDrinkModalTitle').textContent = `Drink Cup ${cupIndex + 1}`;
    const ingNames = contents.map(ingredientLabel).join(', ');
    const spiritCount = contents.filter(i => ingredientKind(i) === 'spirit').length;

    const descEl = el('gbDrinkModalDesc');
    const warning = spiritCount > 0
        ? h('span', { className: 'gb-text-warning' }, `Warning: contains ${spiritCount} spirit${spiritCount > 1 ? 's' : ''} — your drunk level will increase by ${spiritCount}!`)
        : h('span', { className: 'gb-text-safe' }, 'Mixers only — will sober you up.');
    descEl.replaceChildren(
        text(`Are you sure you want to drink Cup ${cupIndex + 1}?`),
        document.createElement('br'),
        h('strong', null, 'Contents:'), text(` ${ingNames || 'empty'}`),
        document.createElement('br'),
        warning
    );

    openModal('gbDrinkModal');
    el('gbDrinkConfirmBtn').disabled = false;
}

async function confirmDrink() {
    clearModalError('gbDrinkModalError');
    const btn = el('gbDrinkConfirmBtn');
    setButtonBusy(btn, true, 'Drinking…');

    try {
        const resp = await gameAction('drink-cup', { cup_index: S.drinkCupIndex });
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
    S.drinkCupIndex = null;
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
// Window exports for HTML onclick handlers
// ─────────────────────────────────────────────────────────────
Object.assign(window, {
    openMenu, closeMenu, openRules, closeRules,
    switchTab, replayGo, exitReplay,
    closeTakeModal, takeModalNext,
    closeSellModal, confirmSell,
    closeDrinkModal, confirmDrink,
    closeCupDoublerModal, confirmCupDoubler,
    showGameError: showError, clearGameError: clearError,
});

// Auto-start
load();
