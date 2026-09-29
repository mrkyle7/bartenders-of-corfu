// Bar Top view — what's in the box: ingredient tokens, special dice faces,
// the cocktail menu, card wording and the house rules. Pure data, no DOM.

export const SPIRITS = ['WHISKEY', 'RUM', 'VODKA', 'GIN', 'TEQUILA'];
export const MIXERS = ['COLA', 'SODA', 'TONIC', 'CRANBERRY'];

// Spirits are round wooden discs, mixers square tiles, specials a purple die.
// Every token carries a short mark so colour is never the only clue.
export const ING = {
    WHISKEY: { label: 'Whisky', mark: 'Wh', kind: 'spirit' },
    RUM: { label: 'Rum', mark: 'Ru', kind: 'spirit' },
    VODKA: { label: 'Vodka', mark: 'Vo', kind: 'spirit' },
    GIN: { label: 'Gin', mark: 'Gi', kind: 'spirit' },
    TEQUILA: { label: 'Tequila', mark: 'Te', kind: 'spirit' },
    COLA: { label: 'Cola', mark: 'Co', kind: 'mixer' },
    SODA: { label: 'Soda water', mark: 'So', kind: 'mixer' },
    TONIC: { label: 'Tonic water', mark: 'To', kind: 'mixer' },
    CRANBERRY: { label: 'Cranberry', mark: 'Cr', kind: 'mixer' },
    SPECIAL: { label: 'Special die', mark: '?', kind: 'special' },
};

export const SPECIALS = {
    bitters: { label: 'Bitters' },
    cointreau: { label: 'Cointreau' },
    lemon: { label: 'Lemon' },
    sugar: { label: 'Sugar' },
    vermouth: { label: 'Vermouth' },
};

// Which mixers each spirit can be sold with (tequila only as a slammer).
export const PAIRINGS = {
    VODKA: ['COLA', 'SODA', 'TONIC', 'CRANBERRY'],
    RUM: ['COLA'],
    WHISKEY: ['COLA', 'SODA'],
    GIN: ['TONIC'],
    TEQUILA: [],
};

export const COCKTAILS = [
    { name: 'Mojito', cup: ['RUM', 'RUM', 'SODA'], specials: ['sugar'], points: 10 },
    { name: 'Old Fashioned', cup: ['WHISKEY', 'WHISKEY', 'WHISKEY'], specials: ['bitters'], points: 10 },
    { name: 'Margarita', cup: ['TEQUILA', 'TEQUILA'], specials: ['cointreau', 'lemon'], points: 10 },
    { name: 'Cosmopolitan', cup: ['VODKA', 'CRANBERRY'], specials: ['cointreau', 'lemon'], points: 10 },
    { name: 'Gin Martini', cup: ['GIN', 'GIN', 'GIN'], specials: ['vermouth'], points: 10 },
    { name: 'Vodka Martini', cup: ['VODKA', 'VODKA', 'VODKA'], specials: ['vermouth'], points: 10 },
    { name: 'Tom Collins', cup: ['GIN', 'SODA'], specials: ['lemon', 'sugar'], points: 10 },
    { name: 'Manhattan', cup: ['WHISKEY', 'WHISKEY'], specials: ['vermouth', 'bitters'], points: 10 },
    { name: 'Long Island Iced Tea', cup: ['GIN', 'VODKA', 'TEQUILA', 'RUM', 'COLA'], specials: ['sugar', 'lemon'], points: 15 },
];

const sameBag = (a, b) => a.length === b.length && [...a].sort().join() === [...b].sort().join();

// What a sold cup would be called, for sell buttons and the log.
export function drinkName(cup, specials = []) {
    const cocktail = COCKTAILS.find((c) => sameBag(c.cup, cup) && sameBag(c.specials, specials));
    if (cocktail) return cocktail.name;
    const spirits = cup.filter((i) => ING[i]?.kind === 'spirit');
    const mixers = cup.filter((i) => ING[i]?.kind === 'mixer');
    if (spirits.length === 2 && spirits.every((s) => s === 'TEQUILA') && !mixers.length) return 'Tequila Slammer';
    if (!spirits.length) return 'a drink';
    const spirit = ING[spirits[0]].label;
    const mixer = mixers.length ? ` and ${ING[mixers[0]].label.replace(' water', '')}` : '';
    return `${spirits.length === 2 ? 'Double ' : ''}${spirit}${mixer}`;
}

export const CARD_KINDS = {
    karaoke: { label: 'Karaoke', points: 5 },
    store: { label: 'Store', points: 1 },
    refresher: { label: 'Refresher', points: 1 },
    cup_doubler: { label: 'Doubler', points: 2 },
    specialist: { label: 'Specialist', points: 2 },
    free_action: { label: 'Free action', points: 2 },
};

const FREE_ACTION_TEXT = {
    take_ingredients: 'Take ingredients a second time every turn.',
    reroll_specials: 'Re-roll your specials for free every turn.',
    sell_cup: 'Sell a second cup every turn.',
    go_for_a_wee: 'Go for a free wee every turn.',
};

export function cardText(card) {
    const spirit = ING[card.spirit_type]?.label;
    const mixer = ING[card.mixer_type]?.label;
    switch (card.card_type) {
        case 'karaoke': return 'Sing three karaoke songs and you win on the spot.';
        case 'store': return `Keeps your ${spirit} out of your bladder. Pour it or drink it whenever you like.`;
        case 'refresher': return `Every ${mixer} you drink sobers you up by one, even with spirits.`;
        case 'cup_doubler': return 'Goes on one glass for good: drinks from it score double (not cocktails).';
        case 'specialist': return `+2 points on every drink with ${spirit} in it (not cocktails).`;
        case 'free_action': return FREE_ACTION_TEXT[card.free_action_type] ?? 'A free extra action every turn.';
        default: return '';
    }
}

// What must be in your bladder to claim a card: a list of token names, where
// 'ANY_SPIRIT' means three of one spirit of your choice.
export function cardCost(card) {
    switch (card.card_type) {
        case 'karaoke':
        case 'free_action': return Array(3).fill(card.spirit_type);
        case 'store': return [card.spirit_type];
        case 'specialist': return Array(2).fill(card.spirit_type);
        case 'refresher': return Array(2).fill(card.mixer_type);
        case 'cup_doubler': return Array(3).fill('ANY_SPIRIT');
        default: return [];
    }
}

export const MODES = {
    sell_both_cups: { label: 'Sell both cups', desc: 'Sell both glasses in one action.' },
    claim_card_free_action: { label: 'Free card claims', desc: 'Claiming a card doesn’t use your action.' },
    reroll_specials_free_action: { label: 'Free re-rolls', desc: 'Re-rolling specials doesn’t use your action.' },
};

// One pawn colour per seat, in turn order.
export const SEAT_COLOURS = ['#e0452b', '#2f8fdb', '#3fae5a', '#f2c230'];

const list = (names) => {
    const counts = {};
    for (const n of names ?? []) counts[n] = (counts[n] ?? 0) + 1;
    return Object.entries(counts)
        .map(([n, c]) => `${c > 1 ? `${c} ` : ''}${ING[n]?.label ?? n}`)
        .join(', ') || 'nothing';
};

export function describeMove(move, nameOf) {
    const a = move.action ?? {};
    const who = nameOf(move.player_id);
    switch (a.type) {
        case 'draw_from_bag': return `${who} drew ${a.drawn?.length ?? 'some'} from the bag`;
        case 'take_ingredients': {
            const taken = a.taken ?? [];
            const bits = [];
            const cups = taken.filter((t) => t.disposition === 'cup').map((t) => t.ingredient);
            const drunk = taken.filter((t) => t.disposition === 'drink').map((t) => t.ingredient);
            if (cups.length) bits.push(`poured ${list(cups)}`);
            if (drunk.length) bits.push(`drank ${list(drunk)}`);
            for (const s of taken.filter((t) => t.disposition === 'special')) {
                bits.push(s.special_type === 'nothing' ? 'rolled a blank' : `rolled ${SPECIALS[s.special_type]?.label ?? s.special_type}`);
            }
            return `${who} ${bits.join(', ') || 'took ingredients'}`;
        }
        case 'sell_cup': {
            const cups = a.sold_cups ?? [a];
            const drinks = cups.map((c) => drinkName(c.ingredients ?? [], c.declared_specials ?? [])).join(' and ');
            return `${who} sold ${drinks} for ${a.points_earned} points`;
        }
        case 'drink_cup': return `${who} downed a glass of ${list(a.ingredients)}`;
        case 'go_for_a_wee': return `${who} went for a wee`;
        case 'claim_card': return `${who} claimed ${a.card_name ?? 'a card'}`;
        case 'drink_stored_spirit': return `${who} drank ${a.count ?? 1} ${ING[a.spirit_type]?.label ?? 'spirit'} from their store`;
        case 'use_stored_spirit': return `${who} poured a stored ${ING[a.spirit_type]?.label ?? 'spirit'} into a glass`;
        case 'reroll_specials': {
            const got = (a.results ?? []).map((r) => (r ? (SPECIALS[r]?.label ?? r) : 'a blank'));
            return `${who} re-rolled and got ${got.join(', ') || 'nothing'}`;
        }
        case 'refresh_card_row': return `${who} cleared card row ${a.row_position}`;
        case 'end_turn': return `${who} ended their turn`;
        case 'quit_game': return `${who} left the bar`;
        case 'cancel_game': return 'The game was called off';
        case 'undo': return `${who} took back the last turn`;
        default: return `${who} made a move`;
    }
}
