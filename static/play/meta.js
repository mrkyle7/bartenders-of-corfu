// Game metadata for the Table View UI: ingredient tokens, card types,
// cocktail recipes and human-readable move descriptions.

export const SPIRITS = ['WHISKEY', 'GIN', 'RUM', 'TEQUILA', 'VODKA'];
export const MIXERS = ['COLA', 'SODA', 'TONIC', 'CRANBERRY'];

export const ING = {
    WHISKEY: { label: 'Whisky', short: 'Wh', kind: 'spirit', color: '#e8a33d', text: '#3a2405' },
    GIN: { label: 'Gin', short: 'Gn', kind: 'spirit', color: '#8fd8c5', text: '#0d3a30' },
    RUM: { label: 'Rum', short: 'Rm', kind: 'spirit', color: '#c9713a', text: '#3a1c05' },
    TEQUILA: { label: 'Tequila', short: 'Tq', kind: 'spirit', color: '#b7d05a', text: '#2c3305' },
    VODKA: { label: 'Vodka', short: 'Vk', kind: 'spirit', color: '#bdd7f2', text: '#122a42' },
    COLA: { label: 'Cola', short: 'Co', kind: 'mixer', color: '#9c6644', text: '#2b1608' },
    SODA: { label: 'Soda', short: 'So', kind: 'mixer', color: '#d7dde2', text: '#26303a' },
    TONIC: { label: 'Tonic', short: 'To', kind: 'mixer', color: '#a9c3e8', text: '#16283f' },
    CRANBERRY: { label: 'Cranberry', short: 'Cr', kind: 'mixer', color: '#d9536a', text: '#3a0710' },
    SPECIAL: { label: 'Special die', short: '?', kind: 'special', color: '#b48be0', text: '#2a0d47' },
};

export const SPECIAL_TYPES = {
    bitters: { label: 'Bitters', icon: '🌿' },
    cointreau: { label: 'Cointreau', icon: '🍊' },
    lemon: { label: 'Lemon', icon: '🍋' },
    sugar: { label: 'Sugar', icon: '🧂' },
    vermouth: { label: 'Vermouth', icon: '🍶' },
};

export const CARD_TYPES = {
    karaoke: {
        icon: '🎤',
        title: 'Karaoke',
        cost: (c) => `3× ${ING[c.spirit_type]?.label ?? 'spirit'} drunk`,
        effect: () => '+5 points. Claim 3 karaoke cards to win instantly!',
    },
    store: {
        icon: '🛢️',
        title: 'Store',
        cost: (c) => `1× ${ING[c.spirit_type]?.label ?? 'spirit'} drunk`,
        effect: (c) => `+1 point. Moves all ${ING[c.spirit_type]?.label ?? ''} out of your bladder onto this card — drink or pour them later as a free action.`,
    },
    refresher: {
        icon: '🧊',
        title: 'Refresher',
        cost: (c) => `2× ${ING[c.mixer_type]?.label ?? 'mixer'} drunk`,
        effect: (c) => `+1 point. Drinking ${ING[c.mixer_type]?.label ?? 'this mixer'} now always sobers you up, even alongside spirits.`,
    },
    cup_doubler: {
        icon: '🥤',
        title: 'Cup doubler',
        cost: () => '3× same spirit drunk',
        effect: () => '+2 points. One of your cups scores double on every non-cocktail sale.',
    },
    specialist: {
        icon: '⭐',
        title: 'Specialist',
        cost: (c) => `2× ${ING[c.spirit_type]?.label ?? 'spirit'} drunk`,
        effect: (c) => `+2 points. +2 bonus points whenever you sell a drink containing ${ING[c.spirit_type]?.label ?? 'that spirit'}.`,
    },
    free_action: {
        icon: '⚡',
        title: 'Free action',
        cost: (c) => `3× ${ING[c.spirit_type]?.label ?? 'spirit'} drunk`,
        effect: (c) => `+2 points. ${FREE_ACTION_LABELS[c.free_action_type] ?? 'An action'} becomes a free extra action every turn.`,
    },
};

export const FREE_ACTION_LABELS = {
    take_ingredients: 'Taking ingredients',
    sell_cup: 'Selling a cup',
    go_for_a_wee: 'Going for a wee',
    reroll_specials: 'Re-rolling specials',
    claim_card: 'Claiming a card',
};

// Cocktail recipes for naming a sale in banners / sell sheets.
// counts: ingredient name -> count, specials: special value -> count
const COCKTAILS = [
    { name: 'Long Island Iced Tea', pts: 15, ings: { GIN: 1, VODKA: 1, TEQUILA: 1, RUM: 1, COLA: 1 }, specials: { sugar: 1, lemon: 1 } },
    { name: 'Mojito', pts: 10, ings: { RUM: 2, SODA: 1 }, specials: { sugar: 1 } },
    { name: 'Old Fashioned', pts: 10, ings: { WHISKEY: 3 }, specials: { bitters: 1 } },
    { name: 'Margarita', pts: 10, ings: { TEQUILA: 2 }, specials: { cointreau: 1, lemon: 1 } },
    { name: 'Cosmopolitan', pts: 10, ings: { VODKA: 1, CRANBERRY: 1 }, specials: { cointreau: 1, lemon: 1 } },
    { name: 'Gin Martini', pts: 10, ings: { GIN: 3 }, specials: { vermouth: 1 } },
    { name: 'Vodka Martini', pts: 10, ings: { VODKA: 3 }, specials: { vermouth: 1 } },
    { name: 'Tom Collins', pts: 10, ings: { GIN: 1, SODA: 1 }, specials: { lemon: 1, sugar: 1 } },
    { name: 'Manhattan', pts: 10, ings: { WHISKEY: 2 }, specials: { vermouth: 1, bitters: 1 } },
];

function counts(list) {
    const c = {};
    for (const x of list) c[x] = (c[x] ?? 0) + 1;
    return c;
}

function sameCounts(a, b) {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const k of keys) if ((a[k] ?? 0) !== (b[k] ?? 0)) return false;
    return true;
}

// Name the drink a cup+specials combination sells as, e.g. "Mojito" or
// "Double whisky & cola". Only called for combinations the server already
// validated as sellable, so unknown shapes fall back to a generic label.
export function drinkName(ingredients, declaredSpecials) {
    const ingCounts = counts(ingredients);
    const spCounts = counts(declaredSpecials);
    for (const r of COCKTAILS) {
        if (sameCounts(ingCounts, r.ings) && sameCounts(spCounts, r.specials)) return r.name;
    }
    const spirits = ingredients.filter((i) => ING[i]?.kind === 'spirit');
    const mixers = ingredients.filter((i) => ING[i]?.kind === 'mixer');
    if (spirits.length === 2 && spirits[0] === 'TEQUILA' && spirits[1] === 'TEQUILA' && mixers.length === 0) {
        return 'Tequila Slammer';
    }
    const spiritLabel = ING[spirits[0]]?.label ?? 'Drink';
    const mixerLabel = mixers.length ? ` & ${ING[mixers[0]]?.label.toLowerCase()}` : '';
    return `${spirits.length === 2 ? 'Double ' : ''}${spiritLabel}${mixerLabel}`;
}

function ingredientList(names) {
    return (names ?? []).map((n) => ING[n]?.label ?? n).join(', ');
}

// Human-readable one-liner for a move record from /history.
export function describeMove(move, nameOf) {
    const a = move.action ?? {};
    const who = nameOf(move.player_id);
    switch (a.type) {
        case 'draw_from_bag':
            return `${who} drew ${a.drawn?.length ?? '?'} from the bag`;
        case 'take_ingredients': {
            const taken = a.taken ?? [];
            const toCups = taken.filter((t) => t.disposition === 'cup');
            const drunk = taken.filter((t) => t.disposition === 'drink');
            const specials = taken.filter((t) => t.disposition === 'special');
            const bits = [];
            if (toCups.length) bits.push(`poured ${ingredientList(toCups.map((t) => t.ingredient))}`);
            if (drunk.length) bits.push(`drank ${ingredientList(drunk.map((t) => t.ingredient))}`);
            for (const s of specials) {
                bits.push(s.special_type === 'nothing' ? 'rolled the special die… nothing!' : `rolled ${SPECIAL_TYPES[s.special_type]?.label ?? s.special_type}`);
            }
            return `${who} ${bits.join(', ') || 'took ingredients'}`;
        }
        case 'sell_cup': {
            const cups = a.sold_cups ?? [a];
            const names = cups.map((c) => drinkName(c.ingredients ?? [], c.declared_specials ?? [])).join(' + ');
            return `${who} sold ${names} for ${a.points_earned} pts 🍹`;
        }
        case 'drink_cup':
            return `${who} drank a whole cup: ${ingredientList(a.ingredients)}`;
        case 'go_for_a_wee':
            return `${who} went for a wee 🚽 (flushed ${a.excreted?.length ?? 0})`;
        case 'claim_card':
            return `${who} claimed ${a.card_name} ${CARD_TYPES[a.card_type]?.icon ?? ''}`;
        case 'drink_stored_spirit':
            return `${who} drank ${a.count}× ${ING[a.spirit_type]?.label ?? a.spirit_type} from their store`;
        case 'use_stored_spirit':
            return `${who} poured a stored ${ING[a.spirit_type]?.label ?? a.spirit_type} into a cup`;
        case 'reroll_specials': {
            const got = (a.results ?? []).map((r) => (r ? (SPECIAL_TYPES[r]?.label ?? r) : 'nothing'));
            return `${who} re-rolled specials → ${got.join(', ')}`;
        }
        case 'refresh_card_row':
            return `${who} refreshed card row ${a.row_position}`;
        case 'end_turn':
            return `${who} ended their turn`;
        case 'quit_game':
            return `${who} left the game`;
        case 'cancel_game':
            return 'The game was cancelled';
        case 'undo':
            return `${who} rolled the game back a turn`;
        default:
            return `${who} did something (${a.type})`;
    }
}

export const MOVE_ICONS = {
    draw_from_bag: '🎒',
    take_ingredients: '🫳',
    sell_cup: '💰',
    drink_cup: '🍹',
    go_for_a_wee: '🚽',
    claim_card: '🃏',
    drink_stored_spirit: '🥃',
    use_stored_spirit: '🫗',
    reroll_specials: '🎲',
    refresh_card_row: '🔄',
    end_turn: '⏭️',
    quit_game: '🚪',
    cancel_game: '❌',
    undo: '↩️',
};

export const STATUS_LABELS = {
    active: '',
    hospitalised: '🏥 In hospital',
    wet: '💦 Wet themselves',
    quit: '🚪 Left the game',
};
