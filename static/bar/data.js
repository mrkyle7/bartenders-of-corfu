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
    take_ingredients: 'Taking ingredients is free: take, then another main action or end your turn.',
    reroll_specials: 'Re-roll your specials for free every turn.',
    sell_cup: 'Selling is free: sell, then another main action or end your turn.',
    go_for_a_wee: 'Weeing is free: wee, then another main action or end your turn.',
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
    take_ingredients: 'Take (free)',
    sell_cup: 'Sell (free)',
    go_for_a_wee: 'Wee (free)',
};

// The rule book shown on the table. Keep in step with "Game Rules.md".
export const RULES_INTRO = 'You are a busy bartender in a bustling bar in Corfu. Make drinks and cocktails to sell to the thirsty punters quicker than your rivals to win! Bartending is thirsty work, so you\u2019ll sample your own drinks along the way. Just don\u2019t get too drunk, or you\u2019ll end up on a fast trip to the nearest hospital.';

export const RULES = [
    {
        title: 'How the night goes',
        items: [
            'Pour and serve: take ingredients into your two glasses and sell the drinks you make for points. Cocktails are worth the most, and punters’ orders pay a bonus on top.',
            'Drink on the job: whatever you don’t pour, you drink. It goes into your bladder, and your bladder is what you spend to claim cards that help you.',
            'Stay on your feet: every spirit you drink makes you drunker, and your bladder only holds so much. Too drunk and it’s hospital; too full and you’ve wet yourself. Either way, you’re out.',
            'Win by reaching the points target first, singing three karaoke songs, or being the last bartender standing (see Winning, at the end).',
        ],
    },
    {
        title: 'Behind the bar',
        items: [
            'The bag holds every ingredient: spirits, mixers, and two each of the purple specials (bitters, cointreau, lemon, sugar, vermouth).',
            'The open display shows five spirits and mixers for anyone to take. A special that comes out while refilling it goes to the specials tray, also for anyone.',
            'Three rows of cards: the five karaoke songs, three orders the punters are calling for, and three ability cards that help you.',
            'Your mat: two glasses, a bladder of 8 spaces, the drunk track and 4 toilet tokens.',
        ],
    },
    {
        title: 'Your turn',
        items: [
            'One main action: pour (take ingredients), serve (sell one or both glasses), drink a glass, or go for a wee.',
            'Free actions, each once a turn, before or after: claim a card, swipe the ability cards (drunk 2 or more), clear the orders (drunk 3 or more), and whatever your free-action cards give you. Pouring or drinking from a Store card is free too.',
            'Your turn ends when your main action is done and nothing free is left that you could use. You can end it early after your main action.',
        ],
    },
    {
        title: 'Pouring',
        lead: 'The punters are waiting. Grab what you need, and whatever doesn’t fit in a glass goes down the hatch.',
        items: [
            'Take exactly 3 plus your drunk level, from the display, the specials tray, blind from the bag, or any mix.',
            'Put each one in a glass or drink it before you take more. A glass holds five spirits and mixers, plus two specials on the rim. Nothing goes back, and a blind draw can hand you anything, specials included.',
            'Specials are for cocktails: a glass with one in it only sells as the cocktail it makes. You might drink one so a rival can’t have it, or to pay for a specialist.',
        ],
    },
    {
        title: 'Serving',
        lead: 'A punter’s waiting at the bar. Hand over the drink and take the money.',
        items: [
            'Sell one glass or both. One spirit with one kind of mixer: 1 point. Two of the same spirit with one kind of mixer: 3. Tequila slammer (two tequila, nothing else): 3.',
            'Cocktails score 10 (Long Island Iced Tea 15) and must match the recipe exactly, specials included. The Drinks menu lists them all.',
            'Serve a drink an order is calling for and you get its bonus too: +2 simple drinks, +3 slammer, +4 cocktails, +5 Long Island. Each glass serves one order; bonuses aren’t doubled.',
        ],
    },
    {
        title: 'Having a drink',
        lead: 'Bartending is thirsty work. A drink or two helps; too many and you’re off in an ambulance.',
        items: [
            'Drink ingredients as you take them, or a whole glass as your main action. Everything you drink goes into your bladder.',
            'After each action: +1 drunk for every spirit, bitters, cointreau or vermouth you drank. If you drank none of those, you sober up 1 for each mixer, lemon or sugar instead.',
            'The drunk track: 0 Sober, 1 Merry, 2 Tipsy, 3 Squiffy, 4 Sozzled, 5 Legless. Above 5 it’s hospital, and you’re out of the game.',
            'Being drunk has its uses: you take more ingredients each turn, can swipe the ability cards at drunk 2, and clear the orders or sing karaoke at drunk 3.',
        ],
    },
    {
        title: 'Nipping to the loo',
        lead: 'Once you break the seal, there’s no going back.',
        items: [
            'More in your bladder than it has spaces and you’ve wet yourself: you’re out of the game.',
            'A wee (main action) empties your bladder back into the bag and sobers you up by 1. Each wee seals a bladder space with a toilet token, down to 4 spaces.',
            'When you’re out, everything you held goes back in the bag for the others.',
        ],
    },
    {
        title: 'Cards',
        lead: 'What you’ve drunk pays for them.',
        items: [
            'Claim a card (free, once a turn) if your bladder holds its cost. Those ingredients leave your bladder and go back in the bag. Stored spirits and specials don’t count, except that one special pays for its specialist.',
            'Karaoke: get up and sing! A song needs 2 of its spirit and you drunk 3 or more (checked, not paid). Sing three and you win.',
            'Ability cards: Store (keep a spirit on the card to pour or drink later), Refresher (a mixer that always sobers you), Cup doubler (a glass that scores double), Specialist (+2 on drinks with its spirit), and free-action cards that make taking, selling or weeing free. The card says what it does.',
            'Free-action cards: that action becomes free, before or after your main action, still once a turn. Done first, it can stand in for your main action.',
            'Swiping the abilities (drunk 2 or more) or clearing the orders (drunk 3 or more) is free, once a turn each: all three go under their deck and three new ones are dealt. The karaoke row is never cleared.',
        ],
    },
    {
        title: 'Winning',
        items: [
            'Reach the target to start the last round: 40 points with two players, 35 with three, 30 with four. The round finishes so everyone has had the same number of turns, then the most points wins (a tie goes to whoever is earliest in turn order).',
            'Sing three karaoke songs and you win on the spot, even in the last round.',
            'Last one standing wins when everyone else is in hospital, wet or gone home.',
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
        case 'skip_turn': return `${who} had nothing they could do and passed`;
        case 'quit_game': return `${who} left the bar`;
        case 'cancel_game': return 'The game was called off';
        case 'undo': return `${who} took back the last turn`;
        default: return `${who} made a move`;
    }
}
