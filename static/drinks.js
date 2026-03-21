/**
 * drinks.js — Drink detection and scoring logic.
 * Auto-detects the best possible drink from cup contents + available specials.
 * Vanilla ES2022, no dependencies.
 */

const COCKTAIL_RECIPES = [
    {
        name: 'Long Island Iced Tea',
        spirits: { GIN: 1, VODKA: 1, TEQUILA: 1, RUM: 1 },
        mixers: { COLA: 1 },
        specials: ['sugar', 'lemon'],
        points: 15,
    },
    {
        name: 'Mojito',
        spirits: { RUM: 2 },
        mixers: { SODA: 1 },
        specials: ['sugar'],
        points: 10,
    },
    {
        name: 'Old Fashioned',
        spirits: { WHISKEY: 3 },
        mixers: {},
        specials: ['bitters'],
        points: 10,
    },
    {
        name: 'Margarita',
        spirits: { TEQUILA: 2 },
        mixers: {},
        specials: ['cointreau', 'lemon'],
        points: 10,
    },
    {
        name: 'Cosmopolitan',
        spirits: { VODKA: 1 },
        mixers: { CRANBERRY: 1 },
        specials: ['cointreau', 'lemon'],
        points: 10,
    },
    {
        name: 'Gin Martini',
        spirits: { GIN: 3 },
        mixers: {},
        specials: ['vermouth'],
        points: 10,
    },
    {
        name: 'Vodka Martini',
        spirits: { VODKA: 3 },
        mixers: {},
        specials: ['vermouth'],
        points: 10,
    },
    {
        name: 'Tom Collins',
        spirits: { GIN: 1 },
        mixers: { SODA: 1 },
        specials: ['lemon', 'sugar'],
        points: 10,
    },
    {
        name: 'Manhattan',
        spirits: { WHISKEY: 2 },
        mixers: {},
        specials: ['vermouth', 'bitters'],
        points: 10,
    },
];

const VALID_PAIRINGS = {
    VODKA: new Set(['COLA', 'SODA', 'TONIC', 'CRANBERRY']),
    RUM: new Set(['COLA']),
    WHISKEY: new Set(['COLA', 'SODA']),
    GIN: new Set(['TONIC']),
    TEQUILA: new Set(),
};

const SPIRITS_SET = new Set(['WHISKEY', 'RUM', 'VODKA', 'GIN', 'TEQUILA']);
const MIXERS_SET = new Set(['COLA', 'SODA', 'TONIC', 'CRANBERRY']);

function countItems(arr) {
    const counts = {};
    for (const item of arr) {
        const u = item.toUpperCase();
        counts[u] = (counts[u] || 0) + 1;
    }
    return counts;
}

function countsEqual(a, b) {
    const keysA = Object.keys(a);
    const keysB = Object.keys(b);
    if (keysA.length !== keysB.length) return false;
    for (const k of keysA) {
        if (a[k] !== (b[k] || 0)) return false;
    }
    return true;
}

/**
 * Detect the best possible drink from cup contents and available specials.
 * @param {string[]} cupIngredients - ingredients in the cup
 * @param {string[]} availableSpecials - specials on player mat
 * @param {boolean} hasCupDoubler - whether this cup has a doubler
 * @param {string[]} specialistSpiritTypes - spirit types from claimed specialist cards
 * @returns {{ name: string, points: number, declaredSpecials: string[] } | null}
 */
export function detectBestDrink(cupIngredients, availableSpecials, hasCupDoubler = false, specialistSpiritTypes = []) {
    if (!cupIngredients || cupIngredients.length === 0) return null;

    const cupSpirits = cupIngredients.filter(i => SPIRITS_SET.has(i.toUpperCase())).map(i => i.toUpperCase());
    const cupMixers = cupIngredients.filter(i => MIXERS_SET.has(i.toUpperCase())).map(i => i.toUpperCase());
    const spiritCounts = countItems(cupSpirits);
    const mixerCounts = countItems(cupMixers);
    const specialCounts = countItems(availableSpecials || []);

    // Specialist bonus: +2 per matching spirit type (non-cocktails only, after doubling)
    const specSet = new Set((specialistSpiritTypes || []).map(s => s.toUpperCase()));
    const cupSpiritTypes = new Set(cupSpirits);
    let specialistBonus = 0;
    for (const st of cupSpiritTypes) {
        if (specSet.has(st)) specialistBonus += 2;
    }

    // 1. Check cocktails (best points first — Long Island first, then 10-pointers)
    for (const recipe of COCKTAIL_RECIPES) {
        // Check spirits match exactly
        if (!countsEqual(spiritCounts, recipe.spirits)) continue;
        // Check mixers match exactly
        if (!countsEqual(mixerCounts, recipe.mixers)) continue;
        // Check specials available (exact match — no extras declared)
        const neededSpecials = countItems(recipe.specials);
        let specialsOk = true;
        for (const [sp, count] of Object.entries(neededSpecials)) {
            if ((specialCounts[sp.toUpperCase()] || 0) < count) {
                specialsOk = false;
                break;
            }
        }
        if (!specialsOk) continue;
        // Cocktails are never doubled
        return {
            name: recipe.name,
            points: recipe.points,
            declaredSpecials: recipe.specials.slice(),
        };
    }

    // 2. Tequila Slammer: exactly 2x TEQUILA, no mixers, no specials
    if (cupSpirits.length === 2 && cupMixers.length === 0 &&
        spiritCounts['TEQUILA'] === 2 && Object.keys(spiritCounts).length === 1) {
        const base = 3;
        const pts = (hasCupDoubler ? base * 2 : base) + specialistBonus;
        return {
            name: 'Tequila Slammer',
            points: pts,
            declaredSpecials: [],
        };
    }

    // Non-cocktail drinks: max 2 spirits
    if (cupSpirits.length > 2) return null;

    // 3. Double spirit: 2 spirits (same type), >=1 valid mixer, all mixers valid
    if (cupSpirits.length === 2 && Object.keys(spiritCounts).length === 1) {
        const spiritType = Object.keys(spiritCounts)[0];
        const validMixers = VALID_PAIRINGS[spiritType] || new Set();
        if (cupMixers.length >= 1 && cupMixers.every(m => validMixers.has(m))) {
            const base = 3;
            const pts = (hasCupDoubler ? base * 2 : base) + specialistBonus;
            return {
                name: `Double ${spiritType.charAt(0) + spiritType.slice(1).toLowerCase()}`,
                points: pts,
                declaredSpecials: [],
            };
        }
    }

    // 4. Single spirit: 1 spirit, >=1 valid mixer, all mixers valid
    if (cupSpirits.length === 1) {
        const spiritType = cupSpirits[0];
        const validMixers = VALID_PAIRINGS[spiritType] || new Set();
        if (cupMixers.length >= 1 && cupMixers.every(m => validMixers.has(m))) {
            const base = 1;
            const pts = (hasCupDoubler ? base * 2 : base) + specialistBonus;
            return {
                name: `${spiritType.charAt(0) + spiritType.slice(1).toLowerCase()} & ${cupMixers.map(m => m.charAt(0) + m.slice(1).toLowerCase()).join('/')}`,
                points: pts,
                declaredSpecials: [],
            };
        }
    }

    return null;
}

/**
 * Get all cocktail recipes (for menu rendering).
 * @returns {Array} cocktail recipe objects
 */
export function getCocktailRecipes() {
    return COCKTAIL_RECIPES;
}

/**
 * Get valid spirit-mixer pairings.
 * @returns {Object} map of spirit → Set of valid mixers
 */
export function getValidPairings() {
    return VALID_PAIRINGS;
}

/**
 * Special ingredient types in the game.
 */
export const SPECIAL_TYPES = ['bitters', 'cointreau', 'lemon', 'sugar', 'vermouth'];

/**
 * Get cocktails that use a given special type.
 * @param {string} specialType
 * @returns {Array} matching recipes
 */
export function cocktailsForSpecial(specialType) {
    const lower = specialType.toLowerCase();
    return COCKTAIL_RECIPES.filter(r => r.specials.includes(lower));
}
