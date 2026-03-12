/**
 * ingredients.js — Ingredient helper functions.
 * Vanilla ES2022.
 */

import { SPIRITS, MIXERS, INGREDIENT_LABELS, INGREDIENT_ICONS } from './constants.js';

export function ingredientLabel(name) {
    if (!name) return '?';
    return INGREDIENT_LABELS[name.toUpperCase()] || name;
}

export function ingredientIcon(name) {
    if (!name) return '';
    return INGREDIENT_ICONS[name.toUpperCase()] || '';
}

export function ingredientKind(name) {
    if (!name) return 'special';
    const u = name.toUpperCase();
    if (SPIRITS.has(u))  return 'spirit';
    if (MIXERS.has(u))   return 'mixer';
    return 'special';
}

/** Build a coloured ingredient token element (BGA-style raised token) */
export function makeIngredientBadge(name) {
    const span = document.createElement('span');
    span.className = `gb-ingredient ${ingredientKind(name)}`;
    const icon = ingredientIcon(name);
    const label = ingredientLabel(name);
    span.textContent = icon ? `${icon} ${label}` : label;
    span.setAttribute('aria-label', label);
    span.title = label;
    return span;
}

/** Build a cost badge element */
export function makeCostBadge(costItem) {
    const span = document.createElement('span');
    const kindNorm = (costItem.kind || '').toLowerCase();
    let cls = 'gb-cost-badge';
    if (kindNorm.includes('spirit'))  cls += ' spirit';
    else if (kindNorm.includes('mixer')) cls += ' mixer';
    else if (kindNorm.includes('special')) cls += ' special';
    span.className = cls;
    span.textContent = `${costItem.count}× ${costItem.kind}`;
    return span;
}
