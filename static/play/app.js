// Table View — main controller. Boots the page, polls the game, and turns
// player taps into API actions. Rendering lives in render.js, primitives in ui.js.

import { api } from './api.js';
import { inviteBox } from '/static/invite.js';
import {
    CARD_TYPES, ING, SPECIAL_TYPES, MOVE_ICONS, STATUS_LABELS,
    describeMove, drinkName,
} from './meta.js';
import {
    bladderRow, cardFace, cupVessel, drunkMeter, renderCardRows, renderDock,
    renderMarket, renderMat, renderOpponents, specialChip, token,
} from './render.js';
import {
    banner, closeSheet, el, flyToken, openSheet, pulse, sheetOption, toastError,
} from './ui.js';

const POLL_MS = 2000;
const gameId = new URLSearchParams(window.location.search).get('id');

// Size the app to the *visible* viewport. Some Android browsers report
// 100dvh taller than what is actually visible (the system gesture bar
// overlays the bottom), which pushed the footer off screen.
function fitViewport() {
    const h = window.visualViewport?.height ?? window.innerHeight;
    document.documentElement.style.setProperty('--app-height', `${Math.round(h)}px`);
}
window.visualViewport?.addEventListener('resize', fitViewport);
window.addEventListener('resize', fitViewport);
fitViewport();

let me = null;
let game = null;
let valid = null;
const names = {};
let moveCount = null; // moves seen so far; null until first history load
let busy = false;
let winnerAnnounced = false;

const $ = (id) => document.getElementById(id);
const pts = (n) => `${n} ${n === 1 ? 'point' : 'points'}`;

// ─── Boot ────────────────────────────────────────────────────────────────────

async function boot() {
    if (!gameId) {
        window.location.href = '/';
        return;
    }
    try {
        me = await api.me();
        await refresh({ announce: false });
    } catch (e) {
        if (e.status === 403 || e.status === 404) {
            $('board').replaceChildren(el('div.center-msg', { text: 'This game is private or does not exist.' }));
            return;
        }
        toastError(e.message);
    }
    // Polls only while the page is showing, so the server counts you as
    // watching and only notifies you when you're not (static/push.js).
    setInterval(() => {
        if (!busy && document.visibilityState === 'visible') refresh().catch(() => {});
    }, POLL_MS);
    window.bocPush?.sync();
    window.bocPush?.watchGame(gameId);
}

async function ensureNames(g) {
    const ids = new Set([g.host, ...g.players]);
    const missing = [...ids].filter((id) => !names[id]);
    await Promise.all(missing.map(async (id) => {
        try {
            const u = await api.user(id);
            names[id] = u.username ?? 'Unknown';
        } catch {
            names[id] = 'Unknown';
        }
    }));
}

const nameOf = (pid) => (pid === me?.id ? 'You' : (names[pid] ?? '…'));

// ─── Polling & event announcements ───────────────────────────────────────────

async function refresh({ announce = true } = {}) {
    const g = await api.game(gameId);
    await ensureNames(g);
    const changed = JSON.stringify(g.game_state) !== JSON.stringify(game?.game_state) || g.status !== game?.status;
    game = g;
    if (g.status !== 'NEW') {
        valid = g.status === 'STARTED' ? await api.validActions(gameId) : { actions: [], available_types: {}, can_end_turn: false };
        if (changed || moveCount === null) await announceNewMoves(announce);
    }
    render();
}

async function announceNewMoves(announce) {
    try {
        const { moves } = await api.history(gameId);
        if (moveCount !== null && announce) {
            for (const move of moves.slice(moveCount)) {
                if (move.player_id === me.id) continue;
                banner(describeMove(move, nameOf), { icon: MOVE_ICONS[move.action?.type] ?? '🍸' });
            }
        }
        moveCount = moves.length;
    } catch {
        // History is decorative; never block the board on it.
    }
}

// Apply an action response immediately (no waiting for the next poll).
async function applyResult(newState) {
    game.game_state = newState;
    try {
        valid = game.status === 'STARTED' && !newState.winner
            ? await api.validActions(gameId)
            : { actions: [], available_types: {}, can_end_turn: false };
    } catch {
        valid = { actions: [], available_types: {}, can_end_turn: false };
    }
    // moveCount is left as-is: the next poll announces any bot moves that
    // happened during this action, while my own moves are filtered out.
    render();
}

async function doAction(fn) {
    if (busy) return null;
    busy = true;
    try {
        const result = await fn();
        closeSheet(true);
        if (result?.game_state) await applyResult(result.game_state);
        return result;
    } catch (e) {
        toastError(e.message);
        try {
            await refresh({ announce: false });
        } catch { /* keep last render */ }
        return null;
    } finally {
        busy = false;
    }
}

// ─── Rendering ───────────────────────────────────────────────────────────────

function render() {
    if (game.status === 'NEW') {
        renderLobby();
        return;
    }
    renderBoard();
}

function buildCtx() {
    const gs = game.game_state;
    const myTurn = gs.player_turn === me.id && !gs.winner;
    const availableTypes = new Map(Object.entries(valid?.available_types ?? {}));
    const takeInProgress = myTurn && (gs.ingredients_taken_this_turn > 0 || gs.bag_draw_pending.length > 0);
    return {
        meId: me.id,
        nameOf,
        myTurn,
        takeInProgress,
        availableTypes,
        canTakeNow: myTurn && availableTypes.has('take_ingredients') && !assignFlow,
        canEndTurn: !!valid?.can_end_turn,
        selectedSlots,
        selectedCount: selectedSlots.size,
        assignFlow: myTurn && assignFlow ? assignFlowDescriptor() : null,
        claimableCardIds: new Set(valid?.actions.filter((a) => a.action_type === 'claim_card').map((a) => a.params.card_id)),
        refreshableRows: new Set(valid?.actions.filter((a) => a.action_type === 'refresh_card_row').map((a) => a.params.row_position)),
        readOnly: false,
        on: {
            displayTokenTap, bagTap, cupTap, bladderTap: confirmWee, cardTap, rowRefresh: confirmRefreshRow,
            specialsTap: openRerollSheet, myStoreCardTap: openStoreCardSheet, opponentTap: openOpponentSheet,
            dockAction, assignSelected, clearSelection, assignCancel: cancelAssignFlow,
        },
    };
}

function renderBoard() {
    const gs = game.game_state;
    // A stale selection or half-assigned batch can't survive the turn moving on
    if (gs.player_turn !== me.id || gs.winner) {
        selectedSlots.clear();
        assignFlow = null;
    }
    const ctx = buildCtx();
    document.body.classList.toggle('my-turn', ctx.myTurn);
    $('board').classList.remove('lobby-mode');
    $('lobby').replaceChildren();

    // Top bar
    const ps = gs.player_states[me.id];
    $('turnIndicator').replaceChildren(...[
        gs.winner
            ? el('span.turn-winner', { text: `🏆 ${nameOf(gs.winner)} won!` })
            : ctx.myTurn
                ? el('span.turn-you', { text: 'Your turn!' })
                : el('span.turn-other', { text: `${nameOf(gs.player_turn)}'s turn` }),
        gs.last_round && !gs.winner ? el('span.last-round', { text: '🔔 Final round' }) : null,
    ].filter(Boolean));
    $('myScore').hidden = false;
    $('myScore').textContent = `⭐ ${ps?.points ?? 0}`;
    $('myScore').setAttribute('aria-label', `Your score: ${ps?.points ?? 0} points. First to 40 triggers the final round.`);

    renderOpponents($('players'), gs, ctx);
    renderCardRows($('cards'), gs, ctx);
    renderMarket($('market'), gs, ctx);
    renderMat($('mat'), gs, ctx);
    renderDock($('dock'), gs, ctx);
    renderUndoBar();

    if (gs.winner && !winnerAnnounced) {
        winnerAnnounced = true;
        showWinnerOverlay(gs.winner);
    }

    // Mid-take with unassigned bag draws (e.g. after a reload): resume the flow.
    if (ctx.myTurn && gs.bag_draw_pending.length > 0 && !assignFlow && !busy) {
        startPendingAssignment();
    }
}

function renderUndoBar() {
    const bar = $('undoBar');
    const undo = game.pending_undo;
    if (!undo || undo.status !== 'pending') {
        bar.classList.add('hidden');
        bar.replaceChildren();
        return;
    }
    const votes = undo.votes ?? {};
    const iVoted = votes[me.id] !== undefined;
    bar.classList.remove('hidden');
    bar.replaceChildren(
        el('span', { text: `↩️ ${nameOf(undo.proposed_by)} asked to undo the last turn` }),
        iVoted
            ? el('span.undo-waiting', { text: 'waiting for others…' })
            : el('span.undo-votes', {},
                el('button.btn-mini', { onclick: () => voteUndo('agree'), text: 'Agree' }),
                el('button.btn-mini.btn-ghost', { onclick: () => voteUndo('disagree'), text: 'Disagree' }),
            ),
    );
}

async function voteUndo(vote) {
    await doAction(async () => {
        await api.voteUndo(gameId, game.pending_undo.id, vote);
        await refresh({ announce: false });
        return null;
    });
}

// ─── Take ingredients flow ───────────────────────────────────────────────────
//
// Face-up ingredients are picked up by tapping (multi-select), then assigned
// in one batch. The bag asks how many to draw; once drawn, every revealed
// ingredient must be assigned — the rules allow no undo on a bag draw.

const selectedSlots = new Set();

function takeRemaining() {
    const gs = game.game_state;
    const ps = gs.player_states[me.id];
    return ps.take_count - gs.ingredients_taken_this_turn;
}

function displayTokenTap(ingredientName, slotIndex) {
    if (selectedSlots.has(slotIndex)) {
        selectedSlots.delete(slotIndex);
    } else if (selectedSlots.size >= takeRemaining()) {
        toastError(`You can only take ${takeRemaining()} more this turn — assign what you've picked up.`);
        return;
    } else {
        selectedSlots.add(slotIndex);
    }
    render();
}

function clearSelection({ rerender = true } = {}) {
    selectedSlots.clear();
    if (rerender) render();
}

function selectedItems() {
    const display = game.game_state.open_display;
    return [...selectedSlots].sort((a, b) => a - b).map((slot) => ({ ingredient: display[slot], source: 'display' }));
}

function assignSelected() {
    startAssignmentFlow(selectedItems());
}

function bagTap(bagEl) {
    const gs = game.game_state;
    const maxDraw = Math.min(takeRemaining() - selectedSlots.size, gs.bag_contents.length);
    if (maxDraw < 1) {
        toastError('No room left this turn — assign what you’ve picked up first.');
        return;
    }
    const countButtons = Array.from({ length: maxDraw }, (_, i) => {
        const n = i + 1;
        return el('button.count-btn', {
            onclick: () => {
                doAction(() => api.drawFromBag(gameId, n)).then((result) => {
                    if (!result) return;
                    flyToken(bagEl, $('dock'));
                    startPendingAssignment();
                });
            },
            'aria-label': `Draw ${n} from the bag`,
            text: String(n),
        });
    });
    openSheet('Draw from the bag', el('div.sheet-options', {},
        el('p.sheet-note', { text: 'How many ingredients do you want to draw blind?' }),
        el('div.count-row', {}, countButtons),
        el('p.sheet-note.sheet-warn', {
            text: 'No going back: whatever you draw, you must keep and assign — to a cup or down the hatch.'
                + (selectedSlots.size ? ` Your ${selectedSlots.size} picked-up ingredient(s) will be assigned in the same batch.` : ''),
        }),
    ));
}

// Kick off assignment of the pending bag draw plus any selected display tokens.
function startPendingAssignment() {
    const pendingItems = game.game_state.bag_draw_pending.map((name) => ({ ingredient: name, source: 'pending' }));
    startAssignmentFlow([...pendingItems, ...selectedItems()]);
}

// The batch being assigned, one ingredient at a time, via the dock (so the
// cups and bladder stay visible). Batches containing bag draws cannot be
// backed out of; display-only batches can be put back.
let assignFlow = null; // { items, collected, batch: { cup0, cup1, drinks } }

function startAssignmentFlow(items) {
    if (!items.length) return;
    assignFlow = { items, collected: [], batch: { cup0: 0, cup1: 0, drinks: 0 } };
    render();
}

function cancelAssignFlow() {
    assignFlow = null;
    clearSelection();
}

async function assignChoice(disposition, cupIndex) {
    const flow = assignFlow;
    const item = flow.items[flow.collected.length];
    flow.collected.push({
        ingredient: item.ingredient, source: item.source, disposition, cup_index: cupIndex,
    });
    if (disposition === 'cup') flow.batch[`cup${cupIndex}`] += 1;
    else flow.batch.drinks += 1;
    if (flow.collected.length < flow.items.length) {
        render();
        return;
    }
    const assignments = flow.collected;
    assignFlow = null;
    const result = await doAction(() => api.takeIngredients(gameId, assignments));
    if (result) {
        clearSelection({ rerender: false });
        afterTakeBatch(result);
    }
    render();
}

// Descriptor for renderDock: the full batch queue, the current item and its
// choice buttons — so a multi-draw shows everything drawn at once.
function assignFlowDescriptor() {
    const flow = assignFlow;
    const idx = flow.collected.length;
    const item = flow.items[idx];
    const meta = ING[item.ingredient];
    const counter = flow.items.length > 1 ? ` (${idx + 1} of ${flow.items.length})` : '';
    const title = item.source === 'pending'
        ? `You drew ${meta?.label ?? item.ingredient}${counter} — where does it go?`
        : `${meta?.label ?? item.ingredient}${counter} — where does it go?`;
    const badgeFor = (a) => (a.disposition === 'cup' ? `🥛${a.cup_index + 1}` : '👄');
    return {
        tokenName: item.ingredient,
        title,
        queue: flow.items.map((it, i) => ({
            name: it.ingredient,
            state: i < idx ? 'done' : i === idx ? 'current' : 'todo',
            badge: i < idx ? badgeFor(flow.collected[i]) : undefined,
        })),
        options: assignOptions(item.ingredient, flow.batch, assignChoice),
        cancellable: !flow.items.some((i) => i.source === 'pending'),
    };
}

function drunkPreview(ingredients) {
    const ps = game.game_state.player_states[me.id];
    const refresherMixers = new Set(ps.cards.filter((c) => c.card_type === 'refresher').map((c) => c.mixer_type));
    const spirits = ingredients.filter((i) => ING[i]?.kind === 'spirit').length;
    const hot = ingredients.filter((i) => ING[i]?.kind === 'mixer' && refresherMixers.has(i)).length;
    const plain = ingredients.filter((i) => ING[i]?.kind === 'mixer' && !refresherMixers.has(i)).length;
    let delta = spirits - hot;
    if (spirits === 0) delta -= plain;
    return delta;
}

// Choice descriptors for a single ingredient, aware of what this batch has
// already claimed (cup space, bladder room) via `batch`. Rendered as dock
// buttons by renderDock.
function assignOptions(ingredientName, batch, submit) {
    const meta = ING[ingredientName];
    if (meta?.kind === 'special') {
        return [{
            icon: '🎲', label: 'Roll the die', sub: 'reveal your special',
            onclick: () => submit('drink', 0),
        }];
    }
    const ps = game.game_state.player_states[me.id];
    const options = [0, 1].map((i) => {
        const fill = ps.cups[i].ingredients.length + batch[`cup${i}`];
        return {
            icon: '🥛',
            label: `Cup ${i + 1}`,
            sub: `${fill}/5 full`,
            disabled: fill >= 5,
            reason: 'full',
            onclick: () => submit('cup', i),
        };
    });
    const delta = drunkPreview([ingredientName]);
    const wouldPassOut = ps.drunk_level + Math.max(delta, 0) > 5;
    const wouldWet = ps.bladder.length + batch.drinks + 1 > ps.bladder_capacity;
    options.push({
        icon: '👄',
        label: 'Drink it',
        sub: wouldPassOut ? '⚠️ hospital!'
            : wouldWet ? '⚠️ overflow!'
                : delta !== 0 ? `${delta > 0 ? '+' : ''}${delta} drunk` : '+1 bladder',
        danger: wouldPassOut || wouldWet,
        onclick: () => submit('drink', 0),
    });
    return options;
}

function afterTakeBatch(result) {
    for (const record of result.move?.taken ?? []) {
        if (record.disposition !== 'special') continue;
        const rolled = record.special_type;
        banner(rolled === 'nothing' ? 'The die came up empty — no special this time' : `🎲 You rolled ${SPECIAL_TYPES[rolled]?.label ?? rolled}!`,
            { icon: '🎲', tone: rolled === 'nothing' ? 'error' : 'info' });
    }
    if (result.move?.turn_complete) {
        const ps = game.game_state.player_states[me.id];
        if (ps.status === 'hospitalised') banner('You passed out — off to hospital! 🏥', { tone: 'error', ms: 4000 });
        else if (ps.status === 'wet') banner('Your bladder gave out… you are out! 💦', { tone: 'error', ms: 4000 });
    } else if (game.game_state.player_turn === me.id) {
        const remaining = takeRemaining();
        if (remaining > 0) pulse($('market'));
    }
}

// ─── Sell / drink cups ───────────────────────────────────────────────────────

function sellOptionsForCup(cupIndex) {
    return (valid?.actions ?? []).filter((a) =>
        a.action_type === 'sell_cup' && a.params.cup_index === cupIndex && !a.params.additional_cups);
}

function sellBothOptions() {
    return (valid?.actions ?? []).filter((a) => a.action_type === 'sell_cup' && a.params.additional_cups);
}

function specialsSummary(declared) {
    return declared.length ? `using ${declared.map((s) => SPECIAL_TYPES[s]?.label ?? s).join(' + ')}` : 'no specials';
}

// One sheet listing every way to sell right now: per-cup options and — when
// the sell_both_cups house rule allows it — both cups in a single action.
function openSellSheet() {
    const gs = game.game_state;
    const ps = gs.player_states[me.id];
    const options = [];
    const boths = sellBothOptions().sort((a, b) => b.params.points - a.params.points).slice(0, 3);
    for (const [i, a] of boths.entries()) {
        options.push(sheetOption({
            icon: '💰',
            label: `Sell BOTH cups — ${pts(a.params.points)}`,
            sub: 'one action, both drinks',
            primary: i === 0,
            onclick: () => sellCup(a.params),
        }));
    }
    for (const cupIndex of [0, 1]) {
        const sells = sellOptionsForCup(cupIndex).sort((a, b) => b.params.points - a.params.points).slice(0, 4);
        for (const a of sells) {
            options.push(sheetOption({
                icon: '🥛',
                label: `Cup ${cupIndex + 1}: ${drinkName(ps.cups[cupIndex].ingredients, a.params.declared_specials)} — ${pts(a.params.points)}`,
                sub: specialsSummary(a.params.declared_specials) + (a.is_free ? ' · ⚡ free action' : ''),
                primary: !boths.length && a === sells[0],
                onclick: () => sellCup(a.params),
            }));
        }
    }
    options.push(el('button.menu-link', { onclick: openDrinksMenu, text: '📖 Drinks menu & prices' }));
    openSheet('Sell drinks', el('div.sheet-options', {}, options));
}

function cupTap(cupIndex) {
    const gs = game.game_state;
    const ps = gs.player_states[me.id];
    const cup = ps.cups[cupIndex];
    const options = [];

    const sells = sellOptionsForCup(cupIndex).sort((a, b) => b.params.points - a.params.points);
    for (const a of sells) {
        options.push(sheetOption({
            icon: '💰',
            label: `Sell as ${drinkName(cup.ingredients, a.params.declared_specials)} — ${pts(a.params.points)}`,
            sub: specialsSummary(a.params.declared_specials) + (a.is_free ? ' · ⚡ free action' : ''),
            primary: a === sells[0],
            onclick: () => sellCup(a.params),
        }));
    }
    for (const a of sellBothOptions().sort((x, y) => y.params.points - x.params.points).slice(0, 3)) {
        options.push(sheetOption({
            icon: '💰',
            label: `Sell BOTH cups — ${pts(a.params.points)}`,
            sub: 'sell_both_cups mode',
            onclick: () => sellCup(a.params),
        }));
    }
    if (!sells.length) {
        options.push(el('p.sheet-note', { text: 'This mix can’t be sold — check the drinks menu below or drink it to clear the cup.' }));
    }

    const delta = drunkPreview(cup.ingredients);
    const after = Math.max(0, ps.drunk_level + delta);
    const wouldPassOut = ps.drunk_level + delta > 5;
    const wouldWet = ps.bladder.length + cup.ingredients.length > ps.bladder_capacity;
    if (valid?.available_types?.drink_cup !== undefined) {
        options.push(sheetOption({
            icon: '🍹',
            label: `Drink Cup ${cupIndex + 1}`,
            sub: wouldPassOut ? '⚠️ You would pass out — hospital!'
                : wouldWet ? '⚠️ Your bladder would overflow!'
                    : `drunk level ${ps.drunk_level} → ${after}, bladder +${cup.ingredients.length}`,
            onclick: () => doAction(() => api.drinkCup(gameId, cupIndex)).then((r) => {
                if (r) banner(`You drank cup ${cupIndex + 1}`, { icon: '🍹' });
            }),
        }));
    }
    options.push(el('button.menu-link', { onclick: openDrinksMenu, text: '📖 Drinks menu & prices' }));

    openSheet(`Cup ${cupIndex + 1}`, el('div.sheet-options', {},
        el('div.sheet-token-preview', {}, cupVessel(cup, cupIndex, { mini: true })),
        options,
    ));
}

async function sellCup(params) {
    const result = await doAction(() => api.sellCup(gameId, {
        cup_index: params.cup_index,
        declared_specials: params.declared_specials,
        additional_cups: params.additional_cups,
    }));
    if (result) {
        banner(`💰 Sold for ${pts(result.move.points_earned)}!`, { icon: '🍸' });
        pulse($('myScore'));
    }
}

// ─── Wee / claim / refresh / re-roll ────────────────────────────────────────

function confirmWee() {
    const ps = game.game_state.player_states[me.id];
    const willSeal = ps.toilet_tokens > 0;
    openSheet('Go for a wee 🚽', el('div.sheet-options', {},
        el('p.sheet-note', {
            text: `Empty your bladder (${ps.bladder.length} ingredients) and sober up one level.`
                + (willSeal ? ' Breaking the seal shrinks your bladder by one slot.' : ''),
        }),
        sheetOption({
            icon: '🚽', label: 'Go for a wee', primary: true,
            onclick: () => doAction(() => api.goForAWee(gameId)).then((r) => {
                if (r) banner('Ahh, much better 🚽', { icon: '💧' });
            }),
        }),
    ));
}

function bladderCount(ingredientName) {
    return game.game_state.player_states[me.id].bladder.filter((i) => i === ingredientName).length;
}

function cardTap(card) {
    const type = CARD_TYPES[card.card_type];
    const claims = (valid?.actions ?? []).filter((a) => a.action_type === 'claim_card' && a.params.card_id === card.id);
    const body = [
        el('div.sheet-card-preview', {}, cardFace(card)),
        el('p.sheet-note', {}, el('strong', { text: `Cost: ${type.cost(card)}. ` }), type.effect(card)),
    ];
    if (claims.length === 0) {
        body.push(el('p.sheet-note.sheet-warn', { text: claimShortfall(card) }));
    } else if (card.card_type === 'cup_doubler') {
        for (const a of claims) {
            body.push(sheetOption({
                icon: '🥤',
                label: `Claim with ${ING[a.params.spirit_type]?.label} → Cup ${a.params.cup_index + 1}`,
                sub: a.is_free ? '⚡ free action' : undefined,
                onclick: () => claimCard(a.params, card),
            }));
        }
    } else {
        body.push(sheetOption({
            icon: type.icon, label: `Claim ${card.name}`, primary: true,
            sub: claims[0].is_free ? '⚡ free action' : undefined,
            onclick: () => claimCard(claims[0].params, card),
        }));
    }
    openSheet(card.name, el('div.sheet-options', {}, body));
}

function claimShortfall(card) {
    const gs = game.game_state;
    if (gs.player_turn !== me.id) return 'You can claim cards on your turn if you have drunk enough.';
    const need = card.cost?.[0]?.count ?? 0;
    if (card.card_type === 'cup_doubler') {
        return 'You need 3 of the same spirit in your bladder to claim this.';
    }
    const type = card.spirit_type ?? card.mixer_type;
    const have = bladderCount(type);
    return `You've drunk ${have} of the ${need} ${ING[type]?.label ?? ''} needed.`;
}

async function claimCard(params, card) {
    const result = await doAction(() => api.claimCard(gameId, {
        card_id: params.card_id, cup_index: params.cup_index, spirit_type: params.spirit_type,
    }));
    if (result) {
        banner(`You claimed ${card.name}! ${CARD_TYPES[card.card_type]?.icon ?? ''}`, { icon: '🃏' });
        pulse($('mat'));
        if (result.game_state.winner === me.id) return; // overlay handles it
    }
}

function confirmRefreshRow(rowPosition) {
    openSheet(`Refresh row ${rowPosition}`, el('div.sheet-options', {},
        el('p.sheet-note', { text: 'Discard all cards in this row and deal replacements from the deck. Discarded cards never come back.' }),
        sheetOption({
            icon: '🔄', label: `Refresh row ${rowPosition}`, primary: true,
            onclick: () => doAction(() => api.refreshCardRow(gameId, rowPosition)).then((r) => {
                if (r) banner(`Row ${rowPosition} refreshed`, { icon: '🔄' });
            }),
        }),
    ));
}

function openRerollSheet() {
    const specials = [...game.game_state.player_states[me.id].special_ingredients];
    const selected = new Set(specials.map((_, i) => i));
    const chips = specials.map((s, i) => specialChip(s, {
        selected: true,
        onclick: (ev) => {
            const on = selected.has(i);
            if (on) selected.delete(i); else selected.add(i);
            ev.currentTarget.classList.toggle('selected', !on);
            ev.currentTarget.setAttribute('aria-pressed', String(!on));
            confirmBtn.disabled = selected.size === 0;
        },
    }));
    const confirmBtn = sheetOption({
        icon: '🎲', label: 'Re-roll selected specials', primary: true,
        sub: 'Each re-roll can land on a new special — or nothing at all',
        onclick: () => {
            const chosen = specials.filter((_, i) => selected.has(i));
            doAction(() => api.rerollSpecials(gameId, chosen)).then((r) => {
                if (!r) return;
                const got = r.move.results.map((x) => (x ? (SPECIAL_TYPES[x]?.label ?? x) : 'nothing'));
                banner(`🎲 Re-rolled → ${got.join(', ')}`, { icon: '🎲' });
            });
        },
    });
    openSheet('Re-roll specials', el('div.sheet-options', {},
        el('p.sheet-note', { text: 'Pick which specials to throw back for a fresh roll.' }),
        el('div.specials-chips.sheet-chips', {}, chips),
        confirmBtn,
    ));
}

// ─── Store cards (free actions) ──────────────────────────────────────────────

function openStoreCardSheet(cardDict, cardIndex) {
    const stored = cardDict.stored_spirits ?? [];
    const spiritLabel = ING[cardDict.spirit_type]?.label ?? cardDict.spirit_type;
    const ps = game.game_state.player_states[me.id];
    const acts = (valid?.actions ?? []);
    const canDrink = acts.some((a) => a.action_type === 'drink_stored_spirit' && a.params.store_card_index === cardIndex);
    const pourTargets = acts.filter((a) => a.action_type === 'use_stored_spirit' && a.params.store_card_index === cardIndex);
    const options = [];
    if (canDrink) {
        const delta = drunkPreview([cardDict.spirit_type]);
        options.push(sheetOption({
            icon: '🥃', label: `Drink one ${spiritLabel}`,
            sub: ps.drunk_level + delta > 5 ? '⚠️ You would pass out!' : `+${delta} drunk, +1 bladder · ⚡ free`,
            onclick: () => doAction(() => api.drinkStoredSpirit(gameId, cardIndex, 1)).then((r) => {
                if (r) banner(`You drank a stored ${spiritLabel}`, { icon: '🥃' });
            }),
        }));
    }
    for (const a of pourTargets) {
        options.push(sheetOption({
            icon: '🫗', label: `Pour one into Cup ${a.params.cup_index + 1}`, sub: '⚡ free',
            onclick: () => doAction(() => api.useStoredSpirit(gameId, cardIndex, a.params.cup_index)),
        }));
    }
    if (!options.length) options.push(el('p.sheet-note', { text: 'You can use stored spirits on your turn.' }));
    openSheet(cardDict.name, el('div.sheet-options', {},
        el('div.sheet-token-preview', {}, stored.map((s) => token(s))),
        options,
    ));
}

// ─── Opponents detail ────────────────────────────────────────────────────────

function openOpponentSheet(pid) {
    const ps = game.game_state.player_states[pid];
    const cards = ps.cards.map((cd) => {
        const type = CARD_TYPES[cd.card_type] ?? { icon: '❓' };
        return el('span.my-card', {},
            el('span', { text: type.icon, 'aria-hidden': 'true' }),
            el('span.my-card-name', { text: cd.name }),
            cd.card_type === 'store' && cd.stored_spirits?.length
                ? el('span.my-card-stored', {}, cd.stored_spirits.map((s) => token(s, { size: 'xs' })))
                : null,
        );
    });
    openSheet(names[pid] ?? 'Player', el('div.sheet-options', {},
        el('div.opp-detail-stats', {},
            el('span', { text: `⭐ ${ps.points} pts` }),
            el('span', { text: `🎤 ${ps.karaoke_cards_claimed}/3` }),
            ps.status !== 'active' ? el('span', { text: STATUS_LABELS[ps.status] }) : null,
        ),
        drunkMeter(ps.drunk_level, ps.take_count),
        // Bladder contents are public — they show which cards this player
        // can afford to claim.
        bladderRow(ps),
        el('div.opp-detail-cups', {},
            cupVessel(ps.cups[0], 0, { mini: true }),
            cupVessel(ps.cups[1], 1, { mini: true }),
        ),
        ps.special_ingredients.length
            ? el('div.specials-chips', {}, ps.special_ingredients.map((s) => specialChip(s)))
            : null,
        cards.length ? el('div.my-cards', {}, cards) : el('p.sheet-note', { text: 'No cards claimed yet.' }),
    ));
}

// ─── Dock actions ────────────────────────────────────────────────────────────

function dockAction(type) {
    const gs = game.game_state;
    switch (type) {
        case 'take_ingredients':
            banner('Tap face-up ingredients to pick them up, or the bag to draw blind', { icon: '🫳' });
            pulse($('market'));
            break;
        case 'sell_cup': {
            const sellable = [0, 1].filter((i) => sellOptionsForCup(i).length);
            if (sellable.length === 1 && !sellBothOptions().length) cupTap(sellable[0]);
            else openSellSheet();
            break;
        }
        case 'drink_cup': {
            const cups = [0, 1].filter((i) => !gs.player_states[me.id].cups[i].is_empty);
            if (cups.length === 1) cupTap(cups[0]);
            else {
                banner('Tap one of your cups', { icon: '🥛' });
                pulse($('mat'));
            }
            break;
        }
        case 'go_for_a_wee':
            confirmWee();
            break;
        case 'claim_card':
            banner('Tap a glowing card to claim it', { icon: '🃏' });
            pulse($('cards'));
            break;
        case 'reroll_specials':
            openRerollSheet();
            break;
        case 'refresh_card_row': {
            const rows = [...buildCtx().refreshableRows];
            if (rows.length === 1) confirmRefreshRow(rows[0]);
            else {
                banner('Tap 🔄 next to the row you want to refresh', { icon: '🔄' });
                pulse($('cards'));
            }
            break;
        }
        case 'end_turn':
            doAction(() => api.endTurn(gameId));
            break;
    }
}

// ─── Drinks menu ─────────────────────────────────────────────────────────────

function openDrinksMenu() {
    const row = (label, pts, tokens_) => el('div.menu-row', {},
        el('span.menu-drink', {}, ...tokens_, el('span', { text: ` ${label}` })),
        el('span.menu-pts', { text: `${pts} pts` }),
    );
    const t = (n) => token(n, { size: 'xs' });
    const sp = (s) => el('span.menu-special', { text: SPECIAL_TYPES[s].icon, title: SPECIAL_TYPES[s].label });
    openSheet('Drinks menu', el('div.sheet-options.menu-list', {},
        el('h3.menu-heading', { text: 'Simple drinks (one spirit type + its mixer)' }),
        row('Single spirit + mixer', 1, [t('VODKA'), t('COLA')]),
        row('Double spirit + mixer', 3, [t('VODKA'), t('VODKA'), t('COLA')]),
        row('Tequila Slammer', 3, [t('TEQUILA'), t('TEQUILA')]),
        el('p.sheet-note', { text: 'Pairings — Vodka: any mixer · Rum: cola · Whisky: cola or soda · Gin: tonic · Tequila: neat only' }),
        el('h3.menu-heading', { text: 'Cocktails (exact recipe + specials)' }),
        row('Mojito', 10, [t('RUM'), t('RUM'), t('SODA'), sp('sugar')]),
        row('Old Fashioned', 10, [t('WHISKEY'), t('WHISKEY'), t('WHISKEY'), sp('bitters')]),
        row('Margarita', 10, [t('TEQUILA'), t('TEQUILA'), sp('cointreau'), sp('lemon')]),
        row('Cosmopolitan', 10, [t('VODKA'), t('CRANBERRY'), sp('cointreau'), sp('lemon')]),
        row('Gin Martini', 10, [t('GIN'), t('GIN'), t('GIN'), sp('vermouth')]),
        row('Vodka Martini', 10, [t('VODKA'), t('VODKA'), t('VODKA'), sp('vermouth')]),
        row('Tom Collins', 10, [t('GIN'), t('SODA'), sp('lemon'), sp('sugar')]),
        row('Manhattan', 10, [t('WHISKEY'), t('WHISKEY'), sp('vermouth'), sp('bitters')]),
        row('Long Island Iced Tea', 15, [t('GIN'), t('VODKA'), t('TEQUILA'), t('RUM'), t('COLA'), sp('sugar'), sp('lemon')]),
    ));
}

// ─── History & replay ────────────────────────────────────────────────────────

async function openHistorySheet() {
    let moves = [];
    try {
        moves = (await api.history(gameId)).moves;
    } catch {
        toastError('Could not load the history right now.');
        return;
    }
    const items = moves.slice().reverse().map((move) => el('div.history-item', {},
        el('span.history-icon', { text: MOVE_ICONS[move.action?.type] ?? '🍸', 'aria-hidden': 'true' }),
        el('span.history-text', { text: describeMove(move, nameOf) }),
        el('span.history-turn', { text: `t${move.turn_number}` }),
    ));
    openSheet('History', el('div.sheet-options.history-list', {},
        items.length ? items : el('p.sheet-note', { text: 'No moves yet.' })));
}

const replayCache = {};
let replayTurn = 0;
let replayTimer = null;

async function openReplay() {
    let maxTurn = game.game_state.turn_number;
    try {
        const { moves } = await api.history(gameId);
        if (moves.length) maxTurn = Math.max(...moves.map((m) => m.turn_number)) + 1;
    } catch { /* fall back to current turn number */ }
    const overlay = $('replayOverlay');
    overlay.classList.remove('hidden');
    overlay.querySelector('#replaySlider').max = String(maxTurn);
    stopReplayAutoplay();
    await showReplayTurn(0);
    overlay.querySelector('.replay-close').focus();
}

async function showReplayTurn(turn) {
    replayTurn = turn;
    const overlay = $('replayOverlay');
    overlay.querySelector('#replaySlider').value = String(turn);
    overlay.querySelector('#replayTurnLabel').textContent = turn === 0 ? 'Start of game' : `After turn ${turn}`;
    let state = replayCache[turn];
    if (!state && turn === Number(overlay.querySelector('#replaySlider').max)) {
        state = game.game_state; // the latest turn is the live state
    }
    if (!state) {
        try {
            state = (await api.stateAtTurn(gameId, turn)).game_state;
            replayCache[turn] = state;
        } catch {
            overlay.querySelector('#replayBoard').replaceChildren(el('p.sheet-note', { text: 'No snapshot for this turn.' }));
            return;
        }
    }
    const host = overlay.querySelector('#replayBoard');
    const roCtx = {
        meId: me.id, nameOf, readOnly: true, myTurn: false, takeInProgress: false,
        canTakeNow: false, availableTypes: new Map(), canEndTurn: false,
        claimableCardIds: new Set(), refreshableRows: new Set(), on: { opponentTap: () => {} },
    };
    const players = el('div.players');
    const cards = el('div.cards');
    const market = el('div.market');
    const mat = el('div.mat');
    renderOpponents(players, state, { ...roCtx, on: { opponentTap: () => {} } });
    renderCardRows(cards, state, roCtx);
    renderMarket(market, state, roCtx);
    renderMat(mat, state, roCtx);
    host.replaceChildren(players, cards, market, el('div.replay-mat-label', { text: 'Your table' }), mat);
}

function stopReplayAutoplay() {
    if (replayTimer) {
        clearInterval(replayTimer);
        replayTimer = null;
        $('replayPlay').textContent = '▶';
        $('replayPlay').setAttribute('aria-label', 'Play replay');
    }
}

function toggleReplayAutoplay() {
    if (replayTimer) {
        stopReplayAutoplay();
        return;
    }
    $('replayPlay').textContent = '⏸';
    $('replayPlay').setAttribute('aria-label', 'Pause replay');
    replayTimer = setInterval(() => {
        const max = Number($('replaySlider').max);
        if (replayTurn >= max) stopReplayAutoplay();
        else showReplayTurn(replayTurn + 1);
    }, 1300);
}

// ─── Menu / winner / lobby ───────────────────────────────────────────────────

function openMenuSheet() {
    const gs = game.game_state;
    const ps = gs.player_states?.[me.id];
    const options = [];
    if (game.status === 'STARTED' && ps && ps.status === 'active') {
        options.push(sheetOption({
            icon: '↩️', label: 'Propose undo', sub: 'Everyone must agree to roll back the last turn',
            onclick: () => doAction(async () => {
                await api.proposeUndo(gameId);
                await refresh({ announce: false });
                banner('Undo proposed — waiting for votes', { icon: '↩️' });
                return null;
            }),
        }));
        options.push(sheetOption({
            icon: '🚪', label: 'Quit this game', sub: 'You are out; the others play on',
            onclick: () => confirmDestructive('Quit this game?', 'You will be out for good.', () =>
                doAction(() => api.quit(gameId))),
        }));
    }
    if (game.status === 'STARTED' && game.host === me.id) {
        options.push(sheetOption({
            icon: '❌', label: 'Cancel the game', sub: 'Ends the game for everyone, no winner',
            onclick: () => confirmDestructive('Cancel the game?', 'This ends the game for all players.', () =>
                doAction(() => api.cancel(gameId))),
        }));
    }
    options.push(sheetOption({
        icon: '🕹️', label: 'Switch to classic view',
        onclick: () => {
            localStorage.setItem('bocTableView', '0');
            localStorage.setItem('bocUi', 'classic');
            window.location.href = `/game?id=${gameId}`;
        },
    }));
    options.push(sheetOption({ icon: '🏠', label: 'Back to home', onclick: () => { window.location.href = '/'; } }));
    openSheet('Menu', el('div.sheet-options', {}, options));
}

function confirmDestructive(title, note, action) {
    openSheet(title, el('div.sheet-options', {},
        el('p.sheet-note.sheet-warn', { text: note }),
        sheetOption({ icon: '✔️', label: 'Yes, do it', onclick: action }),
        sheetOption({ icon: '✖️', label: 'Never mind', primary: true, onclick: () => closeSheet() }),
    ));
}

function showWinnerOverlay(winnerId) {
    const overlay = $('winnerOverlay');
    const iWon = winnerId === me.id;
    overlay.replaceChildren(
        el('div.winner-card', {},
            el('div.winner-emoji', { text: iWon ? '🏆🍹🎉' : '🏆', 'aria-hidden': 'true' }),
            el('h2', { text: iWon ? 'You won!' : `${nameOf(winnerId)} wins!` }),
            el('p', { text: iWon ? 'The bar crowd goes wild. Drinks on you!' : 'Better luck at the next happy hour.' }),
            el('div.winner-actions', {},
                el('button.btn', { onclick: () => { overlay.classList.add('hidden'); openReplay(); }, text: '▶ Watch replay' }),
                el('button.btn.btn-ghost', { onclick: () => overlay.classList.add('hidden'), text: 'View final table' }),
                el('button.btn.btn-ghost', { onclick: () => { window.location.href = '/'; }, text: 'Home' }),
            ),
        ),
    );
    overlay.classList.remove('hidden');
}

const MODE_LABELS = {
    sell_both_cups: { label: 'Sell both cups', desc: 'Sell both cups in a single action' },
    claim_card_free_action: { label: 'Free card claims', desc: 'Claiming a card doesn’t use your main action' },
    reroll_specials_free_action: { label: 'Free re-rolls', desc: 'Re-rolling specials doesn’t use your main action' },
};

let lobbyStrategies = null;
let lobbyModes = null;

let invite = null; // built once so re-renders keep its state

async function renderLobby() {
    document.body.classList.remove('my-turn');
    $('turnIndicator').replaceChildren(el('span.turn-other', { text: 'Waiting to start' }));
    $('myScore').hidden = true;
    const isHost = game.host === me.id;
    const isMember = game.players.includes(me.id);

    if (isHost && (lobbyStrategies === null || lobbyModes === null)) {
        try {
            [lobbyStrategies, lobbyModes] = await Promise.all([
                api.botStrategies().then((r) => r.strategies),
                api.gameModes().then((r) => r.modes),
            ]);
        } catch {
            lobbyStrategies = lobbyStrategies ?? [];
            lobbyModes = lobbyModes ?? [];
        }
    }

    const playerRows = game.players.map((pid) => el('li.lobby-player', {},
        el('span.lobby-player-name', {},
            el('span', { text: names[pid] ?? '…' }),
            pid === game.host ? el('span.lobby-host-tag', { text: '👑 host' }) : null,
        ),
        isHost && pid !== me.id
            ? el('button.btn-mini.btn-ghost', {
                onclick: () => doAction(async () => { await api.removePlayer(gameId, pid); await refresh({ announce: false }); return null; }),
                'aria-label': `Remove ${names[pid]}`, text: '✕',
            })
            : null,
    ));

    const sections = [
        el('div.lobby-card', {},
            el('h2', { text: `${names[game.host] ?? ''}'s bar` }),
            el('p.lobby-sub', { text: `${game.players.length}/4 bartenders at the bar` }),
            el('ul.lobby-players', {}, playerRows),
            !isMember ? el('button.btn', {
                onclick: () => doAction(async () => { await api.join(gameId); await refresh({ announce: false }); return null; }),
                text: '🍸 Join this game',
            }) : null,
        ),
    ];

    if (isMember && game.players.length < 4) {
        invite ??= inviteBox(gameId, {
            classes: { button: 'btn btn-ghost' },
            onCopied: (ok) => (ok ? banner('Invite link copied', { icon: '🔗' }) : toastError('Press Ctrl+C (or Cmd+C) to copy the link')),
        });
        sections.push(el('div.lobby-card', {}, invite));
    }

    if (isHost) {
        const select = el('select.lobby-select', { 'aria-label': 'Bot strategy' },
            (lobbyStrategies ?? []).map((s) => el('option', { value: s, text: s })));
        sections.push(el('div.lobby-card', {},
            el('h3', { text: 'Add a bot' }),
            el('div.lobby-row', {},
                select,
                el('button.btn.btn-ghost', {
                    onclick: () => doAction(async () => { await api.addBot(gameId, select.value); await refresh({ announce: false }); return null; }),
                    text: '+ Add bot',
                }),
            ),
        ));
        const current = new Set(game.game_state.game_modes ?? []);
        sections.push(el('div.lobby-card', {},
            el('h3', { text: 'House rules' }),
            (lobbyModes ?? []).map((mode) => {
                const meta = MODE_LABELS[mode] ?? { label: mode, desc: '' };
                const input = el('input', { type: 'checkbox', id: `mode-${mode}` });
                input.checked = current.has(mode);
                input.addEventListener('change', () => {
                    const next = (lobbyModes ?? []).filter((m) => (m === mode ? input.checked : current.has(m)));
                    doAction(async () => { await api.setModes(gameId, next); await refresh({ announce: false }); return null; });
                });
                return el('label.lobby-mode', { for: `mode-${mode}` },
                    input,
                    el('span', {}, el('strong', { text: meta.label }), el('span.lobby-mode-desc', { text: ` — ${meta.desc}` })),
                );
            }),
        ));
        sections.push(el('button.btn.btn-big', {
            onclick: () => doAction(async () => { await api.start(gameId); await refresh({ announce: false }); return null; }),
            disabled: game.players.length < 2,
            text: game.players.length < 2 ? 'Need at least 2 players' : '🍹 Open the bar!',
        }));
    } else if (isMember) {
        sections.push(el('p.lobby-waiting', {},
            el('span.waiting-dots', { 'aria-hidden': 'true' }),
            el('span', { text: ` Waiting for ${names[game.host] ?? 'the host'} to open the bar…` }),
        ));
    }

    $('players').replaceChildren();
    $('cards').replaceChildren();
    $('market').replaceChildren();
    $('mat').replaceChildren();
    $('dock').replaceChildren();
    $('board').classList.add('lobby-mode');
    $('lobby').replaceChildren(...sections);
}

// ─── Static wiring ───────────────────────────────────────────────────────────

$('footHistory').addEventListener('click', openHistorySheet);
$('footReplay').addEventListener('click', openReplay);
$('footMenu').addEventListener('click', openMenuSheet);
$('footRules').addEventListener('click', openDrinksMenu);
$('sheetBackdrop').addEventListener('click', () => closeSheet());
$('replayClose').addEventListener('click', () => {
    stopReplayAutoplay();
    $('replayOverlay').classList.add('hidden');
});
$('replayPlay').addEventListener('click', toggleReplayAutoplay);
$('replayPrev').addEventListener('click', () => { stopReplayAutoplay(); if (replayTurn > 0) showReplayTurn(replayTurn - 1); });
$('replayNext').addEventListener('click', () => {
    stopReplayAutoplay();
    if (replayTurn < Number($('replaySlider').max)) showReplayTurn(replayTurn + 1);
});
$('replaySlider').addEventListener('input', (ev) => { stopReplayAutoplay(); showReplayTurn(Number(ev.target.value)); });
document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') closeSheet();
});

boot();
