// Bar Top view — the game laid out as the physical box on a table. Every
// piece is on show; you act by touching the piece itself (a token, the bag,
// a glass, your bladder, a card). Legality comes from /valid-actions, so this
// file only decides how things look and which request a touch sends.

import { api } from './api.js';
import {
    BOOZY, CARD_KINDS, COCKTAILS, DRUNK_LABELS, FREE_ACTIONS, GLASS_SPECIALS, ING, MIXERS, MODES, PAIRINGS,
    RULES, RULES_INTRO, SEAT_COLOURS, SPECIALS, SPIRITS, cardCost, cardText, describeMove, drinkName, isSpecial,
    orderRecipe, servesOrder, SPECIALIST_SPECIAL, splitGlass,
} from './data.js';
import { inviteBox } from '/static/invite.js';

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
// in your hand is going, and the question currently asked in the turn bar.
const ui = {
    picks: [], // open-display slot indexes, in the order picked up
    pickedFrom: '', // the display the picks refer to
    specialPicks: [], // specials-tray indexes, in the order picked up
    specialsFrom: '', // the specials tray the picks refer to
    // hand key -> { to: 'cup', cup } | { to: 'mouth' } |
    //             { to: 'mat', choice?, swap?, leave? } for a special token
    staged: {},
    specialDraft: {}, // hand key -> { choice } while a "choose any" is half made
    selected: null, // hand key being placed
    prompt: null, // { text, choices: [{ label, onclick, kind }] }
    historyOpen: false, // show every move, not just the latest
    sheet: null, // 'menu' | 'rules': the panel opened from the turn bar
    leaving: null, // 'cancel' | 'quit': asking to call the game off or leave it
};

const SPECIAL_TYPES = ['bitters', 'cointreau', 'lemon', 'sugar', 'vermouth'];
const MAX_SPECIALS = 2;

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
    order: '<svg viewBox="0 0 24 24"><path d="M5 2h14v19l-2.3-1.6L14.3 21 12 19.4 9.7 21l-2.4-1.6L5 21z" fill="currentColor"/><path d="M8 7h8M8 10.5h8M8 14h5" style="stroke:var(--scene-bottom)" stroke-width="1.5"/></svg>',
};

const AMBULANCE = '<svg viewBox="0 0 32 20" aria-hidden="true"><path d="M2 4h17v12H2z" fill="#fff" stroke="#7d1f15" stroke-width="1.2"/><path d="M19 7h6l4 5v4H19z" fill="#fff" stroke="#7d1f15" stroke-width="1.2"/><path d="M21 8.5h3.4l2.6 3.3H21z" fill="#bfe3f5"/><path d="M8.5 6.5h2v3h3v2h-3v3h-2v-3h-3v-2h3z" fill="#e0452b"/><path d="M2 13h27" stroke="#e0452b" stroke-width="1.2"/><circle cx="7" cy="16.5" r="2.3" fill="#2b2b2b"/><circle cx="24" cy="16.5" r="2.3" fill="#2b2b2b"/><rect x="11" y="2" width="3" height="2" fill="#2f8fdb"/></svg>';

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
// ring, a picture and its name. Tokens are one size wherever they sit;
// `print` is only for the small pictures printed on a card.
// `name` is an ingredient key, 'ANY_SPIRIT', or a rolled special ('lemon'…).
function token(name, { onclick, label, state, selected, key, print, printed: printedName } = {}) {
    const meta = ING[name];
    const special = SPECIALS[name] ?? SPECIALS[meta?.special];
    const kind = special ? 'rolled' : meta?.kind ?? 'spirit';
    const text = special?.label ?? meta?.label ?? 'Any one spirit';
    const printed = printedName ?? special?.label ?? TOKEN_NAMES[name] ?? meta?.label ?? '';
    const node = h(onclick ? 'button.tok' : 'span.tok', {
        cls: `tok-${kind} ing-${name.toLowerCase()}${state ? ` is-${state}` : ''}${selected ? ' is-selected' : ''}${print ? ' tok-print' : ''}`,
        style: { '--len': String(Math.max(printed.length, 4)) },
        type: onclick ? 'button' : undefined,
        onclick,
        'aria-label': label ?? text,
        'aria-pressed': onclick && selected !== undefined ? String(!!selected) : undefined,
        title: label ?? text,
        'data-k': key,
        role: onclick ? undefined : 'img',
    });
    node.append(h('span.tok-icon', { svg: special ? SPECIAL_ICONS[meta?.special ?? name] : ING_ICONS[name] ?? '', 'aria-hidden': 'true' }));
    if (!print) node.append(h('span.tok-name', { text: printed, 'aria-hidden': 'true' }));
    return node;
}

// A token as it sits on the table: a special token shows its rolled face.
function tableToken(name, face, opts = {}) {
    if (name !== 'SPECIAL') return token(name, opts);
    if (face && face !== 'any') return token(face, { ...opts, label: opts.label ?? `${SPECIALS[face].label} special` });
    return token('SPECIAL', { ...opts, printed: 'Any', label: opts.label ?? 'Special: choose any' });
}

const tokenLabel = (name, face) => (name !== 'SPECIAL' ? ING[name].label
    : face && face !== 'any' ? `${SPECIALS[face].label} special` : 'choose-any special');

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
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && ui.sheet) closeSheet();
    });
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
    const faces = gs().bag_draw_pending_specials ?? [];
    const pending = gs().bag_draw_pending.map((name, i) => ({
        key: `p${i}`, name, source: 'pending', face: faces[i] ?? (name === 'SPECIAL' ? 'any' : null),
    }));
    const picks = ui.picks.map((slotIndex) => ({
        key: `d${slotIndex}`,
        name: gs().open_display[slotIndex],
        source: 'display',
        slotIndex,
        face: displayFace(slotIndex),
    }));
    const specials = ui.specialPicks.map((i) => ({
        key: `s${i}`, name: specialsTray()[i], source: 'specials', face: null,
    }));
    return [...pending, ...picks, ...specials];
}

// ─── Specials ───────────────────────────────────────────────────────────────

// Specials drawn from the bag, waiting for anyone to take them.
const specialsTray = () => gs().specials_display ?? [];

// Games started before specials were ingredients use special dice tokens
// and put specials on the mat; show that part of the mat only for them.
const oldSpecials = () => Object.values(gs().player_states).some((ps) => ps.special_ingredients.length)
    || gs().open_display.includes('SPECIAL') || gs().bag_draw_pending.includes('SPECIAL');

// What a special token on the display shows: a special, or 'any'.
function displayFace(slotIndex) {
    if (gs().open_display[slotIndex] !== 'SPECIAL') return null;
    return (gs().display_specials ?? [])[slotIndex] ?? 'any';
}

const isSpecialToken = (it) => it.name === 'SPECIAL';

// Specials nobody holds and no token is showing, less those already chosen in
// your hand: what a "choose any" can become.
function freeSpecialTypes(exceptKey) {
    const taken = new Set();
    for (const ps of Object.values(gs().player_states)) for (const s of ps.special_ingredients) taken.add(s);
    for (const f of [...(gs().display_specials ?? []), ...(gs().bag_draw_pending_specials ?? [])]) {
        if (f && f !== 'any') taken.add(f);
    }
    for (const [key, st] of Object.entries(ui.staged)) {
        if (key !== exceptKey && st.to === 'mat' && st.choice) taken.add(st.choice);
    }
    return SPECIAL_TYPES.filter((t) => !taken.has(t));
}

// How many specials you'd hold once the specials already placed from your
// hand (other than `exceptKey`) land on your mat.
function specialsAfterHand(exceptKey) {
    let count = mine().special_ingredients.length;
    for (const it of handItems()) {
        const st = ui.staged[it.key];
        if (it.key === exceptKey || !st || st.to !== 'mat' || st.leave || st.swap) continue;
        count += 1;
    }
    return count;
}

// The special a staged special token will become (null if left).
function specialOf(it) {
    const st = ui.staged[it.key];
    if (!st || st.leave) return null;
    return it.face === 'any' ? st.choice : it.face;
}

// The hand item being held, if it's a spirit or mixer (specials go to the mat).
function heldIngredient() {
    const it = handItems().find((x) => x.key === ui.selected);
    return it && !isSpecialToken(it) ? it : null;
}

const takeLeft = () => (mine() ? mine().take_count - gs().ingredients_taken_this_turn - handItems().length : 0);
const stagedTo = (to, cup) => handItems().filter((it) => ui.staged[it.key]?.to === to
    && (cup === undefined || ui.staged[it.key].cup === cup));

// Keep local state honest when the table changes underneath it.
function reconcile() {
    if (!myTurn() || ui.pickedFrom !== gs().open_display.join()) {
        ui.picks = [];
    }
    if (!myTurn() || ui.specialsFrom !== specialsTray().join()) {
        ui.specialPicks = [];
    }
    const keys = new Set(handItems().map((it) => it.key));
    for (const key of Object.keys(ui.staged)) if (!keys.has(key)) delete ui.staged[key];
    for (const key of Object.keys(ui.specialDraft)) if (!keys.has(key)) delete ui.specialDraft[key];
    // A special showing a face goes straight to your mat when there's room;
    // "choose any" and a third special wait for you to decide.
    for (const it of handItems()) {
        if (!isSpecialToken(it) || ui.staged[it.key]) continue;
        if (it.face !== 'any' && specialsAfterHand(it.key) < MAX_SPECIALS) ui.staged[it.key] = { to: 'mat' };
    }
    if (ui.selected && (!keys.has(ui.selected) || ui.staged[ui.selected])) ui.selected = null;
    if (!ui.selected) ui.selected = handItems().find((it) => !ui.staged[it.key])?.key ?? null;
    if (!myTurn()) ui.prompt = null;
}

// How drunk you'd be after drinking `extra` on top of what this turn has
// already drunk (the drunk track only moves once the whole take is done).
function drunkAfter(extra) {
    const ps = mine();
    const refreshers = new Set(ps.cards.filter((c) => c.card_type === 'refresher').map((c) => c.mixer_type));
    const drunk = [...gs().drunk_ingredients_this_turn, ...extra];
    const spirits = drunk.filter((i) => ING[i]?.kind === 'spirit' || BOOZY.includes(i)).length;
    const hot = drunk.filter((i) => ING[i]?.kind === 'mixer' && refreshers.has(i)).length;
    // Lemon and sugar sober you like a plain mixer; the boozy specials don't
    const plain = drunk.filter((i) => (ING[i]?.kind === 'mixer' && !refreshers.has(i)) || (isSpecial(i) && !BOOZY.includes(i))).length;
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

function pickFromSpecials(index) {
    if (ui.specialPicks.includes(index)) {
        ui.specialPicks = ui.specialPicks.filter((s) => s !== index);
        delete ui.staged[`s${index}`];
        render({ force: true });
        return;
    }
    if (takeLeft() < 1) {
        toast(`Your hand is full: you take ${mine().take_count} this turn. Place what you're holding first.`, 'error');
        return;
    }
    ui.specialsFrom = specialsTray().join();
    ui.specialPicks.push(index);
    ui.selected = `s${index}`;
    render({ force: true });
}

function drawFromBag(count) {
    act(() => api.drawFromBag(gameId, count), {
        after: () => { ui.selected = null; },
    });
}

function selectInHand(key) {
    delete ui.staged[key];
    delete ui.specialDraft[key];
    ui.selected = ui.selected === key ? null : key;
    render({ force: true });
}

// Settle a special token in your hand: which special ("choose any"), and
// what to do when you'd hold more than two.
function settleSpecial(key, decision) {
    const it = handItems().find((x) => x.key === key);
    if (!it) return;
    const draft = { ...(ui.specialDraft[key] ?? {}), ...decision };
    const atLimit = specialsAfterHand(key) >= MAX_SPECIALS;
    if (it.face === 'any' && !draft.choice && !draft.leave) {
        ui.specialDraft[key] = draft;
    } else if (atLimit && !draft.swap && !draft.leave) {
        ui.specialDraft[key] = draft;
    } else {
        ui.staged[key] = { to: 'mat', ...draft };
        delete ui.specialDraft[key];
        ui.selected = handItems().find((x) => !ui.staged[x.key])?.key ?? null;
    }
    render({ force: true });
}

function placeSelected(to, cup) {
    const item = heldIngredient();
    if (!item) return;
    if (to === 'cup') {
        const room = glassRoom(cup);
        if (isSpecial(item.name) && room.specials < 1) {
            toast(`Glass ${cup + 1} has two specials already: that's the limit.`, 'error');
            return;
        }
        if (!isSpecial(item.name) && room.base < 1) {
            toast(`Glass ${cup + 1} is full: five spirits and mixers is the limit.`, 'error');
            return;
        }
    }
    ui.staged[item.key] = { to, cup };
    ui.selected = handItems().find((it) => !ui.staged[it.key])?.key ?? null;
    render({ force: true });
}

// Room left in one of your glasses, counting what you've placed but not sent.
function glassRoom(cup) {
    const all = [...mine().cups[cup].ingredients, ...stagedTo('cup', cup).map((it) => it.name)];
    const specials = all.filter(isSpecial).length;
    return { base: CUP_SIZE - (all.length - specials), specials: GLASS_SPECIALS - specials };
}

function finishPlacing() {
    const items = handItems();
    if (items.some((it) => !ui.staged[it.key])) {
        toast('Put everything in your hand into a glass or your mouth first.', 'error');
        return;
    }
    const assignments = items.map((it) => {
        const where = ui.staged[it.key];
        const a = {
            ingredient: it.name,
            source: it.source,
            disposition: where.to === 'cup' ? 'cup' : 'drink',
            cup_index: where.to === 'cup' ? where.cup : 0,
        };
        if (it.source === 'display') a.display_index = displayIndexAtSend(it, items);
        if (where.to === 'mat') {
            if (where.choice) a.special_type = where.choice;
            if (where.swap) a.swap_special = where.swap;
        }
        return a;
    });
    const drinks = items.filter((it) => ui.staged[it.key].to === 'mouth').map((it) => it.name);
    const finishing = mine().take_count - gs().ingredients_taken_this_turn - items.length === 0;
    const run = () => act(() => api.takeIngredients(gameId, assignments), {
        after: (result) => {
            ui.picks = [];
            ui.specialPicks = [];
            ui.staged = {};
            ui.selected = null;
            for (const record of result?.move?.taken ?? []) {
                if (record.disposition !== 'special') continue;
                const got = SPECIALS[record.special_type]?.label;
                if (!got) toast('You left the special. Its token goes back in the bag.');
                else if (record.swapped) toast(`${got} is on your mat; ${SPECIALS[record.swapped]?.label} went back.`);
                else toast(`${got} is on your mat.`);
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

// The server takes display tokens one at a time, so a slot further along the
// display moves down by one for each earlier slot taken before it.
function displayIndexAtSend(item, items) {
    const earlier = items.filter((x) => x.source === 'display' && items.indexOf(x) < items.indexOf(item));
    return item.slotIndex - earlier.filter((x) => x.slotIndex < item.slotIndex).length;
}

function sell(params) {
    const body = { cup_index: params.cup_index, declared_specials: params.declared_specials ?? [] };
    if (params.additional_cups) body.additional_cups = params.additional_cups;
    act(() => api.sellCup(gameId, body), {
        after: (result) => {
            const earned = result?.move?.points_earned;
            const served = (result?.move?.orders ?? []).map((o) => `${o.name} (+${o.bonus})`);
            if (earned !== undefined) {
                toast(`Sold for ${plural(earned, 'point')}.${served.length ? ` Order served: ${served.join(', ')}.` : ''}`);
            }
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
        ask(`${card.name}: which glass does it go on, and which three spirits pay for it? They go from your bladder into the bag.`, [
            ...options.map((a) => ({
                label: `Glass ${a.params.cup_index + 1}, paid with ${ING[a.params.spirit_type]?.label ?? a.params.spirit_type}`,
                onclick: () => send(a.params),
                kind: 'go',
            })),
            back,
        ]);
        return;
    }
    const free = isFree('claim_card') ? ' It doesn’t use your action.' : '';
    if (card.card_type === 'specialist') {
        ask(`Claim ${card.name} for ${plural(points, 'point')}? What you pay with goes from your bladder into the bag.${free}`, [
            ...options.map((a) => {
                const pay = a.params.spirit_type;
                const what = pay === card.spirit_type ? `2 ${ING[pay].label}` : `1 ${ING[pay]?.label ?? pay}`;
                return { label: `Pay ${what}`, onclick: () => send(a.params), kind: 'go' };
            }),
            back,
        ]);
        return;
    }
    const cost = cardCost(card);
    const paying = `${cost.length} ${ING[cost[0]]?.label ?? ''}`.trim();
    const extra = card.card_type === 'store'
        ? ` One ${ING[card.spirit_type].label} goes into the bag and the rest in your bladder moves onto the card.`
        : ` ${paying} goes from your bladder into the bag.`;
    ask(`Claim ${card.name} for ${plural(points, 'point')}?${extra}${free}`, [
        { label: 'Claim it', onclick: () => send(options[0].params), kind: 'go' },
        back,
    ]);
}

function clearRow(position) {
    const orders = position === 2;
    ask(orders
        ? 'Clear the orders? All three go to the bottom of the order deck and three new ones are dealt. This is free, once a turn.'
        : 'Swipe the ability cards? All three go to the bottom of the deck and three new ones are dealt. This is free, once a turn.', [
        { label: orders ? 'Clear the orders' : 'Swipe them', onclick: () => act(() => api.refreshCardRow(gameId, position)), kind: 'go' },
        { label: 'Leave them', onclick: () => { ui.prompt = null; render({ force: true }); } },
    ]);
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

// Calling the game off (host) or leaving it asks first, right by the
// button: it can happen on anyone's turn.
function askLeave(kind) {
    ui.leaving = kind;
    render({ force: true });
    document.querySelector('[data-k="leave-yes"]')?.focus();
}

function leave() {
    const kind = ui.leaving;
    ui.leaving = null;
    act(() => (kind === 'cancel' ? api.cancel(gameId) : api.quit(gameId)), {
        after: () => refresh().catch(() => {}),
    });
}

function leaveConfirm() {
    if (!ui.leaving) return null;
    const cancel = ui.leaving === 'cancel';
    const inLobby = game.status === 'NEW';
    return h('div.leave-confirm', { role: 'group', 'aria-label': cancel ? 'Call off the game' : 'Leave the game' },
        h('p', {
            text: cancel
                ? (inLobby ? 'Call off this game? Everyone seated goes back to the games list.' : 'Call off the game for everyone? No one wins.')
                : 'Leave the game? You can’t come back to it; the others play on.',
        }),
        h('div.prompt-choices', {},
            h('button.btn.danger', { type: 'button', onclick: leave, text: cancel ? 'Call it off' : 'Leave the game', 'data-k': 'leave-yes' }),
            h('button.btn', { type: 'button', onclick: () => { ui.leaving = null; render({ force: true }); }, text: 'Stay', 'data-k': 'leave-no' })));
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
            const held = hand.find((it) => it.key === ui.selected);
            detail = !unplaced ? 'Everything is placed. Press "Done placing" on your mat.'
                : held && isSpecialToken(held) ? 'Decide what to do with the special in your hand.'
                    : `Tap a glass or your mouth to put down the ${held ? ING[held.name].label : 'token'} you're holding.`;
        } else if (takeUnderway()) {
            detail = `Take ${plural(left, 'more ingredient')}: tap tokens on the display or the specials tray, or draw from the bag.`;
        } else if (state.main_action_taken_this_turn) {
            detail = 'Main action done. Use a free action or end your turn.';
        } else if (valid.can_end_turn) {
            // A free-action card's action stood in for the main action
            const used = state.free_actions_used_this_turn ?? [];
            const left = [
                used.includes('take_ingredients') ? null : `take ${plural(mine().take_count, 'ingredient')}`,
                used.includes('sell_cup') ? null : 'sell',
                'drink a glass',
                used.includes('go_for_a_wee') ? null : 'wee',
            ].filter(Boolean);
            const last = left.pop();
            const list = left.length ? `${left.join(', ')} or ${last}` : last;
            detail = `Free action done. ${list[0].toUpperCase()}${list.slice(1)}, or end your turn.`;
        } else {
            detail = `Take ${plural(mine().take_count, 'ingredient')}, sell, drink a glass or wee.`;
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
    const strip = myTurn() ? actionStrip() : null;

    const buttons = [];
    if (myTurn() && valid.can_end_turn && !handItems().length) {
        buttons.push(h('button.btn.go', { type: 'button', onclick: endTurn, text: 'End turn', 'data-k': 'end-turn' }));
    }
    if (game.status !== 'NEW') {
        for (const [sheet, label] of [['menu', 'Drinks menu'], ['rules', 'Rules']]) {
            buttons.push(h('button.btn.tiny.sheet-btn', {
                type: 'button', text: label, 'data-k': `open-${sheet}`,
                cls: ui.sheet === sheet ? 'is-open' : '',
                'aria-expanded': String(ui.sheet === sheet), 'aria-controls': 'sheet',
                onclick: () => toggleSheet(sheet),
            }));
        }
    }
    if (buttons.length) kids.push(h('div.turn-buttons', {}, buttons));
    if (strip) kids.push(strip);

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

// The free actions you could use right now; nothing else (the line above
// already says whether your main action is still to do).
function actionStrip() {
    const state = gs();
    const ps = mine();
    const used = new Set(state.free_actions_used_this_turn ?? []);
    const open = new Set(valid.free_actions_left ?? []);
    const mainDone = state.main_action_taken_this_turn;
    const cardFree = new Set(ps.cards.filter((c) => c.card_type === 'free_action').map((c) => c.free_action_type));
    const clearRowOf = { refresh_orders_row: 2, refresh_ability_row: 3 };
    const tiles = [];
    for (const [type, label] of Object.entries(FREE_ACTIONS)) {
        const always = type === 'claim_card' || type in clearRowOf;
        if ((!always && !cardFree.has(type)) || used.has(type)) continue;
        const row = clearRowOf[type];
        const usable = row
            ? actionsOf('refresh_card_row').some((a) => a.params.row_position === row)
            : open.has(type) || (!mainDone && can(type));
        if (usable) tiles.push(h('li.act', { text: label }));
    }
    if (!tiles.length) return null;
    return h('ul.action-strip', { 'aria-label': 'Free actions you can use now' },
        h('li.act-lead', { text: 'Free now:' }), tiles);
}

// ─── Cards ──────────────────────────────────────────────────────────────────

function bladderCounts(ps) {
    const counts = {};
    for (const i of ps?.bladder ?? []) counts[i] = (counts[i] ?? 0) + 1;
    return counts;
}

// How many of your cost tokens you already have, for hollowing out the rest.
function costHave(card, ps) {
    if (!ps) return Infinity;
    const have = bladderCounts(ps);
    if (card.card_type === 'cup_doubler') return Math.max(0, ...SPIRITS.map((s) => have[s] ?? 0));
    // One of its special pays for a specialist in full
    if (card.card_type === 'specialist' && have[SPECIALIST_SPECIAL[card.spirit_type]]) return cardCost(card).length;
    return have[cardCost(card)[0]] ?? 0;
}

function costCaption(card) {
    const cost = cardCost(card);
    if (card.card_type === 'order') return 'Wanted';
    if (card.card_type === 'cup_doubler') return '3 of one spirit';
    return `${cost.length} ${ING[cost[0]]?.label.replace(' water', '') ?? ''}`;
}

const STAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1.6l3 6.6 7.2.8-5.4 4.9 1.5 7.1L12 17.4 5.7 21l1.5-7.1L1.8 9l7.2-.8z" fill="#f4c537" stroke="#6b4a0c" stroke-width="1.1" stroke-linejoin="round"/><path d="M12 4.4l2.2 4.8 5.2.6" fill="none" stroke="#fff3c2" stroke-width=".9" stroke-linecap="round"/></svg>';

// The token a card is about, drawn big in its art: the spirit or mixer.
const cardSubject = (card) => card.spirit_type ?? card.mixer_type ?? null;

// A card laid out like the printed ones: Greek-key border, art panel with the
// cost badge and points star, name ribbon, kind, and the rule in a frame.
function cardFace(card, { claimable, owner, index, compact } = {}) {
    const kind = CARD_KINDS[card.card_type] ?? { label: 'Card', points: 0 };
    const isOrder = card.card_type === 'order';
    const ps = owner || isOrder ? null : (game.status === 'STARTED' && mine()?.status === 'active' ? mine() : null);
    const cost = cardCost(card);
    const have = costHave(card, ps);
    const short = Math.max(0, cost.length - have);
    const label = isOrder
        ? `Order: ${card.name}. ${cardText(card)}`
        : `${card.name}, ${kind.label} card, ${plural(kind.points, 'point')}. ${cardText(card)} Costs ${costCaption(card)} in your bladder${card.card_type === 'karaoke' ? ', and drunk 3 or more' : ''}.${ps && short ? ` You need ${short} more.` : ''}${claimable ? ' You can claim it.' : ''}`;
    const subject = isOrder ? null : cardSubject(card);
    const specials = isOrder ? orderRecipe(card).specials : [];

    const face = h(claimable ? 'button.card' : 'div.card', {
        cls: `kind-${card.card_type}${claimable ? ' is-claimable' : ''}${compact ? ' is-compact' : ''}`,
        type: claimable ? 'button' : undefined,
        onclick: claimable ? () => claim(card) : undefined,
        'aria-label': label,
        role: claimable ? undefined : 'group',
        'data-k': claimable ? `card-${card.id}` : undefined,
    },
    h('span.card-art', { 'aria-hidden': 'true' },
        h('span.card-lights'),
        h('span.card-emblem', { svg: KIND_ICONS[card.card_type] ?? '' }),
        subject ? h('span.card-subject', {}, token(subject, { print: true })) : null,
        h('span.card-costbadge', { cls: `${ps && short ? 'is-short' : ''}${isOrder ? ' is-order' : ''}` },
            h('span.card-costtoks', {},
                cost.map((name, i) => token(name, { print: true, state: i >= have ? 'missing' : undefined })),
                specials.map((sp) => token(sp, { print: true }))),
            h('span.card-costcap', { text: costCaption(card) })),
        h('span.card-star', {},
            h('span.card-star-shape', { svg: STAR }),
            h('span.card-star-num', { text: isOrder ? `+${card.bonus}` : kind.points }),
            h('span.card-star-cap', { text: isOrder ? 'Bonus' : 'Points' }))),
    h('span.card-ribbon', {}, h('span.card-name', { text: card.name })),
    h('span.card-kind', { text: kind.label }),
    compact ? null : h('span.card-rule', {}, h('span', { text: cardText(card) })));

    if (card.card_type === 'store' && owner) {
        face.append(h('span.card-store', { 'aria-label': `${plural(card.stored_spirits.length, 'spirit')} stored` },
            card.stored_spirits.length
                ? card.stored_spirits.map((s) => token(s))
                : h('span.card-store-empty', { text: 'Nothing stored' })));
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

function cardBack(count, label, word = 'Bartenders of Corfu') {
    return h('div.pile', { role: 'img', 'aria-label': label },
        count ? h('div.card.card-back', {}, h('span.back-mark', { text: word })) : h('div.card-space'),
        h('span.pile-count', { text: count ? plural(count, 'card') : 'Empty' }));
}

function renderMarket() {
    const state = gs();
    const claimable = new Set(actionsOf('claim_card').map((a) => a.params.card_id));
    const clearable = new Set(actionsOf('refresh_card_row').map((a) => a.params.row_position));
    const rowOf = (position) => state.card_rows.find((r) => r.position === position) ?? { cards: [] };
    const cells = (position, size) => {
        const row = rowOf(position);
        return Array.from({ length: Math.max(size, row.cards.length) }, (_, i) => (row.cards[i]
            ? cardFace(row.cards[i], { claimable: claimable.has(row.cards[i].id) })
            : h('div.card-space', { role: 'img', 'aria-label': 'Empty slot' })));
    };
    const tag = (title, note, position, buttonText) => h('div.row-tag', {},
        h('span', { text: title }),
        position && clearable.has(position)
            ? h('button.btn.tiny', { type: 'button', onclick: () => clearRow(position), text: buttonText, 'data-k': `clear-${position}` })
            : h('span.row-note', { text: note }));

    return h('section.market', { 'aria-label': 'Cards' },
        h('div.card-row.is-karaoke', { 'aria-label': 'Karaoke stage', role: 'group' },
            tag('Karaoke stage', 'Sing at drunk 3+ with 2 of the song’s spirit. Three songs wins.'),
            h('div.row-cards', {}, cells(1, 5))),
        h('div.card-row', { 'aria-label': 'Orders', role: 'group' },
            tag('Orders', 'Sell what they want for the bonus. Clear at drunk 3+ (free).', 2, 'Clear (free)'),
            h('div.row-cards', {}, cells(2, 3)),
            cardBack(state.order_deck_size ?? 0, `Order deck, ${plural(state.order_deck_size ?? 0, 'order')}`, 'Orders')),
        h('div.card-row', { 'aria-label': 'Ability cards', role: 'group' },
            tag('Ability cards', 'Swipe at drunk 2+ (free).', 3, 'Swipe (free)'),
            h('div.row-cards', {}, cells(3, 3)),
            cardBack(state.deck_size, `Ability deck, ${plural(state.deck_size, 'card')}`, 'Abilities')));
}

// ─── Bag and open display ───────────────────────────────────────────────────

function renderSupply() {
    const state = gs();
    const taking = can('take_ingredients');
    const pendingDraw = state.bag_draw_pending.length > 0;
    const left = taking ? takeLeft() : 0;
    // Specials that come out of the bag go to the tray, so only spirits and
    // mixers can be drawn.
    const drawable = state.bag_contents.filter((n) => !isSpecial(n)).length;
    const maxDraw = taking && !pendingDraw ? Math.min(left, drawable) : 0;

    const display = h('div.display', { role: 'group', 'aria-label': 'Open display' },
        Array.from({ length: 5 }, (_, i) => {
            const name = state.open_display[i];
            if (!name) return slot(null, 'is-empty');
            const face = displayFace(i);
            const what = tokenLabel(name, face);
            const picked = ui.picks.includes(i);
            if (picked) {
                return slot(tableToken(name, face, {
                    state: 'lifted', key: `disp-${i}`,
                    label: `${what} is in your hand. Tap to put it back.`,
                    onclick: () => pickFromDisplay(i),
                }), 'is-lifted');
            }
            const canPick = taking && left > 0;
            return slot(tableToken(name, face, {
                key: `disp-${i}`,
                label: canPick ? `Take the ${what}` : what,
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

    const tray = specialsTray();
    const canPick = taking && left > 0;
    const specials = h('div.specials-tray', { role: 'group', 'aria-label': 'Specials tray' },
        h('div.zone-head', {},
            h('span.zone-name', { text: 'Specials tray' }),
            h('span.zone-count', { text: tray.length ? 'Into a glass, or drink it' : '' })),
        h('div.specials-tray-row', {},
            tray.length
                ? tray.map((name, i) => {
                    const what = ING[name]?.label ?? name;
                    const picked = ui.specialPicks.includes(i);
                    return slot(token(name, {
                        key: `spec-${i}`,
                        state: picked ? 'lifted' : canPick ? 'takeable' : undefined,
                        label: picked ? `${what} is in your hand. Tap to put it back.` : canPick ? `Take the ${what}` : what,
                        onclick: picked || canPick ? () => pickFromSpecials(i) : undefined,
                    }), picked ? 'is-lifted' : '');
                })
                : h('span.zone-empty', { text: 'Specials that come out of the bag wait here.' })));

    return h('section.supply', { 'aria-label': 'Ingredients' }, bag, display, specials);
}

// ─── Score track ────────────────────────────────────────────────────────────

function renderScoreTrack() {
    const seats = seatOrder();
    const target = gs().score_to_win ?? 40;
    const cells = Array.from({ length: target + 1 }, (_, n) => {
        const here = seats.filter((pid) => Math.min(target, gs().player_states[pid].points) === n);
        return h('li.score-cell', { cls: n % 5 === 0 ? 'is-five' : '' },
            n % 5 === 0 || n === target ? h('span.score-num', { text: n === target ? `${target}+ last round` : n, 'aria-hidden': 'true' }) : null,
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
    const held = interactive ? heldIngredient() : null;
    const placing = !!held;
    const space = interactive ? glassRoom(cupIndex) : null;
    const room = placing && (isSpecial(held.name) ? space.specials > 0 : space.base > 0);
    const staged = (it) => token(it.name, {
        state: 'placed', key: `staged-${it.key}`,
        label: `${ING[it.name].label} going into glass ${cupIndex + 1}. Tap to pick it back up.`,
        onclick: () => selectInHand(it.key),
    });
    // Spirits and mixers fill the glass; specials sit on the rim.
    const contents = [
        ...cup.ingredients.filter((n) => !isSpecial(n)).map((name) => token(name)),
        ...incoming.filter((it) => !isSpecial(it.name)).map(staged),
    ];
    const garnish = [
        ...cup.ingredients.filter(isSpecial).map((name) => token(name)),
        ...incoming.filter((it) => isSpecial(it.name)).map(staged),
    ];
    const layers = Array.from({ length: CUP_SIZE }, (_, i) => slot(contents[i] ?? null, contents[i] ? '' : 'is-empty'));
    const showRim = garnish.length || (placing && isSpecial(held.name));
    // The rim always takes its space, so glasses line up whether or not
    // they have specials on top; its slots show only when in use.
    const rim = h('span.glass-rim', { 'aria-hidden': 'true', cls: showRim ? '' : 'is-unused' },
        Array.from({ length: GLASS_SPECIALS }, (_, i) => slot(garnish[i] ?? null, garnish[i] ? '' : 'is-empty')));

    const vessel = h(room ? 'button.glass' : 'div.glass', {
        cls: `${room ? 'is-target' : ''}${cup.has_cup_doubler ? ' has-doubler' : ''}`,
        type: room ? 'button' : undefined,
        onclick: room ? () => placeSelected('cup', cupIndex) : undefined,
        'aria-label': `Glass ${cupIndex + 1}: ${cup.ingredients.length ? cup.ingredients.map((i) => ING[i].label).join(', ') : 'empty'}${cup.has_cup_doubler ? ', scores double' : ''}${room ? '. Tap to put the token here.' : ''}`,
        'data-k': room ? `glass-${cupIndex}` : undefined,
    },
    rim,
    cup.has_cup_doubler ? h('span.straw', { 'aria-hidden': 'true' }) : null,
    h('span.glass-body', {}, layers),
    h('span.glass-foot', { 'aria-hidden': 'true' }));

    const buttons = [];
    if (interactive && !handItems().length) {
        for (const a of actionsOf('sell_cup').filter((x) => x.params.cup_index === cupIndex && !x.params.additional_cups)) {
            const specials = a.params.declared_specials ?? [];
            const name = drinkName(cup.ingredients, specials);
            const order = a.params.order ? ` (+${a.params.order_bonus} order)` : '';
            buttons.push(h('button.btn.go.tiny', {
                type: 'button', onclick: () => sell(a.params), 'data-k': `sell-${cupIndex}-${specials.join('-')}`,
                'aria-label': `Sell glass ${cupIndex + 1} as ${name} for ${plural(a.params.points, 'point')}${a.params.order ? `, including +${a.params.order_bonus} for the ${a.params.order} order` : ''}`,
            }, h('strong', { text: `Sell for ${a.params.points}${freeNote('sell_cup')}` }), h('span', { text: `${name}${order}` })));
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

// One action can sell both glasses.
function sellBoth() {
    if (handItems().length) return null;
    const options = actionsOf('sell_cup').filter((a) => a.params.additional_cups?.length);
    if (!options.length) return null;
    const cups = mine().cups;
    return h('div.sell-both', {}, options.map((a) => {
        const second = a.params.additional_cups[0];
        const orderFor = (ci) => (a.params.orders ?? []).find((o) => o.cup_index === ci);
        const label = (ci, declared) => {
            const o = orderFor(ci);
            return `${drinkName(cups[ci].ingredients, declared ?? [])}${o ? ` (+${o.bonus} order)` : ''}`;
        };
        const names = `${label(a.params.cup_index, a.params.declared_specials)} and ${label(second.cup_index, second.declared_specials)}`;
        return h('button.btn.go.tiny', {
            type: 'button', onclick: () => sell(a.params), 'data-k': `sellboth-${JSON.stringify(a.params)}`,
            'aria-label': `Sell both glasses, ${names}, for ${plural(a.params.points, 'point')}`,
        }, h('strong', { text: `Sell both for ${a.params.points}${freeNote('sell_cup')}` }), h('span', { text: names }));
    }));
}

// A pair of lips, parted into a grin: the spot you drop tokens to drink them.
const LIPS_SVG = '<svg viewBox="0 0 64 34" aria-hidden="true">'
    + '<path d="M5 15.5C15 15 24 14.5 32 15.5C40 14.5 49 15 59 15.5C51 22 43 23.5 32 23.5S13 22 5 15.5Z" fill="#3b0a13"/>'
    + '<path d="M13 15.8C21 16.4 27 16 32 16.6C37 16 43 16.4 51 15.8C47 18.6 40 19.2 32 19.2S17 18.6 13 15.8Z" fill="#fbf3ea"/>'
    + '<path d="M3 15.5C10 10 18 4.5 24.5 4.8C28 5 30.2 6.8 32 8.8C33.8 6.8 36 5 39.5 4.8C46 4.5 54 10 61 15.5C52 14.2 42 13.4 32 15C22 13.4 12 14.2 3 15.5Z" fill="#b8233a" stroke="#7a1022" stroke-width="1" stroke-linejoin="round"/>'
    + '<path d="M5 15.5C13 22 22 23.5 32 23.5S51 22 59 15.5C57 24 46 31.5 32 31.5S7 24 5 15.5Z" fill="#d23249" stroke="#7a1022" stroke-width="1" stroke-linejoin="round"/>'
    + '<path d="M21 26.5C26 28.4 38 28.4 43 26.5" fill="none" stroke="#ff9eab" stroke-width="2.2" stroke-linecap="round" opacity=".75"/>'
    + '<path d="M17 9.6C19.5 8 22 7.4 24.5 7.6" fill="none" stroke="#e8687b" stroke-width="1.6" stroke-linecap="round" opacity=".8"/>'
    + '</svg>';

function mouth() {
    const drinks = stagedTo('mouth');
    const placing = !!heldIngredient();
    const after = drunkAfter(drinks.map((it) => it.name));
    const node = h(placing ? 'button.mouth' : 'div.mouth', {
        cls: placing ? 'is-target' : '',
        type: placing ? 'button' : undefined,
        onclick: placing ? () => placeSelected('mouth') : undefined,
        'aria-label': placing ? 'Your mouth: tap to drink the token you are holding' : 'Your mouth',
        'data-k': placing ? 'mouth' : undefined,
    },
    h('span.lips', { 'aria-hidden': 'true', svg: LIPS_SVG }),
    h('span.mouth-word', { text: 'Drink' }));
    return h('div.mouth-spot', {},
        node,
        h('div.mouth-tokens', {}, drinks.map((it) => token(it.name, {
            state: 'placed', key: `staged-${it.key}`,
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
        return slot(f ? token(f.n, { state: f.staged ? 'placed' : undefined }) : null, f ? '' : 'is-empty');
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
            hospital
                ? h('span.drunk-ambulance', { svg: AMBULANCE })
                : h('span.drunk-num', { text: lvl, 'aria-hidden': 'true' }),
            h('span.drunk-word', { text: hospital ? 'Hospital' : DRUNK_LABELS[lvl], 'aria-hidden': 'true' }),
            here ? h('span.pawn', { style: { '--seat': seatColour(pid) }, 'aria-hidden': 'true' }) : null);
    });
    const where = out ? 'in hospital' : `${DRUNK_LABELS[ps.drunk_level] ?? ''}, level ${ps.drunk_level} of ${MAX_DRUNK}`;
    return h('div.drunk', { role: 'group', 'aria-label': `Drunk track: ${where}` },
        h('div.zone-head', {},
            h('span.zone-name', { text: 'Drunk' }),
            h('span.zone-count', { text: out ? 'In hospital' : `Takes ${ps.take_count} a turn` })),
        h('ol.drunk-steps', {}, steps));
}

// Specials on a player's mat: only in games started with the special dice.
function matSpecials(pid, { interactive }) {
    const ps = gs().player_states[pid];
    const incoming = interactive ? handItems().filter((it) => isSpecialToken(it) && ui.staged[it.key]) : [];
    const leaving = new Set(incoming.map((it) => ui.staged[it.key].swap).filter(Boolean));
    const arriving = incoming.map((it) => specialOf(it)).filter(Boolean);
    return h('div.specials', { role: 'group', 'aria-label': 'Specials' },
        h('div.zone-head', {},
            h('span.zone-name', { text: 'Specials' }),
            h('span.zone-count', { text: `${ps.special_ingredients.length} of ${MAX_SPECIALS}` })),
        h('div.specials-row', {},
            ps.special_ingredients.map((s) => token(s, {
                state: leaving.has(s) ? 'ghost' : undefined,
                label: leaving.has(s) ? `${SPECIALS[s]?.label}, going back` : SPECIALS[s]?.label,
            })),
            arriving.map((s) => token(s, { state: 'placed', label: `${SPECIALS[s]?.label}, coming to your mat` })),
            !ps.special_ingredients.length && !arriving.length ? h('span.zone-empty', { text: 'None yet' }) : null));
}

// Choices for the special token you're holding: which special ("choose any")
// and, when you'd have more than two, which to give back.
function specialChoices(it) {
    const draft = ui.specialDraft[it.key] ?? {};
    const atLimit = specialsAfterHand(it.key) >= MAX_SPECIALS;
    if (it.face === 'any' && !draft.choice) {
        const options = freeSpecialTypes(it.key);
        return h('div.special-choice', { role: 'group', 'aria-label': 'Choose a special' },
            h('p', { text: options.length ? 'Choose any special nobody holds:' : 'Every special is taken. Leave this one.' }),
            h('div.special-options', {},
                options.map((t) => h('button.btn.tiny', {
                    type: 'button', onclick: () => settleSpecial(it.key, { choice: t }), 'data-k': `choose-${t}`,
                }, token(t, { print: true }), h('span', { text: SPECIALS[t].label }))),
                h('button.btn.tiny.quiet-dark', { type: 'button', onclick: () => settleSpecial(it.key, { leave: true }), text: 'Leave it', 'data-k': 'leave-special' })));
    }
    if (atLimit) {
        const want = SPECIALS[draft.choice ?? it.face]?.label ?? 'it';
        return h('div.special-choice', { role: 'group', 'aria-label': 'Swap or leave' },
            h('p', { text: `You hold two specials already. Swap one back for ${want}, or leave it:` }),
            h('div.special-options', {},
                mine().special_ingredients.map((sp) => h('button.btn.tiny', {
                    type: 'button', onclick: () => settleSpecial(it.key, { swap: sp }), 'data-k': `swap-${sp}`,
                }, token(sp, { print: true }), h('span', { text: `Give back ${SPECIALS[sp].label}` }))),
                h('button.btn.tiny.quiet-dark', { type: 'button', onclick: () => settleSpecial(it.key, { leave: true }), text: `Leave ${want}`, 'data-k': 'leave-special' })));
    }
    return null;
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
                ? items.map((it) => tableToken(it.name, it.face, {
                    key: `hand-${it.key}`,
                    state: ui.staged[it.key] ? 'ghost' : undefined,
                    selected: ui.selected === it.key,
                    onclick: () => selectInHand(it.key),
                    label: ui.staged[it.key]
                        ? `${tokenLabel(it.name, it.face)}, placed. Tap to change.`
                        : `${tokenLabel(it.name, it.face)}${it.source === 'pending' ? ' from the bag' : ''}${ui.selected === it.key ? ', holding' : ', tap to hold'}`,
                }))
                : h('span.zone-empty', { text: 'Tap tokens on the display, or draw from the bag.' })),
        (() => {
            const held = items.find((it) => it.key === ui.selected);
            return held && isSpecialToken(held) && !ui.staged[held.key] ? specialChoices(held) : null;
        })(),
        items.some((it) => it.source === 'pending')
            ? h('p.hand-note', { text: 'Bag draws can’t go back. Everything goes in a glass or your mouth.' }) : null,
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
            oldSpecials() ? matSpecials(pid, { interactive }) : null)),
    h('div.mat-cards', { role: 'group', 'aria-label': isMe ? 'Your cards' : `${seatName(pid)}'s cards` },
        ps.cards.length
            ? ps.cards.map((c, i) => cardFace(c, { owner: pid, index: i, compact: !isMe }))
            : h('span.zone-empty', { text: 'No cards claimed yet' })));
}

// ─── Menu and log ───────────────────────────────────────────────────────────

// Where a special is, for the menu: in your glass, on the specials tray, or
// still in the bag (games with special dice: on someone's mat).
function specialWhere(sp) {
    const name = sp.toUpperCase();
    if (mine()?.cups.some((c) => c.ingredients.includes(name))) return 'in your glass';
    const onTray = specialsTray().filter((n) => n === name).length;
    if (onTray) return onTray > 1 ? `${onTray} on the tray` : 'on the tray';
    for (const [pid, ps] of Object.entries(gs().player_states)) {
        if (ps.special_ingredients.includes(sp)) return pid === me.id ? 'yours' : `${seatName(pid)} has it`;
    }
    if ((gs().display_specials ?? []).includes(sp)) return 'on the display';
    return 'in the bag';
}

// How close one of your glasses is to a recipe: what still has to go in,
// or null when the glass holds something the recipe doesn't want.
function glassProgress(cup, recipe) {
    const need = [...recipe];
    for (const i of cup) {
        const at = need.indexOf(i);
        if (at === -1) return null;
        need.splice(at, 1);
    }
    return need;
}

const listTokens = (names) => {
    const counts = {};
    for (const n of names) counts[n] = (counts[n] ?? 0) + 1;
    return Object.entries(counts).map(([n, c]) => `${c} ${ING[n].label.replace(' water', '')}`).join(', ');
};

// The drinks menu, printed like a taverna menu. On your turn it reads your
// glasses and specials: what each glass is close to, and which specials you
// have or where they are.
function menu() {
    const started = game.status === 'STARTED' && isMember() && mine();
    // Your glasses, with what you've just placed in them this turn
    const cups = started
        ? mine().cups.map((c, i) => [...c.ingredients, ...(myTurn() ? stagedTo('cup', i).map((it) => it.name) : [])])
        : [];
    const orders = (gs().card_rows.find((r) => r.position === 2)?.cards ?? []).filter((c) => c.card_type === 'order');
    const wanted = (fn) => orders.find(fn);

    // What each glass still needs for a recipe, specials included (in older
    // games a special can also come from your mat).
    const glassNotes = (recipe, specials = []) => cups.map((cup, i) => {
        if (!cup.length) return null;
        const parts = splitGlass(cup);
        const need = glassProgress(parts.base, recipe);
        const needSpecials = glassProgress(parts.specials, specials);
        if (need === null || needSpecials === null) return null;
        const missing = needSpecials.filter((sp) => !mine().special_ingredients.includes(sp)).map((sp) => SPECIALS[sp].label);
        const add = [listTokens(need), ...missing].filter(Boolean).join(', ');
        if (add) return h('span.menu-glass', { text: `Glass ${i + 1}: add ${add}` });
        return h('span.menu-glass.is-ready', { text: `Glass ${i + 1}: ready to sell` });
    }).filter(Boolean);

    const cocktails = COCKTAILS.map((c) => {
        const order = wanted((o) => o.drink === 'cocktail' && o.cocktail === c.name);
        const specialBits = c.specials.map((sp) => {
            const where = started ? specialWhere(sp) : null;
            return h('span.menu-special', { cls: where === 'yours' || where === 'in your glass' ? 'is-yours' : '' },
                token(sp, { print: true }), `${SPECIALS[sp].label}${where ? ` (${where})` : ''}`);
        });
        return h('li.menu-item', { cls: order ? 'is-wanted' : '' },
            h('div.menu-line', {},
                h('span.menu-name', { text: c.name }),
                order ? h('span.menu-wanted', { text: `Wanted +${order.bonus}` }) : null,
                h('span.menu-dots', { 'aria-hidden': 'true' }),
                h('b.menu-points', { text: c.points })),
            h('div.menu-recipe', {},
                h('span.menu-toks', { 'aria-label': listTokens(c.cup) }, c.cup.map((i) => token(i, { print: true }))),
                specialBits),
            started ? h('div.menu-glasses', {}, glassNotes(c.cup, c.specials)) : null);
    });

    const longDrinks = [];
    for (const s of SPIRITS) {
        for (const m of PAIRINGS[s]) {
            const order = wanted((o) => o.drink === 'simple' && o.spirit_type === s && o.mixer_type === m);
            const names = cups.map((cup, i) => (cup.length && servesOrder({ drink: 'simple', spirit_type: s, mixer_type: m }, cup)
                ? `Glass ${i + 1}` : null)).filter(Boolean);
            longDrinks.push(h('li.menu-long', { cls: order ? 'is-wanted' : '' },
                h('span.menu-toks', {}, token(s, { print: true }), token(m, { print: true })),
                h('span.menu-name', { text: `${ING[s].label} and ${ING[m].label.replace(' water', '')}` }),
                order ? h('span.menu-wanted', { text: `Wanted +${order.bonus}` }) : null,
                names.length ? h('span.menu-glass.is-ready', { text: `${names.join(' and ')}: ready` }) : null));
        }
    }
    const slammerOrder = wanted((o) => o.drink === 'slammer');

    return h('section.menu', { 'aria-label': 'Drinks menu' },
        h('header.menu-head', {},
            h('p.menu-house', { text: 'Taverna Corfu' }),
            h('h2.menu-title', { text: 'Drinks' }),
            h('p.menu-sub', { text: 'Prices in points. Orders on the table add their bonus.' })),
        h('h3.menu-section', { text: 'Cocktails' }),
        h('p.menu-note', { text: 'The glass must match exactly, specials included: take them off the specials tray into the glass.' }),
        h('ul.menu-list', {}, cocktails),
        h('h3.menu-section', { text: 'Long drinks' }),
        h('p.menu-note', { text: 'One spirit and one kind of mixer: 1 point. Two of the same spirit: 3.' }),
        h('ul.menu-longs', {}, longDrinks),
        h('h3.menu-section', { text: 'Shots' }),
        h('ul.menu-longs', {}, h('li.menu-long', { cls: slammerOrder ? 'is-wanted' : '' },
            h('span.menu-toks', {}, token('TEQUILA', { print: true }), token('TEQUILA', { print: true })),
            h('span.menu-name', { text: 'Tequila Slammer, 3 points' }),
            slammerOrder ? h('span.menu-wanted', { text: `Wanted +${slammerOrder.bonus}` }) : null)));
}

// ─── The drinks menu and rules panel ────────────────────────────────────────

function toggleSheet(which) {
    const opening = ui.sheet !== which;
    ui.sheet = opening ? which : null;
    render({ force: true });
    if (opening) $('sheet').querySelector('.sheet-close')?.focus();
    else document.querySelector(`[data-k="open-${which}"]`)?.focus();
}

function closeSheet() {
    const was = ui.sheet;
    if (!was) return;
    ui.sheet = null;
    render({ force: true });
    document.querySelector(`[data-k="open-${was}"]`)?.focus();
}

// Everyone's glasses, kept in view at the top of the drinks menu: yours
// first (with what you've just placed), then the others in turn order.
function sheetGlasses() {
    if (game.status !== 'STARTED') return null;
    const seats = seatOrder();
    const start = Math.max(0, seats.indexOf(me.id));
    const order = [...seats.slice(start), ...seats.slice(0, start)];
    const glassToks = (pid, cup, i) => {
        const staged = pid === me.id && myTurn() ? stagedTo('cup', i) : [];
        const all = [...cup.ingredients, ...staged.map((it) => it.name)];
        return h('span.sheet-glass-toks', {
            role: 'img',
            'aria-label': `Glass ${i + 1}: ${all.length ? all.map((n) => ING[n]?.label ?? n).join(', ') : 'empty'}`,
        },
        all.length
            ? [...cup.ingredients.map((n) => token(n, { print: true })),
                ...staged.map((it) => token(it.name, { print: true, state: 'placed' }))]
            : h('span.sheet-glass-empty', { text: 'Empty' }));
    };
    return h('div.sheet-glasses', { role: 'group', 'aria-label': 'Everyone\'s glasses' },
        order.map((pid) => {
            const ps = gs().player_states[pid];
            return h('div.sheet-glass', { cls: pid === me.id ? 'is-mine' : '', style: { '--seat': seatColour(pid) } },
                h('span.sheet-glass-name', {},
                    h('span.pawn', { 'aria-hidden': 'true' }),
                    h('span', { text: pid === me.id ? 'You' : seatName(pid) })),
                h('span.sheet-glass-cups', {}, ps.cups.map((cup, i) => glassToks(pid, cup, i))));
        }));
}

// A strip of every player at a glance, in the header that scrolls away:
// points, drunk level, bladder, songs, and whose turn it is.
function renderOverview() {
    const box = $('overview');
    if (!box) return;
    if (!game || game.status === 'NEW' || !gs()?.player_states || !gs().turn_order?.length) {
        box.replaceChildren();
        return;
    }
    const target = gs().score_to_win ?? 40;
    box.replaceChildren(h('ol.overview-list', { 'aria-label': 'Players at a glance' },
        seatOrder().map((pid) => {
            const ps = gs().player_states[pid];
            const turn = gs().player_turn === pid && !gs().winner;
            const out = ps.status === 'hospitalised' ? 'Hospital' : ps.status === 'wet' ? 'Wet' : ps.status === 'quit' ? 'Left' : null;
            const songs = ps.cards.filter((c) => c.card_type === 'karaoke').length;
            return h('li.overview-player', {
                cls: `${turn ? 'is-turn' : ''}${out ? ' is-out' : ''}${pid === me.id ? ' is-mine' : ''}`,
                style: { '--seat': seatColour(pid) },
                'aria-label': `${pid === me.id ? 'You' : seatName(pid)}: ${plural(ps.points, 'point')} of ${target}, `
                    + `${out ?? `drunk ${ps.drunk_level}`}, bladder ${ps.bladder.length} of ${ps.bladder_capacity}`
                    + `${songs ? `, ${plural(songs, 'song')}` : ''}${turn ? ', playing now' : ''}`,
            },
            h('span.pawn', { 'aria-hidden': 'true' }),
            h('span.ov-name', { text: pid === me.id ? 'You' : seatName(pid), 'aria-hidden': 'true' }),
            h('span.ov-stats', { 'aria-hidden': 'true' },
                h('b', { text: `${ps.points}` }), ' pts',
                h('span.ov-sep', { text: ' · ' }),
                out ?? `drunk ${ps.drunk_level}`,
                h('span.ov-sep', { text: ' · ' }),
                `bladder ${ps.bladder.length}/${ps.bladder_capacity}`,
                songs ? h('span', { text: ` · 🎤${songs}` }) : null));
        })));
}

function renderSheet() {
    const box = $('sheet');
    const open = !!ui.sheet && game.status !== 'NEW';
    document.body.classList.toggle('has-sheet', open);
    if (!open) {
        box.hidden = true;
        box.replaceChildren();
        return;
    }
    const isMenu = ui.sheet === 'menu';
    const scroll = box.querySelector('.sheet-body')?.scrollTop ?? 0;
    box.hidden = false;
    box.setAttribute('aria-label', isMenu ? 'Drinks menu' : 'Rules');
    box.replaceChildren(...[
        h('div.sheet-head', {},
            h('h2.sheet-title', { text: isMenu ? 'Drinks menu' : 'How to play' }),
            h('button.btn.tiny.sheet-close', {
                type: 'button', text: 'Close', onclick: closeSheet, 'data-k': 'sheet-close',
                'aria-label': `Close the ${isMenu ? 'drinks menu' : 'rules'}`,
            })),
        isMenu ? sheetGlasses() : null,
        h('div.sheet-body', {}, isMenu ? menu() : rulebook()),
    ].filter(Boolean));
    box.querySelector('.sheet-body').scrollTop = scroll;
}

const RECENT_MOVES = 8;

function chalkboard() {
    const all = moves.map((m, i) => ({ n: i + 1, text: describeMove(m, nameOf), mine: m.player_id === me.id })).reverse();
    const shown = ui.historyOpen ? all : all.slice(0, RECENT_MOVES);
    return h('section.chalk', { 'aria-label': 'What happened' },
        h('h2.chalk-title', { text: 'What happened' }),
        shown.length
            ? h('ol.chalk-list', { reversed: true, start: all.length }, shown.map((m) => h('li', { cls: m.mine ? 'is-mine' : '', value: m.n, text: m.text })))
            : h('p.chalk-empty', { text: 'Nothing yet. First round’s on the house.' }),
        all.length > RECENT_MOVES
            ? h('button.btn.tiny.chalk-more', {
                type: 'button',
                'aria-expanded': String(ui.historyOpen),
                onclick: () => { ui.historyOpen = !ui.historyOpen; render({ force: true }); },
                text: ui.historyOpen ? 'Show the latest only' : `Show all ${all.length} moves`,
                'data-k': 'history-toggle',
            })
            : null);
}

function rulebook() {
    return h('section.rulebook', { 'aria-label': 'Rules' },
        h('p.rulebook-intro', { text: RULES_INTRO }),
        h('div.rulebook-pages', {}, RULES.map((part) => h('section.rule-part', {},
            h('h3', { text: part.title }),
            h('ul', {}, part.items.map((t) => h('li', { text: t })))))));
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
        if (ps?.status === 'active') {
            bits.push(h('button.btn.tiny.quiet', { type: 'button', onclick: () => askLeave('quit'), text: 'Leave the game', 'data-k': 'leave' }));
        }
        if (game.host === me.id) {
            bits.push(h('button.btn.tiny.quiet', { type: 'button', onclick: () => askLeave('cancel'), text: 'Call off the game', 'data-k': 'call-off' }));
        }
    }
    if (!bits.length && !ui.leaving) return null;
    return h('nav.housekeeping', { 'aria-label': 'Game options' }, bits, leaveConfirm());
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

let invite = null; // built once so re-renders keep its state

function inviteLink() {
    invite ??= inviteBox(gameId, {
        classes: { button: 'btn' },
        onCopied: (ok) => toast(ok ? 'Invite link copied' : 'Press Ctrl+C (or Cmd+C) to copy the link', ok ? 'info' : 'error'),
    });
    return invite;
}

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
        isMember() && game.players.length < 4 ? inviteLink() : null,
    ].filter(Boolean);
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
        parts.push(ui.leaving ? leaveConfirm() : h('button.btn.tiny.quiet', {
            type: 'button', text: 'Call off this game', 'data-k': 'call-off', onclick: () => askLeave('cancel'),
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
        ui.picks, ui.specialPicks, ui.staged, ui.specialDraft, ui.selected, ui.historyOpen, !!ui.prompt, ui.sheet, ui.leaving]);
    if (!force && signature === lastSignature) return;
    lastSignature = signature;
    const focusKey = document.activeElement?.getAttribute?.('data-k');

    if (game.status === 'NEW') {
        turnbar();
        renderSheet();
        renderOverview();
        renderLobby().then(() => restoreFocus(focusKey));
        return;
    }
    if (game.status === 'ENDED' && !gs()?.turn_order?.length) {
        // Called off in the lobby, before anyone played
        turnbar();
        renderSheet();
        renderOverview();
        $('table').replaceChildren(h('section.lobby', { id: 'lobby' },
            h('h2.lobby-title', { text: 'This game was called off' }),
            h('p.lobby-sub', { text: `${seatName(game.host)} called it off before the bar opened.` }),
            h('a.btn.go', { href: '/', text: 'Back to the games' })));
        return;
    }
    reconcile();
    turnbar();
    document.body.classList.toggle('is-my-turn', myTurn());

    const seats = seatOrder();
    const start = Math.max(0, seats.indexOf(me.id));
    const around = [...seats.slice(start + 1), ...seats.slice(0, start)].filter((pid) => pid !== me.id);

    $('table').replaceChildren(...[
        around.length ? h('div.across', { 'aria-label': 'Other players' }, around.map(mat)) : null,
        // The bag and display sit under the cards, right above your mat
        h('div.middle', {}, h('div.middle-main', {}, renderMarket(), renderSupply()), h('div.middle-side', {}, renderScoreTrack())),
        isMember() && gs().player_states[me.id] ? mat(me.id) : null,
        h('div.extras', {}, chalkboard()),
        housekeeping(),
    ].filter(Boolean));
    renderSheet();
    renderOverview();
    ending();
    restoreFocus(focusKey);
}

function restoreFocus(key) {
    if (!key) return;
    const target = document.querySelector(`[data-k="${CSS.escape(key)}"]`);
    if (target && document.activeElement !== target) target.focus({ preventScroll: true });
}

boot();
