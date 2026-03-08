/**
 * gameElements.js — custom web components for Bartenders of Corfu
 *
 * <ingredient name="RUM"></ingredient>
 *   Renders a BGA-style physical chip token for a single ingredient.
 *   Attributes:
 *     name  — ingredient key (e.g. "RUM", "VODKA", "SPECIAL")
 *     size  — "sm" | "md" (default) | "lg"
 */

const INGREDIENT_LABELS = {
    WHISKEY: 'Whiskey', WHISKY: 'Whisky',
    RUM: 'Rum', VODKA: 'Vodka', GIN: 'Gin', TEQUILA: 'Tequila',
    COLA: 'Cola', SODA: 'Soda', SODA_WATER: 'Soda',
    TONIC: 'Tonic', TONIC_WATER: 'Tonic',
    CRANBERRY: 'Cran',
    SPECIAL: 'Special',
    BITTERS: 'Bitters', COINTREAU: 'Coin',
    LEMON: 'Lemon', SUGAR: 'Sugar', VERMOUTH: 'Verm',
};

const INGREDIENT_ICONS = {
    WHISKEY: '🥃', WHISKY: '🥃',
    RUM: '🍾', VODKA: '🔮', GIN: '🌿', TEQUILA: '🌵',
    COLA: '🥤', SODA: '💧', SODA_WATER: '💧',
    TONIC: '💧', TONIC_WATER: '💧',
    CRANBERRY: '🫐',
    BITTERS: '✨', COINTREAU: '🍊', LEMON: '🍋',
    SUGAR: '🍬', VERMOUTH: '🌹',
    SPECIAL: '✨',
};

const SPIRITS  = new Set(['WHISKEY', 'WHISKY', 'RUM', 'VODKA', 'GIN', 'TEQUILA']);
const MIXERS   = new Set(['COLA', 'SODA', 'SODA_WATER', 'TONIC', 'TONIC_WATER', 'CRANBERRY']);

function _ingredientKind(key) {
    if (SPIRITS.has(key))  return 'spirit';
    if (MIXERS.has(key))   return 'mixer';
    return 'special';
}

class Ingredient extends HTMLElement {
    static observedAttributes = ['name', 'size'];

    connectedCallback() { this._render(); }
    attributeChangedCallback() { if (this.isConnected) this._render(); }

    _render() {
        const raw  = (this.getAttribute('name') || '').toUpperCase();
        const size = this.getAttribute('size') || 'md';
        const icon  = INGREDIENT_ICONS[raw]  || '?';
        const label = INGREDIENT_LABELS[raw] || raw || '?';
        const kind  = _ingredientKind(raw);

        const px = size === 'sm' ? 38 : size === 'lg' ? 60 : 48;
        const iconPx = size === 'sm' ? 16 : size === 'lg' ? 24 : 20;
        const labelPx = size === 'sm' ? 7 : size === 'lg' ? 9 : 8;

        this.setAttribute('aria-label', label);
        this.setAttribute('title', label);
        this.className = `gb-ingredient ${kind}`;
        this.style.cssText = `width:${px}px;height:${px}px;`;

        this.innerHTML = `
            <span class="gb-ingredient-icon" aria-hidden="true"
                  style="font-size:${iconPx}px">${icon}</span>
            <span class="gb-ingredient-label"
                  style="font-size:${labelPx}px">${label}</span>
        `;
    }
}

customElements.define('ingredient-token', Ingredient);
