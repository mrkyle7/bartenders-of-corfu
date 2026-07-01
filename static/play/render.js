// Pure rendering of the game state into the Table View board.
// All interactivity is delegated to handlers supplied via ctx.on — the
// renderer decides *what* is tappable, app.js decides what happens.

import { CARD_TYPES, ING, SPECIAL_TYPES, STATUS_LABELS } from './meta.js';
import { el } from './ui.js';

const INITIAL_BLADDER_CAPACITY = 8;
const MAX_DRUNK = 5;

// ─── Small pieces ────────────────────────────────────────────────────────────

export function token(name, { size = '', onclick, highlight = false } = {}) {
    const meta = ING[name] ?? { label: name, short: '?', kind: 'mixer', color: '#888', text: '#000' };
    const tag = onclick ? 'button' : 'span';
    const node = el(`${tag}.tok.tok-${meta.kind}${size ? `.tok-${size}` : ''}`, {
        onclick,
        'aria-label': onclick ? `${meta.label} — tap to take` : meta.label,
        title: meta.label,
    }, el('span.tok-glyph', { text: meta.short, 'aria-hidden': 'true' }));
    node.style.setProperty('--tok-color', meta.color);
    node.style.setProperty('--tok-text', meta.text);
    if (highlight) node.classList.add('tok-live');
    return node;
}

export function specialChip(value, { onclick, selected } = {}) {
    const meta = SPECIAL_TYPES[value] ?? { label: value, icon: '✨' };
    const tag = onclick ? 'button' : 'span';
    const node = el(`${tag}.special-chip`, {
        onclick,
        'aria-label': `Special ingredient: ${meta.label}`,
        'aria-pressed': onclick ? String(!!selected) : undefined,
    },
        el('span', { text: meta.icon, 'aria-hidden': 'true' }),
        el('span.special-chip-label', { text: meta.label }),
    );
    if (selected) node.classList.add('selected');
    return node;
}

function costDots(card) {
    // Cost rendered as physical mini-tokens, e.g. three rum dots.
    const req = card.cost?.[0];
    const type = card.spirit_type ?? card.mixer_type;
    const count = req?.count ?? 0;
    if (card.card_type === 'cup_doubler') {
        return el('span.card-cost', { 'aria-label': 'Costs 3 of any one spirit drunk' },
            Array.from({ length: 3 }, () => el('span.cost-dot.cost-dot-any', { text: '?' })));
    }
    const meta = ING[type];
    const dots = Array.from({ length: count }, () => {
        const d = el('span.cost-dot');
        if (meta) d.style.setProperty('--tok-color', meta.color);
        return d;
    });
    return el('span.card-cost', { 'aria-label': `Costs ${count} ${meta?.label ?? ''} drunk` }, dots);
}

export function cardFace(card, { claimable = false, onclick } = {}) {
    const type = CARD_TYPES[card.card_type] ?? { icon: '❓', title: card.card_type };
    const node = el(onclick ? 'button.card' : 'div.card', {
        onclick,
        'data-card-id': card.id,
        'aria-label': `${card.name} (${type.title})${claimable ? ' — tap to claim' : ''}`,
    },
        el('span.card-icon', { text: type.icon, 'aria-hidden': 'true' }),
        el('span.card-name', { text: card.name }),
        costDots(card),
    );
    node.classList.add(`card-${card.card_type}`);
    if (claimable) node.classList.add('claimable');
    return node;
}

function drunkMeter(level, takeCount) {
    const segs = Array.from({ length: MAX_DRUNK }, (_, i) =>
        el('span.drunk-seg', { 'data-on': i < level ? '1' : undefined, 'data-danger': i >= 3 ? '1' : undefined }));
    return el('div.drunk-meter', {
        role: 'img',
        'aria-label': `Drunk level ${level} of ${MAX_DRUNK}. You must take ${takeCount} ingredients per turn.`,
    },
        el('span.meter-label', { text: '🍺', 'aria-hidden': 'true' }),
        el('span.drunk-segs', {}, segs),
        el('span.meter-num', { text: String(level) }),
    );
}

function bladderRow(ps, { onclick } = {}) {
    const sealed = INITIAL_BLADDER_CAPACITY - ps.bladder_capacity;
    const slots = [];
    for (let i = 0; i < ps.bladder_capacity; i++) {
        const ing = ps.bladder[i];
        slots.push(ing
            ? el('span.bladder-slot.filled', {}, token(ing, { size: 'xs' }))
            : el('span.bladder-slot'));
    }
    for (let i = 0; i < sealed; i++) {
        slots.push(el('span.bladder-slot.sealed', { title: 'Sealed by a toilet token', text: '🚽' }));
    }
    const full = ps.bladder.length >= ps.bladder_capacity;
    const node = el(onclick ? 'button.bladder' : 'div.bladder', {
        onclick,
        'aria-label': `Bladder: ${ps.bladder.length} of ${ps.bladder_capacity}${onclick ? ' — tap to go for a wee' : ''}`,
    },
        el('span.meter-label', { text: '💧', 'aria-hidden': 'true' }),
        el('span.bladder-slots', {}, slots),
    );
    if (full) node.classList.add('bladder-full');
    return node;
}

export function cupVessel(cup, index, { onclick, mini = false, live = false } = {}) {
    const slots = [];
    for (let i = 4; i >= 0; i--) {
        const ing = cup.ingredients[i];
        slots.push(el('span.cup-slot', {}, ing ? token(ing, { size: mini ? 'xs' : 'sm' }) : null));
    }
    const contents = cup.ingredients.map((i) => ING[i]?.label ?? i).join(', ') || 'empty';
    const node = el(onclick ? 'button.cup' : 'div.cup', {
        onclick,
        'data-cup': String(index),
        'aria-label': `Cup ${index + 1}: ${contents}${cup.has_cup_doubler ? ', doubles points' : ''}${onclick ? ' — tap for actions' : ''}`,
    },
        el('span.cup-glass', {}, slots),
        el('span.cup-label', {},
            `Cup ${index + 1}`,
            cup.has_cup_doubler ? el('span.cup-doubler-badge', { text: '×2', title: 'Cup doubler: non-cocktail sales score double' }) : null,
        ),
    );
    if (mini) node.classList.add('cup-mini');
    if (live) node.classList.add('cup-live');
    return node;
}

// ─── Board sections ──────────────────────────────────────────────────────────

export function renderOpponents(container, state, ctx) {
    const chips = state.turn_order
        .filter((pid) => pid !== ctx.meId)
        .map((pid) => {
            const ps = state.player_states[pid];
            const isTurn = state.player_turn === pid;
            const chip = el('button.opp-chip', {
                onclick: () => ctx.on.opponentTap(pid),
                'data-player': pid,
                'aria-label': `${ctx.nameOf(pid)}: ${ps.points} points, drunk level ${ps.drunk_level} — tap for details`,
            },
                el('span.opp-name', { text: ctx.nameOf(pid) }),
                el('span.opp-stats', {},
                    el('span.opp-stat', { text: `⭐${ps.points}` }),
                    el('span.opp-stat', { text: `🍺${ps.drunk_level}` }),
                    el('span.opp-stat', { text: `💧${ps.bladder.length}/${ps.bladder_capacity}` }),
                    ps.karaoke_cards_claimed ? el('span.opp-stat', { text: `🎤${ps.karaoke_cards_claimed}` }) : null,
                ),
                ps.status !== 'active' ? el('span.opp-out', { text: STATUS_LABELS[ps.status] ?? 'Out' }) : null,
            );
            if (isTurn) chip.classList.add('is-turn');
            if (ps.status !== 'active') chip.classList.add('is-out');
            return chip;
        });
    container.replaceChildren(...chips);
}

export function renderCardRows(container, state, ctx) {
    const rows = state.card_rows.map((row) => {
        const claimableIds = ctx.claimableCardIds ?? new Set();
        const cards = row.cards.map((card) =>
            cardFace(card, {
                claimable: claimableIds.has(card.id),
                onclick: ctx.readOnly ? undefined : () => ctx.on.cardTap(card),
            }));
        while (cards.length < 3) cards.push(el('div.card.card-empty', { 'aria-label': 'Empty card slot' }, el('span.card-icon', { text: '·' })));
        const canRefresh = !ctx.readOnly && (ctx.refreshableRows ?? new Set()).has(row.position);
        return el('div.card-row', { 'data-row': String(row.position) },
            el('span.card-row-tag', {},
                row.position === 1 ? el('span', { text: '🎤', title: 'Karaoke row — never refreshed', 'aria-hidden': 'true' }) : el('span', { text: String(row.position), 'aria-hidden': 'true' }),
                canRefresh
                    ? el('button.row-refresh', { onclick: () => ctx.on.rowRefresh(row.position), 'aria-label': `Refresh card row ${row.position}`, text: '🔄' })
                    : null,
            ),
            el('div.card-row-cards', {}, cards),
        );
    });
    container.replaceChildren(...rows);
}

export function renderMarket(container, state, ctx) {
    const canTake = !ctx.readOnly && ctx.canTakeNow;
    const tokens = state.open_display.map((name, i) =>
        el('span.market-slot', { 'data-slot': String(i) },
            token(name, {
                onclick: canTake ? (ev) => ctx.on.displayTokenTap(name, ev.currentTarget) : undefined,
                highlight: canTake,
            })));
    const bag = el(canTake ? 'button.bag' : 'div.bag', {
        id: 'bagChip',
        onclick: canTake ? (ev) => ctx.on.bagTap(ev.currentTarget) : undefined,
        'aria-label': `Ingredient bag, ${state.bag_contents.length} inside${canTake ? ' — tap to draw blind' : ''}`,
    },
        el('span.bag-icon', { text: '🎒', 'aria-hidden': 'true' }),
        el('span.bag-count', { text: String(state.bag_contents.length) }),
    );
    if (canTake) bag.classList.add('bag-live');
    container.replaceChildren(el('div.market-tokens', {}, tokens), bag);
}

function myClaimedCards(ps, ctx) {
    if (!ps.cards.length) return null;
    const items = ps.cards.map((cd, index) => {
        const type = CARD_TYPES[cd.card_type] ?? { icon: '❓', title: cd.card_type };
        const stored = cd.card_type === 'store' ? (cd.stored_spirits ?? []) : [];
        const tappable = !ctx.readOnly && cd.card_type === 'store' && stored.length > 0;
        return el(tappable ? 'button.my-card' : 'span.my-card', {
            onclick: tappable ? () => ctx.on.myStoreCardTap(cd, index) : undefined,
            title: `${cd.name} (${type.title})`,
            'aria-label': `${cd.name}${stored.length ? `, holds ${stored.length} spirits` : ''}${tappable ? ' — tap to use' : ''}`,
        },
            el('span', { text: type.icon, 'aria-hidden': 'true' }),
            el('span.my-card-name', { text: cd.name }),
            stored.length ? el('span.my-card-stored', {}, stored.map((s) => token(s, { size: 'xs' }))) : null,
        );
    });
    return el('div.my-cards', { 'aria-label': 'Your claimed cards' }, items);
}

export function renderMat(container, state, ctx) {
    const ps = state.player_states[ctx.meId];
    if (!ps) {
        container.replaceChildren();
        return;
    }
    const canWee = !ctx.readOnly && ctx.availableTypes?.has('go_for_a_wee');
    const canSpecials = !ctx.readOnly && ctx.availableTypes?.has('reroll_specials');
    const cupTappable = (i) => !ctx.readOnly && !ctx.takeInProgress && ctx.myTurn && !state.player_states[ctx.meId].cups[i].is_empty;

    const specials = el(canSpecials ? 'button.specials' : 'div.specials', {
        onclick: canSpecials ? () => ctx.on.specialsTap() : undefined,
        'aria-label': ps.special_ingredients.length
            ? `Your specials: ${ps.special_ingredients.join(', ')}${canSpecials ? ' — tap to re-roll' : ''}`
            : 'No special ingredients yet',
    },
        el('span.meter-label', { text: '🎲', 'aria-hidden': 'true' }),
        ps.special_ingredients.length
            ? el('span.specials-chips', {}, ps.special_ingredients.map((s) => specialChip(s)))
            : el('span.specials-empty', { text: 'no specials' }),
    );

    container.replaceChildren(...[
        el('div.mat-meters', {},
            drunkMeter(ps.drunk_level, ps.take_count),
            bladderRow(ps, { onclick: canWee ? () => ctx.on.bladderTap() : undefined }),
            specials,
        ),
        el('div.mat-cups', {},
            cupVessel(ps.cups[0], 0, { onclick: cupTappable(0) ? () => ctx.on.cupTap(0) : undefined, live: cupTappable(0) }),
            cupVessel(ps.cups[1], 1, { onclick: cupTappable(1) ? () => ctx.on.cupTap(1) : undefined, live: cupTappable(1) }),
        ),
        myClaimedCards(ps, ctx),
    ].filter(Boolean));
}

// ─── Action dock ─────────────────────────────────────────────────────────────

const DOCK_ACTIONS = [
    { type: 'take_ingredients', icon: '🫳', label: 'Take' },
    { type: 'sell_cup', icon: '💰', label: 'Sell' },
    { type: 'drink_cup', icon: '🍹', label: 'Drink' },
    { type: 'go_for_a_wee', icon: '🚽', label: 'Wee' },
    { type: 'claim_card', icon: '🃏', label: 'Claim' },
    { type: 'reroll_specials', icon: '🎲', label: 'Re-roll' },
    { type: 'refresh_card_row', icon: '🔄', label: 'Refresh' },
];

export function renderDock(container, state, ctx) {
    if (ctx.readOnly) {
        container.replaceChildren();
        return;
    }
    const ps = state.player_states[ctx.meId];

    if (state.winner) {
        container.replaceChildren(el('div.dock-msg.dock-winner', {
            text: state.winner === ctx.meId ? '🏆 You won!' : `🏆 ${ctx.nameOf(state.winner)} won!`,
        }));
        return;
    }
    if (ps?.is_eliminated || (ps && ps.status !== 'active')) {
        container.replaceChildren(el('div.dock-msg', { text: `You're out — ${STATUS_LABELS[ps.status] ?? ''}` }));
        return;
    }
    if (!ctx.myTurn) {
        container.replaceChildren(el('div.dock-msg', {},
            el('span.waiting-dots', { 'aria-hidden': 'true' }),
            el('span', { text: `${ctx.nameOf(state.player_turn)} is at the bar…` }),
        ));
        return;
    }
    if (ctx.takeInProgress) {
        const remaining = ps.take_count - state.ingredients_taken_this_turn;
        container.replaceChildren(el('div.dock-msg.dock-take', {
            text: `Take ${remaining} more — tap a face-up ingredient or the bag`,
        }));
        return;
    }

    const buttons = [];
    for (const def of DOCK_ACTIONS) {
        const info = ctx.availableTypes?.get(def.type);
        if (!info) continue;
        buttons.push(el('button.dock-btn', {
            onclick: () => ctx.on.dockAction(def.type),
            'aria-label': `${def.label}${info.is_free ? ' (free action)' : ''}`,
        },
            el('span.dock-btn-icon', { text: def.icon, 'aria-hidden': 'true' }),
            el('span.dock-btn-label', { text: def.label }),
            info.is_free ? el('span.dock-free', { text: '⚡ free', title: 'Free action — does not use your turn' }) : null,
        ));
    }
    if (ctx.canEndTurn) {
        buttons.push(el('button.dock-btn.dock-end', {
            onclick: () => ctx.on.dockAction('end_turn'),
            'aria-label': 'End turn',
        },
            el('span.dock-btn-icon', { text: '⏭️', 'aria-hidden': 'true' }),
            el('span.dock-btn-label', { text: 'End turn' }),
        ));
    }
    // Store-card free actions surface via the cards themselves; hint when they exist
    if (!buttons.length) {
        container.replaceChildren(el('div.dock-msg', { text: 'No actions available' }));
        return;
    }
    container.replaceChildren(
        el('div.dock-prompt', { text: 'Your turn — pick an action', 'aria-live': 'polite' }),
        el('div.dock-btns', {}, buttons),
    );
}
