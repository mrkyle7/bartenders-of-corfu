// Bar Top view — what's in the box: ingredient tokens, special dice faces,
// the cocktail menu, card wording and the house rules. Pure data, no DOM.

export const SPIRITS = ['WHISKEY', 'RUM', 'VODKA', 'GIN', 'TEQUILA'];
export const MIXERS = ['COLA', 'SODA', 'TONIC', 'CRANBERRY'];

// Every token carries a picture (and its name, when big enough) so colour is
// never the only clue.
export const ING = {
    WHISKEY: { label: 'Whisky', kind: 'spirit' },
    RUM: { label: 'Rum', kind: 'spirit' },
    VODKA: { label: 'Vodka', kind: 'spirit' },
    GIN: { label: 'Gin', kind: 'spirit' },
    TEQUILA: { label: 'Tequila', kind: 'spirit' },
    COLA: { label: 'Cola', kind: 'mixer' },
    SODA: { label: 'Soda water', kind: 'mixer' },
    TONIC: { label: 'Tonic water', kind: 'mixer' },
    CRANBERRY: { label: 'Cranberry', kind: 'mixer' },
    SPECIAL: { label: 'Special die', kind: 'special' },
    // Specials: tokens in the bag like any other; `special` is their recipe name.
    BITTERS: { label: 'Bitters', kind: 'special', special: 'bitters' },
    COINTREAU: { label: 'Cointreau', kind: 'special', special: 'cointreau' },
    LEMON: { label: 'Lemon', kind: 'special', special: 'lemon' },
    SUGAR: { label: 'Sugar', kind: 'special', special: 'sugar' },
    VERMOUTH: { label: 'Vermouth', kind: 'special', special: 'vermouth' },
};

// A special ingredient token (not the old special die).
export const isSpecial = (name) => !!ING[name]?.special;
// Drunk, these specials count like a spirit; lemon and sugar like a mixer.
export const BOOZY = ['BITTERS', 'COINTREAU', 'VERMOUTH'];
// One of these pays for the specialist card of that spirit.
export const SPECIALIST_SPECIAL = { WHISKEY: 'BITTERS', TEQUILA: 'COINTREAU', VODKA: 'VERMOUTH', RUM: 'SUGAR', GIN: 'LEMON' };
// Max specials that sit in one glass, on top of its five spirits and mixers.
export const GLASS_SPECIALS = 2;

// A glass split into its spirits and mixers and the specials in it.
export function splitGlass(cup) {
    return {
        base: cup.filter((i) => !isSpecial(i)),
        specials: cup.filter(isSpecial).map((i) => ING[i].special),
    };
}

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

// What a sold cup would be called, for sell buttons and the log. Specials
// can be in the glass, or declared from the mat in older games.
export function drinkName(glass, declared = []) {
    const { base: cup, specials: inGlass } = splitGlass(glass);
    const specials = [...declared, ...inGlass];
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
    order: { label: 'Order', points: 0 },
};

// The ingredients an order asks for (tokens) and the specials it needs.
export function orderRecipe(card) {
    if (card.drink === 'simple') return { cup: [card.spirit_type, card.mixer_type], specials: [] };
    if (card.drink === 'slammer') return { cup: ['TEQUILA', 'TEQUILA'], specials: [] };
    const c = COCKTAILS.find((x) => x.name === card.cocktail);
    return c ? { cup: c.cup, specials: c.specials } : { cup: [], specials: [] };
}

// Whether a glass (and the specials declared) would serve this order.
export function servesOrder(card, cup, specials = []) {
    const name = drinkName(cup, specials);
    if (card.drink === 'cocktail') return name === card.cocktail;
    const spirits = [...new Set(cup.filter((i) => ING[i]?.kind === 'spirit'))];
    const mixers = [...new Set(cup.filter((i) => ING[i]?.kind === 'mixer'))];
    if (COCKTAILS.some((c) => c.name === name)) return false;
    if (cup.some(isSpecial) || specials.length) return false; // not a cocktail, so not sellable
    if (card.drink === 'slammer') return name === 'Tequila Slammer';
    return spirits.length === 1 && spirits[0] === card.spirit_type
        && mixers.length === 1 && mixers[0] === card.mixer_type
        && cup.filter((i) => ING[i]?.kind === 'spirit').length <= 2;
}

const FREE_ACTION_TEXT = {
    take_ingredients: 'Take ingredients a second time every turn.',
    reroll_specials: 'Re-roll your specials for free every turn.',
    sell_cup: 'Selling is free: sell, then take a main action too or end your turn.',
    go_for_a_wee: 'Go for a free wee every turn.',
};

export function cardText(card) {
    const spirit = ING[card.spirit_type]?.label;
    const mixer = ING[card.mixer_type]?.label;
    switch (card.card_type) {
        case 'karaoke': return 'Sing when you’re drunk 3 or more. Three songs and you win on the spot.';
        case 'store': return `Keeps your ${spirit} out of your bladder. Pour it or drink it whenever you like.`;
        case 'refresher': return `Every ${mixer} you drink sobers you up by one, even with spirits.`;
        case 'cup_doubler': return 'Goes on one glass for good: drinks from it score double (not cocktails).';
        case 'specialist': return `+2 points on every drink with ${spirit} in it (not cocktails). Pay 2 ${spirit} or 1 ${ING[SPECIALIST_SPECIAL[card.spirit_type]]?.label ?? 'special'}.`;
        case 'free_action': return FREE_ACTION_TEXT[card.free_action_type] ?? 'A free extra action every turn.';
        case 'order':
            if (card.drink === 'simple') return `Serve a ${card.name}, single or double, for +${card.bonus} on top.`;
            return `Serve a ${card.name} for +${card.bonus} on top.`;
        default: return '';
    }
}

// What must be in your bladder to claim a card: a list of token names, where
// 'ANY_SPIRIT' means three of one spirit of your choice.
export function cardCost(card) {
    switch (card.card_type) {
        case 'karaoke': return Array(2).fill(card.spirit_type); // and drunk 3+
        case 'free_action': return Array(3).fill(card.spirit_type);
        case 'store': return [card.spirit_type];
        case 'specialist': return Array(2).fill(card.spirit_type);
        case 'refresher': return Array(2).fill(card.mixer_type);
        case 'cup_doubler': return Array(3).fill('ANY_SPIRIT');
        case 'order': return orderRecipe(card).cup;
        default: return [];
    }
}

// Optional house rules offered in the lobby (none at the moment).
export const MODES = {};

// The drunk track, sober to stretcher.
export const DRUNK_LABELS = ['Sober', 'Merry', 'Tipsy', 'Squiffy', 'Sozzled', 'Legless'];

// Free actions by the name the server uses for them.
export const FREE_ACTIONS = {
    claim_card: 'Claim a card',
    refresh_orders_row: 'Clear the orders',
    refresh_ability_row: 'Swipe the abilities',
    take_ingredients: 'Take again',
    sell_cup: 'Sell (free)',
    go_for_a_wee: 'A free wee',
};

// The rule book shown on the table. Keep in step with "Game Rules.md".
export const RULES = [
    {
        title: 'Winning',
        items: [
            'Reach the target to start the last round: 40 points with two players, 35 with three, 30 with four. The round finishes so everyone has had the same number of turns, then the most points wins (a tie goes to whoever is earliest in turn order).',
            'Sing three karaoke songs and you win on the spot, even in the last round. A song needs drunk 3 or more and 2 of its spirit in your bladder.',
            'Last one standing wins when everyone else is in hospital, wet or gone home.',
        ],
    },
    {
        title: 'Your turn',
        items: [
            'One main action: take ingredients, sell your glasses (one or both), drink a glass, or go for a wee.',
            'Free actions, each once a turn, before or after: claim a card, clear the orders (drunk 3 or more), swipe the ability cards (drunk 2 or more), and whatever your free-action cards give you. Pouring or drinking from a Store card is free too.',
            'Your turn ends when your main action is done and there is nothing free left you could use. You can end it early after your main action.',
        ],
    },
    {
        title: 'Taking ingredients',
        items: [
            'Take exactly 3 plus your drunk level, from the display, the specials tray, blind from the bag, or any mix.',
            'Put each one in a glass (five spirits and mixers at most) or drink it before you take more. Nothing goes back.',
            'Your drunk level changes once, after the whole take: +1 per spirit, bitters, cointreau or vermouth drunk; if you drank none of those, −1 per mixer, lemon or sugar.',
        ],
    },
    {
        title: 'Specials',
        items: [
            'There are two each of bitters, cointreau, lemon, sugar and vermouth in the bag. Whenever one comes out, it goes to the specials tray and the drawing carries on, so the display always shows five spirits and mixers and a blind draw never hands you a special.',
            'Anyone can take specials from the tray as part of their take. A special goes straight into a glass, up to two per glass on top of its five spirits and mixers, or you drink it.',
            'A glass with a special in it only sells as the cocktail it makes. Drink one to stop others getting it: lemon and sugar sober you like a mixer, bitters, cointreau and vermouth get you drunk like a spirit.',
            'Specials never count toward a card, except that one pays for a specialist: bitters for whisky, cointreau for tequila, vermouth for vodka, sugar for rum, lemon for gin.',
        ],
    },
    {
        title: 'Selling',
        items: [
            'One spirit with one kind of mixer: 1 point. Two of the same spirit with one kind of mixer: 3. Tequila slammer (two tequila, nothing else): 3.',
            'Cocktails score 10 (Long Island Iced Tea 15) and must match the recipe exactly, specials included.',
            'If an order on the table wants your drink, you also get its bonus: +2 simple drinks, +3 slammer, +4 cocktails, +5 Long Island. Bonuses aren’t doubled.',
        ],
    },
    {
        title: 'Drink, wee and limits',
        items: [
            'Everything you drink goes into your bladder. More than it holds and you’ve wet yourself; above drunk 5 it’s hospital. Either way you’re out.',
            'A wee empties your bladder into the bag and sobers you up by 1. Each wee seals a bladder space with a toilet token, down to 4 spaces.',
        ],
    },
    {
        title: 'Cards',
        items: [
            'Claiming pays the cost: those ingredients leave your bladder and go back in the bag. Stored spirits don’t count. A Store card pays one spirit and the rest of it moves onto the card.',
            'A karaoke song also needs you drunk 3 or more (checked, not paid). Karaoke cards are all out from the start and aren’t replaced. A claimed ability card is replaced from the deck.',
            'Clearing the orders (drunk 3 or more) or swiping the abilities (drunk 2 or more) is free, once a turn each. All three cards go to the bottom of their deck and three new ones are dealt. The karaoke row is never cleared.',
        ],
    },
];

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
                const got = SPECIALS[s.special_type]?.label;
                if (!got) bits.push(s.face ? 'left a special' : 'rolled a blank');
                else if (s.swapped) bits.push(`took ${got}, giving back ${SPECIALS[s.swapped]?.label ?? s.swapped}`);
                else bits.push(`took ${got}`);
            }
            return `${who} ${bits.join(', ') || 'took ingredients'}`;
        }
        case 'sell_cup': {
            const cups = a.sold_cups ?? [a];
            const drinks = cups.map((c) => drinkName(c.ingredients ?? [], c.declared_specials ?? [])).join(' and ');
            const orders = (a.orders ?? []).map((o) => o.name);
            return `${who} sold ${drinks} for ${a.points_earned} points${orders.length ? `, serving the ${orders.join(' and ')} order` : ''}`;
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
        case 'refresh_card_row':
            return a.row_position === 2 ? `${who} cleared the orders` : a.row_position === 3 ? `${who} swiped the ability cards` : `${who} cleared card row ${a.row_position}`;
        case 'end_turn': return `${who} ended their turn`;
        case 'quit_game': return `${who} left the bar`;
        case 'cancel_game': return 'The game was called off';
        case 'undo': return `${who} took back the last turn`;
        default: return `${who} made a move`;
    }
}
