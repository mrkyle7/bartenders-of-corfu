/**
 * constants.js — Shared constants for Bartenders of Corfu.
 * Vanilla ES2022, no dependencies.
 */

export const SPIRITS = new Set(['WHISKEY','RUM','VODKA','GIN','TEQUILA']);
export const MIXERS  = new Set(['COLA','SODA','TONIC','CRANBERRY']);

export const INGREDIENT_LABELS = {
    WHISKEY:'Whiskey', WHISKY:'Whisky',
    RUM:'Rum', VODKA:'Vodka', GIN:'Gin', TEQUILA:'Tequila',
    COLA:'Cola', SODA:'Soda Water', SODA_WATER:'Soda Water',
    TONIC:'Tonic Water', TONIC_WATER:'Tonic Water',
    CRANBERRY:'Cranberry',
    SPECIAL:'Special',
    BITTERS:'Bitters', COINTREAU:'Cointreau', LEMON:'Lemon',
    SUGAR:'Sugar', VERMOUTH:'Vermouth',
};

export const INGREDIENT_ICONS = {
    WHISKEY:'🥃', WHISKY:'🥃',
    RUM:'🍾', VODKA:'🔮', GIN:'🌿', TEQUILA:'🌵',
    COLA:'🥤', SODA:'🫧', SODA_WATER:'🫧',
    TONIC:'🍶', TONIC_WATER:'🍶',
    CRANBERRY:'🫐',
    BITTERS:'✨', COINTREAU:'🍊', LEMON:'🍋',
    SUGAR:'🍬', VERMOUTH:'🌹',
    SPECIAL:'✨',
};

export const CARD_COST_TOKEN = { karaoke: 'spirit', store: 'spirit', refresher: 'mixer', cup_doubler: 'spirit', specialist: 'spirit' };
export const CARD_COST_COUNT = { karaoke: 3, store: 1, refresher: 2, cup_doubler: 3, specialist: 2 };

export const MAX_SLOTS = 5;
