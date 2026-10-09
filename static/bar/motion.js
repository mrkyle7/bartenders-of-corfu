// Motion for the table: each redraw rebuilds the table, so before it we
// note where every piece is (snapshot) and after it we fly each piece from
// where it was to where it is now (play). What moved is worked out from the
// pieces themselves, so it works the same for your own moves and for other
// players' moves as they come in:
//
//   - a piece with a motion key (data-m: cards, pawns) is the same piece
//     before and after, wherever it went;
//   - a token is known by where it sits (the nearest data-loc) and its name;
//     one that left a place and one of the same name that arrived elsewhere
//     are the same token on the move;
//   - a token that arrives from nowhere came out of the bag (or from the
//     piece named in its data-from, e.g. the display slot you picked it
//     from, which has then moved rather than vanished), and one that
//     vanishes goes back into the bag;
//   - a token lifted off the display or tray, or ghosted in your hand once
//     placed, is only a reminder of where it was: the piece is in your hand
//     or where you put it;
//   - a market card that arrives from nowhere is dealt from its pile, and
//     one that vanishes goes to the bottom of its pile.
//
// Everything is decoration: nothing waits on it, and with reduced motion
// asked for it does nothing at all.

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
const EASE = 'cubic-bezier(.22,.8,.3,1)';
const FLIGHT = 620;
const SHIFT = 260;
const GAP = 70; // between one flying token and the next

let layer = null;

function rectOf(el) {
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height };
}

const isPiece = (el) => !el.classList.contains('is-ghost') && !el.classList.contains('is-lifted')
    && !el.closest('.tok-print, .card-costbadge, .card-subject');

export function snapshot(root) {
    if (!root) return null;
    const tokens = [];
    const keyed = new Map();
    const anchors = new Map();
    const values = new Map();
    for (const el of root.querySelectorAll('[data-m]')) keyed.set(el.dataset.m, { el, r: rectOf(el), pile: el.dataset.pile });
    const seen = new Map();
    // Tokens printed on cards don't count; tokens stored on a Store card do
    // (they sit in a data-loc of their own).
    for (const el of root.querySelectorAll('.tok[data-n], .loo')) {
        if (!isPiece(el)) continue;
        const loc = el.closest('[data-loc]')?.dataset.loc;
        if (!loc) continue;
        const name = el.classList.contains('loo') ? 'LOO' : el.dataset.n;
        const base = `${loc}|${name}`;
        const n = seen.get(base) ?? 0;
        seen.set(base, n + 1);
        tokens.push({ el, r: rectOf(el), key: `${base}|${n}`, name, from: el.dataset.from, k: el.dataset.k });
    }
    for (const el of root.querySelectorAll('[data-k], [data-loc]')) {
        if (el.dataset.k) anchors.set(el.dataset.k, rectOf(el));
        if (el.dataset.loc) anchors.set(`loc:${el.dataset.loc}`, rectOf(el));
    }
    for (const el of root.querySelectorAll('[data-pts]')) values.set(el.dataset.pts, { v: Number(el.dataset.v), el });
    return { tokens, keyed, anchors, values, origin: rectOf(root) };
}

function ensureLayer() {
    if (!layer || !layer.isConnected) {
        layer = document.createElement('div');
        layer.className = 'motion-layer';
        layer.setAttribute('aria-hidden', 'true');
        document.body.append(layer);
    }
    return layer;
}

// Move el (already at `to`) so it starts at `from` and lands where it is.
function fly(el, from, to, zoom, { delay = 0, arc = 46, duration = FLIGHT, flip = false } = {}) {
    const dx = (from.x - to.x) / zoom;
    const dy = (from.y - to.y) / zoom;
    if (Math.abs(dx) < 4 && Math.abs(dy) < 4 && !flip) return; // a nudge, not a move
    const s = to.w ? from.w / to.w : 1;
    const lift = Math.min(arc, Math.hypot(dx, dy) / 3);
    const frames = [
        { transform: `translate(${dx}px, ${dy}px) scale(${s})${flip ? ' rotateY(90deg)' : ''}` },
        { transform: `translate(${dx / 2}px, ${dy / 2 - lift}px) scale(${((s + 1) / 2) * 1.12})${flip ? ' rotateY(45deg)' : ''}`, offset: 0.45 },
        { transform: 'none' },
    ];
    el.classList.add('is-flying');
    const anim = el.animate(frames, { duration, delay, easing: EASE, fill: 'backwards' });
    anim.finished.then(() => el.classList.remove('is-flying'), () => el.classList.remove('is-flying'));
    return anim;
}

// A piece that has left the table: its old element flies off on the layer.
function ghost(item, to, zoom, { delay = 0, fade = true } = {}) {
    const el = item.el;
    const host = ensureLayer();
    el.classList.remove('is-takeable', 'is-flying');
    el.removeAttribute('data-k');
    el.removeAttribute('data-m');
    Object.assign(el.style, {
        position: 'absolute',
        left: `${(item.r.x - item.r.w / 2) / zoom}px`,
        top: `${(item.r.y - item.r.h / 2) / zoom}px`,
        width: `${item.r.w / zoom}px`,
        height: `${item.r.h / zoom}px`,
        margin: '0',
    });
    host.append(el);
    const dx = to ? (to.x - item.r.x) / zoom : 0;
    const dy = to ? (to.y - item.r.y) / zoom : -20;
    const end = to ? `translate(${dx}px, ${dy}px) scale(0.35)` : 'translateY(-20px) scale(0.9)';
    const anim = el.animate([
        { transform: 'none', opacity: 1 },
        { transform: `translate(${dx / 2}px, ${dy / 2 - 40}px) scale(1.05)`, opacity: 1, offset: 0.45 },
        { transform: end, opacity: fade ? 0 : 1 },
    ], { duration: FLIGHT, delay, easing: EASE, fill: 'both' });
    anim.finished.then(() => el.remove(), () => el.remove());
}

function wobble(el, delay) {
    el?.animate([
        { transform: 'none' },
        { transform: 'scale(1.08, 0.94) rotate(-3deg)' },
        { transform: 'scale(0.96, 1.05) rotate(2deg)' },
        { transform: 'none' },
    ], { duration: 420, delay, easing: 'ease-out' });
}

function float(text, at, zoom, delay) {
    const host = ensureLayer();
    const tag = document.createElement('span');
    tag.className = 'motion-float';
    tag.textContent = text;
    tag.style.left = `${at.x / zoom}px`;
    tag.style.top = `${at.y / zoom}px`;
    host.append(tag);
    tag.animate([
        { transform: 'translate(-50%, -30%) scale(0.6)', opacity: 0 },
        { transform: 'translate(-50%, -110%) scale(1.15)', opacity: 1, offset: 0.25 },
        { transform: 'translate(-50%, -240%) scale(1)', opacity: 0 },
    ], { duration: 1500, delay, easing: 'ease-out', fill: 'both' }).finished.then(() => tag.remove(), () => tag.remove());
}

export function play(before, root, zoom = 1) {
    if (!before || !root || reduced.matches) return;
    const after = snapshot(root);
    // If the whole table moved (the turn bar above it grew a line, say),
    // that isn't a piece moving: measure everything from the table.
    const sx = after.origin.x - before.origin.x;
    const sy = after.origin.y - before.origin.y;
    const shift = (r) => ({ ...r, x: r.x + sx, y: r.y + sy });
    for (const list of [before.tokens, [...before.keyed.values()]]) for (const t of list) t.r = shift(t.r);
    for (const [k, r] of before.anchors) before.anchors.set(k, shift(r));
    const bagEl = root.querySelector('[data-loc="bag"]');
    const bag = after.anchors.get('loc:bag') ?? before.anchors.get('loc:bag');
    let wait = 0; // stagger for long flights
    let bagUsed = 0;

    // Pieces that are the same piece before and after: cards, pawns.
    for (const [m, now] of after.keyed) {
        const was = before.keyed.get(m);
        if (was) {
            const far = Math.hypot(was.r.x - now.r.x, was.r.y - now.r.y) > 120;
            fly(now.el, was.r, now.r, zoom, far ? { delay: wait++ * GAP } : { duration: SHIFT, arc: 0 });
        } else if (now.pile) {
            const pile = after.anchors.get(`loc:pile-${now.pile}`) ?? before.anchors.get(`loc:pile-${now.pile}`);
            if (pile) fly(now.el, pile, now.r, zoom, { delay: 250 + wait++ * GAP * 2, flip: true, duration: 760 });
        }
    }
    for (const [m, was] of before.keyed) {
        if (after.keyed.has(m) || !was.pile) continue;
        const pile = after.anchors.get(`loc:pile-${was.pile}`);
        ghost(was, pile, zoom, { delay: wait++ * GAP });
    }

    // Tokens: same place, same name → the same token (maybe shuffled along).
    const oldByKey = new Map(before.tokens.map((t) => [t.key, t]));
    const newKeys = new Set(after.tokens.map((t) => t.key));
    const gone = before.tokens.filter((t) => !newKeys.has(t.key));
    const arrived = [];
    for (const t of after.tokens) {
        const was = oldByKey.get(t.key);
        if (was) fly(t.el, was.r, t.r, zoom, { duration: SHIFT, arc: 0 });
        else arrived.push(t);
    }
    const take = (match) => {
        const i = gone.findIndex(match);
        return i < 0 ? null : gone.splice(i, 1)[0];
    };
    for (const t of arrived) {
        const hinted = t.from && before.anchors.get(t.from);
        // The piece it came from has moved here, not gone back in the bag.
        if (hinted) take((g) => g.k === t.from);
        const was = hinted ? null : take((g) => g.name === t.name);
        const from = hinted ?? was?.r ?? null;
        if (from) {
            fly(t.el, from, t.r, zoom, { delay: wait++ * GAP });
        } else if (bag && t.name !== 'LOO') {
            fly(t.el, { ...bag, w: bag.w * 0.35 }, t.r, zoom, { delay: 180 + bagUsed++ * GAP * 1.6, arc: 90 });
        }
    }
    if (bagUsed) for (let i = 0; i < Math.min(bagUsed, 3); i++) wobble(bagEl, 120 + i * GAP * 1.6);

    // Tokens that left the table go back in the bag (sold, wee'd away).
    let toBag = 0;
    for (const g of gone) {
        if (g.name === 'LOO' || !bag) continue;
        ghost(g, bag, zoom, { delay: toBag++ * 45 });
    }
    if (toBag) wobble(bagEl, FLIGHT * 0.7);

    // Points scored float up from the score.
    for (const [pid, now] of after.values) {
        const was = before.values.get(pid);
        if (was && now.v > was.v) {
            float(`+${now.v - was.v}`, rectOf(now.el), zoom, 250);
            now.el.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.5)' }, { transform: 'scale(1)' }],
                { duration: 700, delay: 250, easing: 'ease-out' });
        }
    }
}
