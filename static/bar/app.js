// Bar Top view — the game laid out as the physical box on a table. Every
// piece is on show; you act by touching the piece itself (a token, the bag,
// a glass, your bladder, a card). Legality comes from /valid-actions, so this
// file only decides how things look and which request a touch sends.

import { api } from '/static/play/api.js';
import {
    CARD_KINDS, COCKTAILS, ING, MIXERS, MODES, PAIRINGS, SEAT_COLOURS, SPECIALS, SPIRITS,
    cardCost, cardText, describeMove, drinkName,
} from './data.js';

const POLL_MS = 2000;
const MAX_DRUNK = 5;
const INITIAL_BLADDER = 8;
const CUP_SIZE = 5;
const gameId = new URLSearchParams(window.location.search).get('id');

let me = null;
let game = null;
let valid = { actions: [], available_types: {}, can_end_turn: false };
let moves = [];
const names = {};
let busy = false;
let lastSignature = '';
let endingShown = false;

// Local, not-yet-sent state: tokens picked off the display, where each token
// in your hand is going, which specials are picked for a re-roll, and the
// question currently asked in the turn bar.
const ui = {
    picks: [], // open-display slot indexes, in the order picked up
    pickedFrom: '', // the display the picks refer to
    staged: {}, // hand key -> { to: 'cup' | 'mouth' | 'roll', cup }
    selected: null, // hand key being placed
    reroll: new Set(), // indexes into my special_ingredients
    prompt: null, // { text, choices: [{ label, onclick, kind }] }
};

const $ = (id) => document.getElementById(id);

// ─── Tiny DOM helper ────────────────────────────────────────────────────────

function h(spec, props = {}, ...children) {
    const [tag, ...classes] = spec.split('.');
    const node = document.createElement(tag || 'div');
    if (classes.length) node.className = classes.join(' ');
    for (const [key, value] of Object.entries(props ?? {})) {
        if (value === undefined || value === null || value === false) continue;
        if (key === 'text') node.textContent = value;
        else if (key === 'svg') node.innerHTML = value; // constants from this file only
        else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
        else if (key === 'style') for (const [k, v] of Object.entries(value)) node.style.setProperty(k, v);
        else if (key === 'cls') node.classList.add(...String(value).split(' ').filter(Boolean));
        else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat(Infinity)) {
        if (child === null || child === undefined || child === false) continue;
        node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
}

function toast(message, tone = 'info') {
    const box = $('toasts');
    const note = h('div.toast', { cls: tone, role: tone === 'error' ? 'alert' : 'status', text: message });
    box.append(note);
    setTimeout(() => note.classList.add('gone'), tone === 'error' ? 5200 : 3800);
    setTimeout(() => note.remove(), tone === 'error' ? 5600 : 4200);
}

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const nameOf = (pid) => (pid === me?.id ? 'You' : (names[pid] ?? 'A player'));
const seatName = (pid) => names[pid] ?? 'A player';

// ─── Pictures ───────────────────────────────────────────────────────────────

const SPECIAL_ICONS = {
    lemon: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="12" rx="9" ry="6.5" fill="#f7d633" stroke="#8a6d00" stroke-width="1.4"/><circle cx="3.6" cy="12" r="1.3" fill="#f7d633" stroke="#8a6d00"/><path d="M8 10.5q4-2 8 0" stroke="#fff6b0" stroke-width="1.4" fill="none"/></svg>',
    cointreau: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="#f08a24" stroke="#8a4200" stroke-width="1.4"/><circle cx="12" cy="12" r="6" fill="#ffc27a"/><path d="M12 6v12M6 12h12M7.8 7.8l8.4 8.4M16.2 7.8l-8.4 8.4" stroke="#f08a24" stroke-width="1.1"/></svg>',
    sugar: '<svg viewBox="0 0 24 24"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" fill="#fff" stroke="#6b6b6b" stroke-width="1.3"/><path d="M4 7.5L12 12l8-4.5M12 12v9" stroke="#9a9a9a" stroke-width="1.1" fill="none"/></svg>',
    bitters: '<svg viewBox="0 0 24 24"><path d="M10 2h4v4l2 2v13H8V8l2-2z" fill="#7a2d12" stroke="#2b0f05" stroke-width="1.2"/><rect x="8.6" y="11" width="6.8" height="6" fill="#f3e3c3"/></svg>',
    vermouth: '<svg viewBox="0 0 24 24"><path d="M4 4h16l-8 9z" fill="#e8c9d6" stroke="#6d3a50" stroke-width="1.3"/><path d="M12 13v7M8 21h8" stroke="#6d3a50" stroke-width="1.5"/><circle cx="14" cy="7" r="1.6" fill="#5f8d2d"/></svg>',
};

const KIND_ICONS = {
    karaoke: '<svg viewBox="0 0 24 24"><rect x="9" y="2" width="6" height="11" rx="3" fill="currentColor"/><path d="M6 10a6 6 0 0 0 12 0M12 16v5M8 21h8" stroke="currentColor" stroke-width="1.8" fill="none"/></svg>',
    store: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="7" ry="2.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M5 5v14c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V5M5 10c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>',
    refresher: '<svg viewBox="0 0 24 24"><path d="M12 2v20M3.5 7l17 10M20.5 7l-17 10" stroke="currentColor" stroke-width="1.8"/><path d="M9.5 3.5L12 6l2.5-2.5M9.5 20.5L12 18l2.5 2.5" stroke="currentColor" stroke-width="1.6" fill="none"/></svg>',
    cup_doubler: '<svg viewBox="0 0 24 24"><path d="M2 11a10 7 0 0 1 20 0z" fill="currentColor"/><path d="M12 11v9a2 2 0 0 1-4 0" stroke="currentColor" stroke-width="1.8" fill="none"/></svg>',
    specialist: '<svg viewBox="0 0 24 24"><path d="M12 2l2.9 6.3 6.9.8-5.1 4.7 1.4 6.8L12 17.2 5.9 20.6l1.4-6.8L2.2 9.1l6.9-.8z" fill="currentColor"/></svg>',
    free_action: '<svg viewBox="0 0 24 24"><path d="M13 2L4 14h7l-1 8 9-12h-7z" fill="currentColor"/></svg>',
};

// Ingredient pictures, as printed on the real tokens. `currentColor` is the
// token's ink; `var(--fill)` cuts detail back out in the token's colour.
const ING_ICONS = {
    SODA: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="8.5" cy="15.5" r="4.3"/><circle cx="16" cy="12.5" r="3"/><circle cx="12.5" cy="6.8" r="2.3"/><circle cx="18.3" cy="5.6" r="1.4"/></svg>',
    COLA: '<svg viewBox="0 0 24 24"><path d="M5.5 9.5h13l-1.4 12H6.9z" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M6.4 13.5h11.2l-.9 7H7.3z" fill="currentColor"/><circle cx="10" cy="6" r="1.5" fill="currentColor"/><circle cx="14.2" cy="4.2" r="1.9" fill="currentColor"/><circle cx="12.6" cy="7.9" r="1" fill="currentColor"/></svg>',
    CRANBERRY: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 8.5C9.5 4 5 4.5 3.5 6c2.5.3 5.6 1.6 8.5 2.5zM12 8.5c2.5-4.5 7-4 8.5-2.5-2.5.3-5.6 1.6-8.5 2.5z"/><circle cx="7.6" cy="14" r="4" style="stroke:var(--fill)" stroke-width="1.2"/><circle cx="16.4" cy="14" r="4" style="stroke:var(--fill)" stroke-width="1.2"/><circle cx="12" cy="11.3" r="3.7" style="stroke:var(--fill)" stroke-width="1.2"/><circle cx="7" cy="12.8" r=".9" style="fill:var(--fill)"/><circle cx="15.8" cy="12.8" r=".9" style="fill:var(--fill)"/></svg>',
    TEQUILA: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 21L11 3.5 13 3.5z"/><path d="M12 21L6.5 6l2.2-.4z"/><path d="M12 21l5.5-15-2.2-.4z"/><path d="M12 21L2 10.5l2-1z"/><path d="M12 21l10-10.5-2-1z"/><path d="M12 21L.8 16.5l1.3-1.6z"/><path d="M12 21l11.2-4.5-1.3-1.6z"/><path d="M6 21h12v1H6z"/></svg>',
    RUM: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M2.5 15.5h19l-2.6 4.7H5.4z"/><path d="M8.3 3.5v12M15.3 2.5v13" stroke="currentColor" stroke-width="1"/><path d="M4.8 5.5q3.5 1 0 5h6.8q3.5-4 0-5zM4.3 11.2q3 .8.2 3.5h7.4q2.6-2.5 0-3.5z"/><path d="M11.8 4q3.5 1.2 0 5.6h7q3.5-4.3 0-5.6zM11.4 10.5q3 .8.2 4h7.6q2.6-3 0-4z"/><path d="M15.3 2.5l3 .9-3 .9z"/><circle cx="8.3" cy="17.6" r=".75" style="fill:var(--fill)"/><circle cx="12" cy="17.6" r=".75" style="fill:var(--fill)"/><circle cx="15.7" cy="17.6" r=".75" style="fill:var(--fill)"/></svg>',
    WHISKEY: '<svg viewBox="0 0 24 24"><path d="M6.2 3h11.6q2.6 9 0 18H6.2q-2.6-9 0-18z" fill="currentColor"/><path d="M5.3 7.5h13.4M5.3 16.5h13.4" style="stroke:var(--fill)" stroke-width="1.3"/><path d="M10 3.2v17.6M14 3.2v17.6" style="stroke:var(--fill)" stroke-width=".8"/></svg>',
    VODKA: '<svg viewBox="0 0 24 24"><path d="M4.5 3.5h15l-2.2 17H6.7z" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M6.4 11.5h11.2l-1.2 7.5H7.6z" fill="currentColor"/></svg>',
    GIN: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 22c0-6 1-11 4-17" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M13 13c-3-1-6-3-7.5-6 3 .4 6 2.2 7.5 6zM14.4 9.5c2.8-1 5-3 6-5.8-2.8.8-5.2 2.8-6 5.8z"/><circle cx="8.3" cy="15.7" r="2.4"/><circle cx="12.3" cy="18" r="2.2"/><circle cx="17.3" cy="13.6" r="2.3"/><circle cx="7.6" cy="15" r=".7" style="fill:var(--fill)"/></svg>',
    TONIC: '<svg viewBox="0 0 24 24"><path d="M2.5 7.5a9.5 9.5 0 0 0 19 0z" fill="currentColor"/><path d="M4.3 8.8a7.7 7.7 0 0 0 15.4 0z" style="fill:var(--fill)"/><path d="M5.6 8.8a6.4 6.4 0 0 0 12.8 0z" fill="currentColor"/><path d="M12 8.8v6.4M12 8.8l-4.6 4.4M12 8.8l4.6 4.4M12 8.8L5.8 10.8M12 8.8l6.2 2" style="stroke:var(--fill)" stroke-width="1.1"/></svg>',
    SPECIAL: '<svg viewBox="0 0 24 24"><polygon fill="currentColor" points="12.0,1.5 13.8,5.2 17.2,2.9 16.9,7.1 21.1,6.8 18.8,10.2 22.5,12.0 18.8,13.8 21.1,17.2 16.9,16.9 17.2,21.1 13.8,18.8 12.0,22.5 10.2,18.8 6.8,21.1 7.1,16.9 2.9,17.3 5.2,13.8 1.5,12.0 5.2,10.2 2.9,6.7 7.1,7.1 6.7,2.9 10.2,5.2"/><polygon style="fill:var(--fill)" points="12.0,8.0 13.0,10.6 15.8,10.8 13.6,12.5 14.4,15.2 12.0,13.7 9.6,15.2 10.4,12.5 8.2,10.8 11.0,10.6"/></svg>',
    ANY_SPIRIT: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M8.5 8.5a3.5 3.5 0 1 1 5 3.2c-1 .5-1.5 1.2-1.5 2.3v.8"/><circle cx="12" cy="18.6" r=".6" fill="currentColor"/></svg>',
};

const TOKEN_NAMES = {
    WHISKEY: 'Whisky', SODA: 'Soda', TONIC: 'Tonic', SPECIAL: 'Special', ANY_SPIRIT: 'Any',
};

// A token, drawn like the real ones: a thick coloured disc with an engraved
// ring, a picture, and the name round the bottom (on the bigger tokens).
// `name` is an ingredient key, 'ANY_SPIRIT', or a rolled special ('lemon'…).
function token(name, { onclick, label, state, selected, key, small } = {}) {
    const special = SPECIALS[name];
    const meta = ING[name];
    const kind = special ? 'rolled' : meta?.kind ?? 'spirit';
    const text = special?.label ?? meta?.label ?? 'Any one spirit';
    const printed = special?.label ?? TOKEN_NAMES[name] ?? meta?.label ?? '';
    const node = h(onclick ? 'button.tok' : 'span.tok', {
        cls: `tok-${kind} ing-${name.toLowerCase()}${state ? ` is-${state}` : ''}${selected ? ' is-selected' : ''}${small ? ' tok-small' : ''}`,
        style: { '--len': String(Math.max(printed.length, 4)) },
        type: onclick ? 'button' : undefined,
        onclick,
        'aria-label': label ?? text,
        'aria-pressed': onclick && selected !== undefined ? String(!!selected) : undefined,
        title: label ?? text,
        'data-k': key,
        role: onclick ? undefined : 'img',
    });
    node.append(h('span.tok-icon', { svg: special ? SPECIAL_ICONS[name] : ING_ICONS[name] ?? '', 'aria-hidden': 'true' }));
    if (!small) node.append(h('span.tok-name', { text: printed, 'aria-hidden': 'true' }));
    return node;
}

function slot(child, cls = '') {
    return h('span.slot', { cls }, child);
}

// ─── Loading and polling ────────────────────────────────────────────────────

async function boot() {
    if (!gameId) {
        window.location.href = '/';
        return;
    }
    try {
        me = await api.me();
        await refresh();
    } catch (e) {
        if (e.status === 403 || e.status === 404) {
            $('table').replaceChildren(h('p.empty-table', { text: 'This game is private or no longer exists.' }),
                h('a.btn', { href: '/', text: 'Back to the games' }));
            return;
        }
        toast(e.message, 'error');
    }
    setInterval(() => {
        if (!busy && document.visibilityState === 'visible') refresh().catch(() => {});
    }, POLL_MS);
}

async function ensureNames(g) {
    const missing = [...new Set([g.host, ...g.players])].filter((id) => !names[id]);
    await Promise.all(missing.map(async (id) => {
        try {
            names[id] = (await api.user(id)).username ?? 'A player';
        } catch {
            names[id] = 'A player';
        }
    }));
}

async function refresh() {
    const g = await api.game(gameId);
    await ensureNames(g);
    const before = JSON.stringify(game?.game_state ?? null) + game?.status;
    game = g;
    if (g.status === 'STARTED') {
        valid = await api.validActions(gameId).catch(() => valid);
    } else {
        valid = { actions: [], available_types: {}, can_end_turn: false };
    }
    if (g.status !== 'NEW' && (before !== JSON.stringify(g.game_state) + g.status || !moves.length)) {
        await loadMoves(true);
    }
    render();
}

async function loadMoves(announce) {
    try {
        const { moves: all } = await api.history(gameId);
        if (announce && moves.length) {
            for (const move of all.slice(moves.length)) {
                if (move.player_id !== me.id) toast(describeMove(move, nameOf));
            }
        }
        moves = all;
    } catch {
        // The log is a nicety; the table still works without it.
    }
}

// Run one request, then show the state it returns straight away.
async function act(request, { after } = {}) {
    if (busy) return null;
    busy = true;
    ui.prompt = null;
    document.body.classList.add('is-busy');
    try {
        const result = await request();
        if (result?.game_state) {
            game.game_state = result.game_state;
            valid = game.status === 'STARTED' && !result.game_state.winner
                ? await api.validActions(gameId).catch(() => valid)
                : valid;
        }
        after?.(result);
        await loadMoves(false);
        return result;
    } catch (e) {
        toast(e.message, 'error');
        await refresh().catch(() => {});
        return null;
    } finally {
        busy = false;
        document.body.classList.remove('is-busy');
        render({ force: true });
    }
}

// ─── Reading the state ──────────────────────────────────────────────────────

const gs = () => game.game_state;
const mine = () => gs().player_states[me.id];
const isMember = () => game.players.includes(me.id);
const myTurn = () => game.status === 'STARTED' && !gs().winner && gs().player_turn === me.id;
const can = (type) => myTurn() && Object.prototype.hasOwnProperty.call(valid.available_types ?? {}, type);
const actionsOf = (type) => (myTurn() ? (valid.actions ?? []).filter((a) => a.action_type === type) : []);
const isFree = (type) => !!valid.available_types?.[type]?.is_free;
const freeNote = (type) => (isFree(type) && gs().main_action_taken_this_turn ? ' (free)' : '');
const takeUnderway = () => myTurn() && (gs().ingredients_taken_this_turn > 0 || gs().bag_draw_pending.length > 0);

function seatOrder() {
    const order = gs()?.turn_order?.length ? gs().turn_order : game.players;
    return order.filter((pid) => gs().player_states?.[pid]);
}

const seatColour = (pid) => SEAT_COLOURS[Math.max(0, seatOrder().indexOf(pid)) % SEAT_COLOURS.length];

function handItems() {
    if (!myTurn()) return [];
    const pending = gs().bag_draw_pending.map((name, i) => ({ key: `p${i}`, name, source: 'pending' }));
    const picks = ui.picks.map((slotIndex) => ({
        key: `d${slotIndex}`, name: gs().open_display[slotIndex], source: 'display', slotIndex,
    }));
    return [...pending, ...picks];
}

const takeLeft = () => (mine() ? mine().take_count - gs().ingredients_taken_this_turn - handItems().length : 0);
const stagedTo = (to, cup) => handItems().filter((it) => ui.staged[it.key]?.to === to
    && (cup === undefined || ui.staged[it.key].cup === cup));

// Keep local state honest when the table changes underneath it.
function reconcile() {
    if (!myTurn() || ui.pickedFrom !== gs().open_display.join()) {
        ui.picks = [];
    }
    const keys = new Set(handItems().map((it) => it.key));
    for (const key of Object.keys(ui.staged)) if (!keys.has(key)) delete ui.staged[key];
    for (const it of handItems()) {
        if (ING[it.name]?.kind === 'special') ui.staged[it.key] = { to: 'roll' };
    }
    if (ui.selected && (!keys.has(ui.selected) || ui.staged[ui.selected])) ui.selected = null;
    if (!ui.selected) ui.selected = handItems().find((it) => !ui.staged[it.key])?.key ?? null;
    const specials = mine()?.special_ingredients ?? [];
    for (const i of [...ui.reroll]) if (i >= specials.length || !can('reroll_specials')) ui.reroll.delete(i);
    if (!myTurn()) ui.prompt = null;
}

// How drunk you'd be after drinking `extra` on top of what this turn has
// already drunk (the drunk track only moves once the whole take is done).
function drunkAfter(extra) {
    const ps = mine();
    const refreshers = new Set(ps.cards.filter((c) => c.card_type === 'refresher').map((c) => c.mixer_type));
    const drunk = [...gs().drunk_ingredients_this_turn, ...extra];
    const spirits = drunk.filter((i) => ING[i]?.kind === 'spirit').length;
    const hot = drunk.filter((i) => ING[i]?.kind === 'mixer' && refreshers.has(i)).length;
    const plain = drunk.filter((i) => ING[i]?.kind === 'mixer' && !refreshers.has(i)).length;
    let delta = spirits - hot;
    if (!spirits) delta -= plain;
    return Math.max(0, ps.drunk_level + delta);
}

// ─── Player moves ───────────────────────────────────────────────────────────

function ask(text, choices) {
    ui.prompt = { text, choices };
    render({ force: true });
    document.querySelector('#turnbar [data-k="prompt-0"]')?.focus();
}

function pickFromDisplay(slotIndex) {
    if (ui.picks.includes(slotIndex)) {
        ui.picks = ui.picks.filter((s) => s !== slotIndex);
        delete ui.staged[`d${slotIndex}`];
        render({ force: true });
        return;
    }
    if (takeLeft() < 1) {
        toast(`Your hand is full: you take ${mine().take_count} this turn. Place what you're holding first.`, 'error');
        return;
    }
    ui.pickedFrom = gs().open_display.join();
    ui.picks.push(slotIndex);
    ui.selected = `d${slotIndex}`;
    render({ force: true });
}

function drawFromBag(count) {
    act(() => api.drawFromBag(gameId, count), {
        after: () => { ui.selected = null; },
    });
}

function selectInHand(key) {
    if (ui.staged[key]?.to === 'roll') return;
    delete ui.staged[key];
    ui.selected = ui.selected === key ? null : key;
    render({ force: true });
}

function placeSelected(to, cup) {
    const item = handItems().find((it) => it.key === ui.selected);
    if (!item) return;
    if (to === 'cup') {
        const inCup = mine().cups[cup].ingredients.length + stagedTo('cup', cup).length;
        if (inCup >= CUP_SIZE) {
            toast(`Glass ${cup + 1} is full: five ingredients is the limit.`, 'error');
            return;
        }
    }
    ui.staged[item.key] = { to, cup };
    ui.selected = handItems().find((it) => !ui.staged[it.key])?.key ?? null;
    render({ force: true });
}

function finishPlacing() {
    const items = handItems();
    if (items.some((it) => !ui.staged[it.key])) {
        toast('Put everything in your hand into a glass or your mouth first.', 'error');
        return;
    }
    const assignments = items.map((it) => {
        const where = ui.staged[it.key];
        return {
            ingredient: it.name,
            source: it.source,
            disposition: where.to === 'cup' ? 'cup' : 'drink',
            cup_index: where.to === 'cup' ? where.cup : 0,
        };
    });
    const drinks = items.filter((it) => ui.staged[it.key].to === 'mouth').map((it) => it.name);
    const finishing = mine().take_count - gs().ingredients_taken_this_turn - items.length === 0;
    const run = () => act(() => api.takeIngredients(gameId, assignments), {
        after: (result) => {
            ui.picks = [];
            ui.staged = {};
            ui.selected = null;
            for (const record of result?.move?.taken ?? []) {
                if (record.disposition !== 'special') continue;
                toast(record.special_type === 'nothing'
                    ? 'The die came up blank. It goes back in the bag.'
                    : `You rolled ${SPECIALS[record.special_type]?.label}. It's on your mat.`);
            }
            const status = result?.game_state?.player_states?.[me.id]?.status;
            if (status === 'hospitalised') toast('You passed out and went to hospital. You are out of the game.', 'error');
            if (status === 'wet') toast('Your bladder gave way. You are out of the game.', 'error');
        },
    });
    const ps = mine();
    const overflow = ps.bladder.length + drinks.length > ps.bladder_capacity;
    const hospital = finishing && drunkAfter(drinks) > MAX_DRUNK;
    if (overflow || hospital) {
        ask(overflow ? 'That overflows your bladder and puts you out of the game.' : 'That much drink puts you in hospital and out of the game.', [
            { label: 'Drink it anyway', onclick: run, kind: 'danger' },
            { label: 'Think again', onclick: () => { ui.prompt = null; render({ force: true }); } },
        ]);
        return;
    }
    run();
}

function sell(params) {
    const body = { cup_index: params.cup_index, declared_specials: params.declared_specials ?? [] };
    if (params.additional_cups) body.additional_cups = params.additional_cups;
    act(() => api.sellCup(gameId, body), {
        after: (result) => {
            const earned = result?.move?.points_earned;
            if (earned !== undefined) toast(`Sold for ${plural(earned, 'point')}.`);
        },
    });
}

function drinkCup(cupIndex) {
    const ps = mine();
    const contents = ps.cups[cupIndex].ingredients;
    const run = () => act(() => api.drinkCup(gameId, cupIndex));
    const overflow = ps.bladder.length + contents.length > ps.bladder_capacity;
    const hospital = drunkAfter(contents) > MAX_DRUNK;
    ask(overflow ? `Drinking glass ${cupIndex + 1} overflows your bladder and puts you out.`
        : hospital ? `Drinking glass ${cupIndex + 1} puts you in hospital and out of the game.`
            : `Drink everything in glass ${cupIndex + 1}? That's your action for the turn.`, [
        { label: 'Drink it', onclick: run, kind: overflow || hospital ? 'danger' : 'go' },
        { label: 'Keep it', onclick: () => { ui.prompt = null; render({ force: true }); } },
    ]);
}

function wee() {
    act(() => api.goForAWee(gameId), { after: () => toast('Much better. One level more sober.') });
}

function claim(card) {
    const options = actionsOf('claim_card').filter((a) => a.params.card_id === card.id);
    if (!options.length) return;
    const points = CARD_KINDS[card.card_type]?.points ?? 0;
    const send = (params) => act(() => api.claimCard(gameId, params), {
        after: (result) => { if (result) toast(`${card.name} is yours: ${plural(points, 'point')}.`); },
    });
    const back = { label: 'Leave it', onclick: () => { ui.prompt = null; render({ force: true }); } };
    if (card.card_type === 'cup_doubler') {
        ask(`${card.name}: which glass does it go on, and which three spirits pay for it?`, [
            ...options.map((a) => ({
                label: `Glass ${a.params.cup_index + 1}, paid with ${ING[a.params.spirit_type]?.label ?? a.params.spirit_type}`,
                onclick: () => send(a.params),
                kind: 'go',
            })),
            back,
        ]);
        return;
    }
    const extra = card.card_type === 'store'
        ? ` All the ${ING[card.spirit_type].label} in your bladder moves onto it.` : '';
    const free = isFree('claim_card') ? ' It doesn’t use your action.' : '';
    ask(`Claim ${card.name} for ${plural(points, 'point')}?${extra}${free}`, [
        { label: 'Claim it', onclick: () => send(options[0].params), kind: 'go' },
        back,
    ]);
}

function clearRow(position) {
    ask(`Clear card row ${position}? Its cards go to the discard pile and new ones are dealt.`, [
        { label: 'Clear the row', onclick: () => act(() => api.refreshCardRow(gameId, position)), kind: 'go' },
        { label: 'Leave it', onclick: () => { ui.prompt = null; render({ force: true }); } },
    ]);
}

function toggleReroll(i) {
    if (ui.reroll.has(i)) ui.reroll.delete(i);
    else ui.reroll.add(i);
    render({ force: true });
}

function reroll() {
    const specials = mine().special_ingredients;
    const chosen = [...ui.reroll].sort((a, b) => a - b).map((i) => specials[i]);
    ui.reroll.clear();
    act(() => api.rerollSpecials(gameId, chosen), {
        after: (result) => {
            const got = (result?.move?.results ?? []).map((r) => (r ? SPECIALS[r]?.label ?? r : 'a blank'));
            if (got.length) toast(`You rolled ${got.join(', ')}.`);
        },
    });
}

function storeDrink(cardIndex) {
    act(() => api.drinkStoredSpirit(gameId, cardIndex, 1));
}

function storePour(cardIndex, cupIndex) {
    act(() => api.useStoredSpirit(gameId, cardIndex, cupIndex));
}

function endTurn() {
    act(() => api.endTurn(gameId));
}

function confirmLeave() {
    const host = game.host === me.id;
    ask(host ? 'Call off the game for everyone?' : 'Leave the game? You can’t come back to it.', [
        {
            label: host ? 'Call it off' : 'Leave the game',
            kind: 'danger',
            onclick: () => act(() => (host ? api.cancel(gameId) : api.quit(gameId)), {
                after: () => refresh().catch(() => {}),
            }),
        },
        { label: 'Stay', onclick: () => { ui.prompt = null; render({ force: true }); } },
    ]);
}

function proposeUndo() {
    act(async () => {
        await api.proposeUndo(gameId);
        await refresh();
        toast('Asked the table to take back the last turn.');
        return null;
    });
}

function voteUndo(vote) {
    act(async () => {
        await api.voteUndo(gameId, game.pending_undo.id, vote);
        await refresh();
        return null;
    });
}

// ─── The turn bar ───────────────────────────────────────────────────────────

function turnbar() {
    const bar = $('turnbar');
    const state = gs();
    const kids = [];
    let tone = 'wait';
    let headline;
    let detail = '';

    if (game.status === 'NEW') {
        headline = game.host === me?.id ? 'Seat your players, then open the bar' : 'Waiting for the host to open the bar';
    } else if (state.winner) {
        tone = state.winner === me.id ? 'win' : 'wait';
        headline = state.winner === me.id ? 'You won!' : `${seatName(state.winner)} won the game`;
    } else if (game.status === 'ENDED') {
        headline = 'This game was called off';
    } else if (myTurn()) {
        tone = 'you';
        headline = 'Your turn';
        const left = mine().take_count - state.ingredients_taken_this_turn;
        const hand = handItems();
        if (hand.length) {
            const unplaced = hand.filter((it) => !ui.staged[it.key]).length;
            detail = unplaced
                ? `Tap a glass or your mouth to put down the ${ING[hand.find((it) => it.key === ui.selected)?.name]?.label ?? 'token'} you're holding.`
                : 'Everything is placed. Press "Done placing" on your mat.';
        } else if (takeUnderway()) {
            detail = `Take ${plural(left, 'more ingredient')}: tap tokens on the display or draw from the bag.`;
        } else if (state.main_action_taken_this_turn) {
            detail = 'You can still use a free action, or end your turn.';
        } else {
            detail = `Take ${plural(mine().take_count, 'ingredient')}, or sell or drink a glass, go for a wee, claim a card or re-roll.`;
        }
    } else {
        headline = `${seatName(state.player_turn)} is playing`;
        const ps = mine();
        if (ps && ps.status !== 'active') detail = ps.status === 'hospitalised' ? 'You’re in hospital, out of this game.' : 'You wet yourself and are out of this game.';
    }
    if (state?.last_round && !state.winner && game.status === 'STARTED') detail = `${detail} Last round: everyone gets one more turn.`.trim();

    kids.push(h('div.turn-words', {},
        h('p.turn-head', { text: headline }),
        detail ? h('p.turn-detail', { text: detail }) : null));

    const buttons = [];
    if (myTurn() && valid.can_end_turn && !handItems().length) {
        buttons.push(h('button.btn.go', { type: 'button', onclick: endTurn, text: 'End turn', 'data-k': 'end-turn' }));
    }
    if (buttons.length) kids.push(h('div.turn-buttons', {}, buttons));

    const undo = game.pending_undo;
    if (undo && undo.status === 'pending') {
        const voted = (undo.votes ?? {})[me.id] !== undefined;
        kids.push(h('div.prompt', { role: 'group', 'aria-label': 'Undo request' },
            h('p', { text: `${nameOf(undo.proposed_by)} asked to take back the last turn.` }),
            voted ? h('p.prompt-note', { text: 'Waiting for everyone to answer.' })
                : h('div.prompt-choices', {},
                    h('button.btn.go', { type: 'button', onclick: () => voteUndo('agree'), text: 'Agree', 'data-k': 'undo-yes' }),
                    h('button.btn', { type: 'button', onclick: () => voteUndo('disagree'), text: 'Disagree', 'data-k': 'undo-no' }))));
    }
    if (ui.prompt) {
        kids.push(h('div.prompt', { role: 'group', 'aria-label': 'Question' },
            h('p', { text: ui.prompt.text }),
            h('div.prompt-choices', {}, ui.prompt.choices.map((c, i) => h('button.btn', {
                type: 'button', cls: c.kind, onclick: c.onclick, text: c.label, 'data-k': `prompt-${i}`,
            })))));
    }
    bar.className = `turnbar tone-${tone}`;
    bar.replaceChildren(...kids);
}

// ─── Cards ──────────────────────────────────────────────────────────────────

function bladderCounts(ps) {
    const counts = {};
    for (const i of ps?.bladder ?? []) counts[i] = (counts[i] ?? 0) + 1;
    return counts;
}

function costTokens(card, ps) {
    const cost = cardCost(card);
    const have = bladderCounts(ps);
    if (card.card_type === 'karaoke' && ps) {
        for (const c of ps.cards) if (c.card_type === 'store' && c.spirit_type === card.spirit_type) {
            have[card.spirit_type] = (have[card.spirit_type] ?? 0) + (c.stored_spirits?.length ?? 0);
        }
    }
    if (card.card_type === 'cup_doubler') {
        const best = Math.max(0, ...SPIRITS.map((s) => have[s] ?? 0));
        return cost.map((name, i) => token(name, { small: true, state: ps && i >= best ? 'missing' : undefined }));
    }
    return cost.map((name, i) => token(name, { small: true, state: ps && i >= (have[name] ?? 0) ? 'missing' : undefined }));
}

function cardFace(card, { claimable, owner, index, compact } = {}) {
    const kind = CARD_KINDS[card.card_type] ?? { label: 'Card', points: 0 };
    const ps = owner ? null : (game.status === 'STARTED' && mine()?.status === 'active' ? mine() : null);
    const cost = cardCost(card);
    const costLabel = card.card_type === 'cup_doubler'
        ? 'three of any one spirit'
        : `${cost.length} ${ING[cost[0]]?.label ?? ''}`;
    const label = `${card.name}, ${kind.label} card, ${plural(kind.points, 'point')}. ${cardText(card)} Needs ${costLabel} in your bladder.${claimable ? ' You can claim it.' : ''}`;
    const face = h(claimable ? 'button.card' : 'div.card', {
        cls: `kind-${card.card_type}${claimable ? ' is-claimable' : ''}${compact ? ' is-compact' : ''}`,
        type: claimable ? 'button' : undefined,
        onclick: claimable ? () => claim(card) : undefined,
        'aria-label': label,
        role: claimable ? undefined : 'group',
        'data-k': claimable ? `card-${card.id}` : undefined,
    },
    h('span.card-band', {},
        h('span.card-kind-icon', { svg: KIND_ICONS[card.card_type] ?? '', 'aria-hidden': 'true' }),
        h('span.card-kind', { text: kind.label }),
        h('span.card-points', { text: kind.points, 'aria-hidden': 'true' })),
    h('span.card-name', { text: card.name }),
    compact ? null : h('span.card-text', { text: cardText(card) }),
    h('span.card-cost', { 'aria-hidden': 'true' }, costTokens(card, owner ? null : ps)));

    if (card.card_type === 'store' && owner) {
        face.append(h('span.card-store', { 'aria-label': `${plural(card.stored_spirits.length, 'spirit')} stored` },
            card.stored_spirits.length
                ? card.stored_spirits.map((s) => token(s, { small: true }))
                : h('span.card-store-empty', { text: 'Empty' })));
        if (owner === me.id && index !== undefined) {
            const drink = actionsOf('drink_stored_spirit').some((a) => a.params.store_card_index === index && a.params.count === 1);
            const pours = actionsOf('use_stored_spirit').filter((a) => a.params.store_card_index === index);
            if (drink || pours.length) {
                face.append(h('span.card-actions', {},
                    drink ? h('button.btn.tiny', { type: 'button', onclick: () => storeDrink(index), text: 'Drink one', 'data-k': `sdrink-${index}` }) : null,
                    pours.map((a) => h('button.btn.tiny', {
                        type: 'button', onclick: () => storePour(index, a.params.cup_index),
                        text: `Pour into glass ${a.params.cup_index + 1}`, 'data-k': `spour-${index}-${a.params.cup_index}`,
                    }))));
            }
        }
    }
    return face;
}

function cardBack(count, label) {
    return h('div.pile', { role: 'img', 'aria-label': label },
        count ? h('div.card.card-back', {}, h('span.back-mark', { text: 'Bartenders of Corfu' })) : h('div.card-space'),
        h('span.pile-count', { text: count ? plural(count, 'card') : 'Empty' }));
}

function renderMarket() {
    const state = gs();
    const claimable = new Set(actionsOf('claim_card').map((a) => a.params.card_id));
    const clearable = new Set(actionsOf('refresh_card_row').map((a) => a.params.row_position));
    const discard = state.discard ?? [];
    const topDiscard = discard[discard.length - 1];

    const rows = [1, 2, 3].map((position) => {
        const row = state.card_rows.find((r) => r.position === position) ?? { cards: [] };
        const cells = [0, 1, 2].map((i) => (row.cards[i]
            ? cardFace(row.cards[i], { claimable: claimable.has(row.cards[i].id) })
            : h('div.card-space', { role: 'img', 'aria-label': 'Empty slot' })));
        return h('div.card-row', { 'aria-label': position === 1 ? 'Karaoke row' : `Card row ${position}`, role: 'group' },
            h('div.row-tag', {},
                h('span', { text: position === 1 ? 'Karaoke stage' : `Row ${position}` }),
                position === 1 ? h('span.row-note', { text: 'Never cleared' })
                    : clearable.has(position)
                        ? h('button.btn.tiny', { type: 'button', onclick: () => clearRow(position), text: 'Clear row', 'data-k': `clear-${position}` })
                        : h('span.row-note', { text: 'Clear at drunk 3+' })),
            h('div.row-cards', {}, cells));
    });

    return h('section.market', { 'aria-label': 'Cards' },
        h('div.piles', {},
            cardBack(state.deck_size, `Draw deck, ${plural(state.deck_size, 'card')} left`),
            h('div.pile', { role: 'group', 'aria-label': `Discard pile, ${plural(discard.length, 'card')}` },
                topDiscard ? cardFace(topDiscard, { compact: true, owner: 'discard' }) : h('div.card-space'),
                h('span.pile-count', { text: discard.length ? `${plural(discard.length, 'card')} discarded` : 'No discards' }))),
        h('div.rows', {}, rows));
}

// ─── Bag and open display ───────────────────────────────────────────────────

function renderSupply() {
    const state = gs();
    const taking = can('take_ingredients');
    const pendingDraw = state.bag_draw_pending.length > 0;
    const left = taking ? takeLeft() : 0;
    const maxDraw = taking && !pendingDraw ? Math.min(left, state.bag_contents.length) : 0;

    const display = h('div.display', { role: 'group', 'aria-label': 'Open display' },
        Array.from({ length: 5 }, (_, i) => {
            const name = state.open_display[i];
            if (!name) return slot(null, 'is-empty');
            const picked = ui.picks.includes(i);
            if (picked) {
                return slot(token(name, {
                    state: 'lifted', key: `disp-${i}`,
                    label: `${ING[name].label} is in your hand. Tap to put it back.`,
                    onclick: () => pickFromDisplay(i),
                }), 'is-lifted');
            }
            const canPick = taking && left > 0;
            return slot(token(name, {
                key: `disp-${i}`,
                label: canPick ? `Take the ${ING[name].label}` : ING[name].label,
                onclick: canPick ? () => pickFromDisplay(i) : undefined,
                state: canPick ? 'takeable' : undefined,
            }));
        }));

    const bag = h('div.bag-wrap', {},
        h('div.bag', { role: 'img', 'aria-label': `The bag, ${plural(state.bag_contents.length, 'ingredient')} inside` },
            h('span.bag-neck', { 'aria-hidden': 'true' }),
            h('span.bag-body', {}, h('span.bag-count', { text: state.bag_contents.length }), h('span.bag-word', { text: 'in the bag' }))),
        maxDraw > 0
            ? h('div.draws', { role: 'group', 'aria-label': 'Draw blind from the bag' },
                h('span.draws-label', { text: 'Draw blind' }),
                Array.from({ length: maxDraw }, (_, i) => h('button.btn.tiny', {
                    type: 'button', onclick: () => drawFromBag(i + 1), text: i + 1,
                    'aria-label': `Draw ${i + 1} from the bag`, 'data-k': `draw-${i + 1}`,
                })))
            : taking && pendingDraw ? h('p.bag-note', { text: 'Place what you drew before drawing again.' }) : null);

    return h('section.supply', { 'aria-label': 'Ingredients' }, bag, display);
}

// ─── Score track ────────────────────────────────────────────────────────────

function renderScoreTrack() {
    const seats = seatOrder();
    const cells = Array.from({ length: 41 }, (_, n) => {
        const here = seats.filter((pid) => Math.min(40, gs().player_states[pid].points) === n);
        return h('li.score-cell', { cls: n % 5 === 0 ? 'is-five' : n === 40 ? 'is-goal' : '' },
            n % 5 === 0 ? h('span.score-num', { text: n === 40 ? '40 wins' : n, 'aria-hidden': 'true' }) : null,
            here.map((pid) => h('span.pawn', {
                style: { '--seat': seatColour(pid) }, role: 'img',
                'aria-label': `${seatName(pid)}: ${plural(gs().player_states[pid].points, 'point')}`,
            })));
    });
    return h('section.score', { 'aria-label': 'Score track' },
        h('h2.plaque', { text: 'Score track' }),
        h('ol.score-track', {}, cells));
}

// ─── Player mats ────────────────────────────────────────────────────────────

function glass(pid, cupIndex, { interactive }) {
    const ps = gs().player_states[pid];
    const cup = ps.cups[cupIndex];
    const incoming = interactive ? stagedTo('cup', cupIndex) : [];
    const placing = interactive && ui.selected;
    const room = cup.ingredients.length + incoming.length < CUP_SIZE;
    const contents = [
        ...cup.ingredients.map((name) => token(name, { small: true })),
        ...incoming.map((it) => token(it.name, {
            small: true, state: 'placed', key: `staged-${it.key}`,
            label: `${ING[it.name].label} going into glass ${cupIndex + 1}. Tap to pick it back up.`,
            onclick: () => selectInHand(it.key),
        })),
    ];
    const layers = Array.from({ length: CUP_SIZE }, (_, i) => slot(contents[i] ?? null, contents[i] ? '' : 'is-empty'));

    const vessel = h(placing && room ? 'button.glass' : 'div.glass', {
        cls: `${placing && room ? 'is-target' : ''}${cup.has_cup_doubler ? ' has-doubler' : ''}`,
        type: placing && room ? 'button' : undefined,
        onclick: placing && room ? () => placeSelected('cup', cupIndex) : undefined,
        'aria-label': `Glass ${cupIndex + 1}: ${cup.ingredients.length ? cup.ingredients.map((i) => ING[i].label).join(', ') : 'empty'}${cup.has_cup_doubler ? ', scores double' : ''}${placing && room ? '. Tap to put the token here.' : ''}`,
        'data-k': placing && room ? `glass-${cupIndex}` : undefined,
    },
    cup.has_cup_doubler ? h('span.straw', { 'aria-hidden': 'true' }) : null,
    h('span.glass-body', {}, layers),
    h('span.glass-foot', { 'aria-hidden': 'true' }));

    const buttons = [];
    if (interactive && !handItems().length) {
        for (const a of actionsOf('sell_cup').filter((x) => x.params.cup_index === cupIndex && !x.params.additional_cups)) {
            const specials = a.params.declared_specials ?? [];
            buttons.push(h('button.btn.go.tiny', {
                type: 'button', onclick: () => sell(a.params), 'data-k': `sell-${cupIndex}-${specials.join('-')}`,
                'aria-label': `Sell glass ${cupIndex + 1} as ${drinkName(cup.ingredients, specials)} for ${plural(a.params.points, 'point')}`,
            }, h('strong', { text: `Sell for ${a.params.points}${freeNote('sell_cup')}` }), h('span', { text: drinkName(cup.ingredients, specials) })));
        }
        if (actionsOf('drink_cup').some((a) => a.params.cup_index === cupIndex)) {
            buttons.push(h('button.btn.tiny', { type: 'button', onclick: () => drinkCup(cupIndex), text: 'Drink it', 'data-k': `drinkcup-${cupIndex}` }));
        }
    }
    return h('div.glass-spot', {},
        vessel,
        h('span.glass-label', { text: `Glass ${cupIndex + 1}${cup.has_cup_doubler ? ', doubled' : ''}` }),
        buttons.length ? h('div.glass-actions', {}, buttons) : null);
}

// Only with the "sell both cups" house rule: one action sells both glasses.
function sellBoth() {
    if (handItems().length) return null;
    const options = actionsOf('sell_cup').filter((a) => a.params.additional_cups?.length);
    if (!options.length) return null;
    const cups = mine().cups;
    return h('div.sell-both', {}, options.map((a) => {
        const second = a.params.additional_cups[0];
        const names = `${drinkName(cups[a.params.cup_index].ingredients, a.params.declared_specials ?? [])} and ${drinkName(cups[second.cup_index].ingredients, second.declared_specials ?? [])}`;
        return h('button.btn.go.tiny', {
            type: 'button', onclick: () => sell(a.params), 'data-k': `sellboth-${JSON.stringify(a.params)}`,
            'aria-label': `Sell both glasses, ${names}, for ${plural(a.params.points, 'point')}`,
        }, h('strong', { text: `Sell both for ${a.params.points}${freeNote('sell_cup')}` }), h('span', { text: names }));
    }));
}

function mouth() {
    const drinks = stagedTo('mouth');
    const placing = !!ui.selected;
    const after = drunkAfter(drinks.map((it) => it.name));
    const node = h(placing ? 'button.mouth' : 'div.mouth', {
        cls: placing ? 'is-target' : '',
        type: placing ? 'button' : undefined,
        onclick: placing ? () => placeSelected('mouth') : undefined,
        'aria-label': placing ? 'Your mouth: tap to drink the token you are holding' : 'Your mouth',
        'data-k': placing ? 'mouth' : undefined,
    },
    h('span.lips', { 'aria-hidden': 'true' }),
    h('span.mouth-word', { text: 'Drink' }));
    return h('div.mouth-spot', {},
        node,
        h('div.mouth-tokens', {}, drinks.map((it) => token(it.name, {
            small: true, state: 'placed', key: `staged-${it.key}`,
            label: `${ING[it.name].label} to drink. Tap to pick it back up.`,
            onclick: () => selectInHand(it.key),
        }))),
        drinks.length || gs().drunk_ingredients_this_turn.length
            ? h('span.mouth-note', { cls: after > MAX_DRUNK ? 'is-danger' : '', text: after > MAX_DRUNK ? 'Hospital!' : `Drunk ${after} after this turn` })
            : null);
}

function bladder(pid, { interactive }) {
    const ps = gs().player_states[pid];
    const incoming = interactive ? stagedTo('mouth') : [];
    const sealed = INITIAL_BLADDER - ps.bladder_capacity;
    const filled = [...ps.bladder.map((n) => ({ n })), ...incoming.map((it) => ({ n: it.name, staged: true }))];
    const slots = Array.from({ length: INITIAL_BLADDER }, (_, i) => {
        if (i >= ps.bladder_capacity) return slot(h('span.loo', { role: 'img', 'aria-label': 'Sealed by a toilet token' }), 'is-sealed');
        const f = filled[i];
        return slot(f ? token(f.n, { small: true, state: f.staged ? 'placed' : undefined }) : null, f ? '' : 'is-empty');
    });
    const overflow = filled.length > ps.bladder_capacity;
    const full = filled.length >= ps.bladder_capacity;
    const canWee = interactive && !handItems().length && actionsOf('go_for_a_wee').length > 0;
    return h('div.bladder', {
        cls: `${full ? 'is-full' : ''}${overflow ? ' is-over' : ''}`,
        role: 'group',
        'aria-label': `Bladder: ${ps.bladder.length} of ${ps.bladder_capacity} spaces used, ${sealed} sealed`,
    },
    h('div.zone-head', {},
        h('span.zone-name', { text: 'Bladder' }),
        h('span.zone-count', { text: `${ps.bladder.length} of ${ps.bladder_capacity}` })),
    h('div.bladder-slots', {}, slots),
    h('div.loo-reserve', { role: 'img', 'aria-label': `${plural(ps.toilet_tokens, 'toilet token')} left` },
        Array.from({ length: ps.toilet_tokens }, () => h('span.loo')),
        h('span.reserve-word', { text: ps.toilet_tokens ? 'toilet tokens left' : 'No toilet tokens left' })),
    overflow ? h('p.zone-warn', { text: 'Overflowing!' }) : null,
    canWee ? h('button.btn.go.tiny', { type: 'button', onclick: wee, text: `Go for a wee${freeNote('go_for_a_wee')}`, 'data-k': 'wee' }) : null);
}

function drunkTrack(pid) {
    const ps = gs().player_states[pid];
    const out = ps.status === 'hospitalised';
    const steps = Array.from({ length: MAX_DRUNK + 2 }, (_, lvl) => {
        const hospital = lvl === MAX_DRUNK + 1;
        const here = hospital ? out : !out && ps.drunk_level === lvl;
        return h('li.drunk-step', { cls: `lvl-${lvl}${here ? ' is-here' : ''}` },
            h('span.drunk-num', { text: hospital ? 'H' : lvl, 'aria-hidden': 'true' }),
            here ? h('span.pawn', { style: { '--seat': seatColour(pid) }, 'aria-hidden': 'true' }) : null);
    });
    return h('div.drunk', { role: 'group', 'aria-label': out ? 'Drunk track: in hospital' : `Drunk level ${ps.drunk_level} of ${MAX_DRUNK}` },
        h('div.zone-head', {},
            h('span.zone-name', { text: 'Drunk' }),
            h('span.zone-count', { text: out ? 'In hospital' : `Takes ${ps.take_count} a turn` })),
        h('ol.drunk-steps', {}, steps));
}

function specialsTray(pid, { interactive }) {
    const ps = gs().player_states[pid];
    const rolling = interactive ? handItems().filter((it) => ui.staged[it.key]?.to === 'roll') : [];
    const canReroll = interactive && !handItems().length && can('reroll_specials') && ps.special_ingredients.length > 0;
    return h('div.specials', { role: 'group', 'aria-label': 'Specials' },
        h('div.zone-head', {},
            h('span.zone-name', { text: 'Specials' }),
            canReroll ? h('span.zone-count', { text: 'Tap to pick for a re-roll' }) : null),
        h('div.specials-row', {},
            ps.special_ingredients.map((s, i) => token(s, {
                key: canReroll ? `sp-${i}` : undefined,
                onclick: canReroll ? () => toggleReroll(i) : undefined,
                selected: canReroll ? ui.reroll.has(i) : undefined,
                label: canReroll ? `${SPECIALS[s]?.label}: ${ui.reroll.has(i) ? 'picked for re-roll' : 'tap to re-roll'}` : SPECIALS[s]?.label,
            })),
            rolling.map((it) => token('SPECIAL', { state: 'placed', label: 'Special die, rolled when you finish placing' })),
            !ps.special_ingredients.length && !rolling.length ? h('span.zone-empty', { text: 'None yet' }) : null),
        canReroll && ui.reroll.size
            ? h('button.btn.go.tiny', { type: 'button', onclick: reroll, text: `Re-roll ${ui.reroll.size}${freeNote('reroll_specials')}`, 'data-k': 'reroll' })
            : null);
}

function hand() {
    const items = handItems();
    const allPlaced = items.length && items.every((it) => ui.staged[it.key]);
    return h('div.hand', { role: 'group', 'aria-label': 'In your hand' },
        h('div.zone-head', {},
            h('span.zone-name', { text: 'In your hand' }),
            h('span.zone-count', { text: `${gs().ingredients_taken_this_turn + items.length} of ${mine().take_count} taken` })),
        h('div.hand-row', {},
            items.length
                ? items.map((it) => token(it.name, {
                    key: `hand-${it.key}`,
                    state: ui.staged[it.key] ? 'ghost' : undefined,
                    selected: ui.selected === it.key,
                    onclick: ui.staged[it.key]?.to === 'roll' ? undefined : () => selectInHand(it.key),
                    label: ui.staged[it.key]
                        ? `${ING[it.name].label}, placed`
                        : `${ING[it.name].label}${it.source === 'pending' ? ' from the bag' : ''}${ui.selected === it.key ? ', holding' : ', tap to hold'}`,
                }))
                : h('span.zone-empty', { text: 'Tap tokens on the display, or draw from the bag.' })),
        items.some((it) => it.source === 'pending')
            ? h('p.hand-note', { text: 'Bag draws can’t go back. Every one goes in a glass or your mouth.' }) : null,
        items.length
            ? h('button.btn.go', { type: 'button', disabled: !allPlaced, onclick: finishPlacing, text: 'Done placing', 'data-k': 'done-placing' })
            : null);
}

function mat(pid) {
    const ps = gs().player_states[pid];
    const isMe = pid === me.id;
    const interactive = isMe && myTurn();
    const theirTurn = gs().player_turn === pid && !gs().winner && game.status === 'STARTED';
    const songs = ps.cards.filter((c) => c.card_type === 'karaoke').length;
    const status = ps.status === 'hospitalised' ? 'In hospital' : ps.status === 'wet' ? 'Wet themselves' : ps.status === 'quit' ? 'Left' : null;
    const taking = interactive && (can('take_ingredients') || handItems().length > 0);

    return h('section.mat', {
        cls: `${isMe ? 'is-mine' : 'is-theirs'}${theirTurn ? ' is-turn' : ''}${ps.status !== 'active' ? ' is-out' : ''}`,
        style: { '--seat': seatColour(pid) },
        'aria-label': isMe ? 'Your mat' : `${seatName(pid)}'s mat`,
    },
    h('header.mat-head', {},
        h('span.pawn', { 'aria-hidden': 'true' }),
        h('h2.mat-name', { text: isMe ? `${seatName(pid)} (you)` : seatName(pid) }),
        theirTurn ? h('span.mat-turn', { text: isMe ? 'Your turn' : 'Playing' }) : null,
        status ? h('span.mat-status', { text: status }) : null,
        h('span.mat-songs', { text: songs ? `${songs} of 3 songs` : '' }),
        h('span.mat-points', {}, h('strong', { text: ps.points }), ' points')),
    h('div.mat-board', {},
        taking ? hand() : null,
        h('div.bar-area', {},
            glass(pid, 0, { interactive }),
            glass(pid, 1, { interactive }),
            taking ? mouth() : null,
            interactive ? sellBoth() : null),
        h('div.body-area', {},
            bladder(pid, { interactive }),
            drunkTrack(pid),
            specialsTray(pid, { interactive }))),
    h('div.mat-cards', { role: 'group', 'aria-label': isMe ? 'Your cards' : `${seatName(pid)}'s cards` },
        ps.cards.length
            ? ps.cards.map((c, i) => cardFace(c, { owner: pid, index: i, compact: !isMe }))
            : h('span.zone-empty', { text: 'No cards claimed yet' })));
}

// ─── Menu and log ───────────────────────────────────────────────────────────

let menuNode = null;
function menu() {
    if (menuNode) return menuNode;
    const pairs = h('table.pairings', {},
        h('caption', { text: 'What mixes with what' }),
        h('thead', {}, h('tr', {}, h('th', { scope: 'col', text: '' }), SPIRITS.map((s) => h('th', { scope: 'col' }, token(s, { small: true }))))),
        h('tbody', {}, MIXERS.map((m) => h('tr', {},
            h('th', { scope: 'row' }, token(m, { small: true })),
            SPIRITS.map((s) => h('td', { 'aria-label': `${ING[s].label} with ${ING[m].label}: ${PAIRINGS[s].includes(m) ? 'yes' : 'no'}` },
                h('span', { cls: PAIRINGS[s].includes(m) ? 'yes' : 'no', text: PAIRINGS[s].includes(m) ? '✓' : '✕', 'aria-hidden': 'true' })))))));
    menuNode = h('section.menu', { 'aria-label': 'Drinks menu' },
        h('h2.menu-title', { text: 'Drinks menu' }),
        h('ul.menu-simple', {},
            h('li', {}, h('span', { text: 'One spirit and a mixer' }), h('b', { text: '1' })),
            h('li', {}, h('span', { text: 'Two of a spirit and a mixer' }), h('b', { text: '3' })),
            h('li', {}, h('span', { text: 'Tequila slammer: two tequila' }), h('b', { text: '3' })),
            h('li', {}, h('span', { text: 'Any cocktail below' }), h('b', { text: '10' })),
            h('li', {}, h('span', { text: 'Long Island Iced Tea' }), h('b', { text: '15' }))),
        pairs,
        h('p.menu-note', { text: 'One kind of mixer per drink, no more than two spirits. Cocktails must match exactly: specials come from your mat.' }),
        h('ul.cocktails', {}, COCKTAILS.map((c) => h('li.cocktail', {},
            h('span.cocktail-name', { text: c.name }),
            h('span.cocktail-recipe', {}, c.cup.map((i) => token(i, { small: true })), c.specials.map((s) => token(s, { small: true }))),
            h('b.cocktail-points', { text: c.points })))));
    return menuNode;
}

function chalkboard() {
    const recent = moves.slice(-14).reverse();
    return h('section.chalk', { 'aria-label': 'What happened' },
        h('h2.chalk-title', { text: 'What happened' }),
        recent.length
            ? h('ol.chalk-list', {}, recent.map((m) => h('li', { text: describeMove(m, nameOf) })))
            : h('p.chalk-empty', { text: 'Nothing yet. First round’s on the house.' }));
}

function housekeeping() {
    const bits = [];
    const state = gs();
    if (game.status === 'STARTED' && !state.winner && isMember()) {
        const ps = mine();
        const undoOpen = game.pending_undo && game.pending_undo.status === 'pending';
        if (moves.length && !undoOpen && ps?.status === 'active') {
            bits.push(h('button.btn.tiny', { type: 'button', onclick: proposeUndo, text: 'Ask to take back the last turn', 'data-k': 'undo' }));
        }
        if (game.host === me.id || ps?.status === 'active') {
            bits.push(h('button.btn.tiny.quiet', { type: 'button', onclick: confirmLeave, text: game.host === me.id ? 'Call off the game' : 'Leave the game', 'data-k': 'leave' }));
        }
    }
    bits.push(h('a.btn.tiny.quiet', { href: `/play?id=${encodeURIComponent(gameId)}`, onclick: () => setView('table'), text: 'Switch to table view' }));
    bits.push(h('a.btn.tiny.quiet', { href: `/game?id=${encodeURIComponent(gameId)}`, onclick: () => setView('classic'), text: 'Switch to classic view' }));
    return h('nav.housekeeping', { 'aria-label': 'Game options' }, bits);
}

function setView(view) {
    try {
        localStorage.setItem('bocUi', view);
        localStorage.setItem('bocTableView', view === 'table' ? '1' : '0');
    } catch { /* storage blocked: the link still works */ }
}

// ─── Game over ──────────────────────────────────────────────────────────────

function ending() {
    const box = $('ending');
    const state = gs();
    const over = game.status === 'ENDED' || !!state?.winner;
    if (!over) {
        box.hidden = true;
        return;
    }
    if (endingShown) return;
    endingShown = true;
    const standings = seatOrder().map((pid) => ({ pid, ps: state.player_states[pid] }))
        .sort((a, b) => (b.pid === state.winner) - (a.pid === state.winner) || b.ps.points - a.ps.points);
    box.replaceChildren(h('div.ending-card', { role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'endingTitle' },
        h('h2', { id: 'endingTitle', text: state.winner ? (state.winner === me.id ? 'You won!' : `${seatName(state.winner)} won`) : 'Game called off' }),
        h('ol.standings', {}, standings.map(({ pid, ps }) => h('li', { style: { '--seat': seatColour(pid) } },
            h('span.pawn', { 'aria-hidden': 'true' }),
            h('span', { text: pid === me.id ? `${seatName(pid)} (you)` : seatName(pid) }),
            h('b', { text: plural(ps.points, 'point') })))),
        h('div.ending-buttons', {},
            h('a.btn.go', { href: '/', text: 'Back to the games' }),
            h('button.btn', { type: 'button', onclick: () => { box.hidden = true; }, text: 'Look at the table' }))));
    box.hidden = false;
    box.querySelector('.btn.go')?.focus();
}

// ─── Lobby ──────────────────────────────────────────────────────────────────

let lobbyExtras = null;

async function renderLobby() {
    const host = game.host === me.id;
    if (host && !lobbyExtras) {
        try {
            const [s, m] = await Promise.all([api.botStrategies(), api.gameModes()]);
            lobbyExtras = { strategies: s.strategies ?? [], modes: m.modes ?? [] };
        } catch {
            lobbyExtras = { strategies: [], modes: [] };
        }
    }
    const seats = Array.from({ length: 4 }, (_, i) => {
        const pid = game.players[i];
        return h('li.seat', { cls: pid ? 'is-taken' : 'is-open', style: { '--seat': SEAT_COLOURS[i] } },
            h('span.pawn', { 'aria-hidden': 'true' }),
            h('span.seat-name', { text: pid ? `${seatName(pid)}${pid === me.id ? ' (you)' : ''}${pid === game.host ? ', host' : ''}` : 'Empty stool' }),
            host && pid && pid !== me.id
                ? h('button.btn.tiny.quiet', {
                    type: 'button', 'aria-label': `Remove ${seatName(pid)}`, text: 'Remove',
                    onclick: () => act(async () => { await api.removePlayer(gameId, pid); await refresh(); return null; }),
                }) : null);
    });

    const parts = [
        h('h2.lobby-title', { text: `${seatName(game.host)}'s table` }),
        h('p.lobby-sub', { text: `${plural(game.players.length, 'bartender')} of 4 seated. Two or more can play.` }),
        h('ol.seats', {}, seats),
    ];
    if (!isMember()) {
        parts.push(h('button.btn.go', {
            type: 'button', text: 'Take a seat',
            onclick: () => act(async () => { await api.join(gameId); await refresh(); return null; }),
        }));
    }
    if (host) {
        const select = h('select', { 'aria-label': 'Bot style', id: 'botStyle' },
            lobbyExtras.strategies.map((s) => h('option', { value: s, text: s })));
        if (game.players.length < 4 && lobbyExtras.strategies.length) {
            parts.push(h('div.lobby-bot', {},
                h('label', { for: 'botStyle', text: 'Seat a bot' }),
                select,
                h('button.btn', {
                    type: 'button', text: 'Add bot',
                    onclick: () => act(async () => { await api.addBot(gameId, select.value); await refresh(); return null; }),
                })));
        }
        const on = new Set(gs()?.game_modes ?? []);
        if (lobbyExtras.modes.length) {
            parts.push(h('fieldset.house-rules', {},
                h('legend', { text: 'House rules' }),
                lobbyExtras.modes.map((mode) => {
                    const input = h('input', { type: 'checkbox', id: `mode-${mode}` });
                    input.checked = on.has(mode);
                    input.addEventListener('change', () => {
                        const next = lobbyExtras.modes.filter((m) => (m === mode ? input.checked : on.has(m)));
                        act(async () => { await api.setModes(gameId, next); await refresh(); return null; });
                    });
                    return h('label.rule', { for: `mode-${mode}` }, input,
                        h('span', {}, h('strong', { text: MODES[mode]?.label ?? mode }), ' ', MODES[mode]?.desc ?? ''));
                })));
        }
        parts.push(h('button.btn.go.big', {
            type: 'button', disabled: game.players.length < 2,
            text: game.players.length < 2 ? 'Needs a second player' : 'Open the bar',
            onclick: () => act(async () => { await api.start(gameId); await refresh(); return null; }),
        }));
    } else if (isMember()) {
        parts.push(h('p.lobby-sub', { text: `Waiting for ${seatName(game.host)} to open the bar.` }));
    }
    $('table').replaceChildren(h('section.lobby', { id: 'lobby', 'aria-label': 'Waiting to start' }, parts));
}

// ─── Putting it all on the table ────────────────────────────────────────────

function render({ force = false } = {}) {
    if (!game) return;
    const signature = JSON.stringify([game.status, game.game_state, game.pending_undo, valid, moves.length,
        ui.picks, ui.staged, ui.selected, [...ui.reroll], !!ui.prompt]);
    if (!force && signature === lastSignature) return;
    lastSignature = signature;
    const focusKey = document.activeElement?.getAttribute?.('data-k');

    if (game.status === 'NEW') {
        turnbar();
        renderLobby().then(() => restoreFocus(focusKey));
        return;
    }
    reconcile();
    turnbar();
    document.body.classList.toggle('is-my-turn', myTurn());

    const seats = seatOrder();
    const start = Math.max(0, seats.indexOf(me.id));
    const around = [...seats.slice(start + 1), ...seats.slice(0, start)].filter((pid) => pid !== me.id);

    $('table').replaceChildren(
        around.length ? h('div.across', { 'aria-label': 'Other players' }, around.map(mat)) : null,
        h('div.middle', {}, renderMarket(), h('div.middle-side', {}, renderSupply(), renderScoreTrack())),
        isMember() && gs().player_states[me.id] ? mat(me.id) : null,
        h('div.extras', {}, menu(), chalkboard()),
        housekeeping(),
    );
    ending();
    restoreFocus(focusKey);
}

function restoreFocus(key) {
    if (!key) return;
    const target = document.querySelector(`[data-k="${CSS.escape(key)}"]`);
    if (target && document.activeElement !== target) target.focus({ preventScroll: true });
}

boot();
