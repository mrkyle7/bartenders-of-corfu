/**
 * theme.js — Shared color theme utilities for Bartenders of Corfu.
 * Include in <head> of every page (before stylesheets) to prevent FOUC.
 */

const THEME_KEY = 'boc-theme';
const VALID_THEMES = ['taverna', 'mediterranean', 'nightclub', 'sunset'];
const THEME_META_COLORS = {
    taverna: '#4a2c0e',
    mediterranean: '#0c2d48',
    nightclub: '#121218',
    sunset: '#4a2040',
};

/**
 * Apply theme to the document immediately.
 */
function applyTheme(theme) {
    if (!VALID_THEMES.includes(theme)) theme = 'taverna';
    if (theme === 'taverna') {
        document.documentElement.removeAttribute('data-theme');
    } else {
        document.documentElement.setAttribute('data-theme', theme);
    }
    // Update meta theme-color for mobile browser chrome
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', THEME_META_COLORS[theme] || THEME_META_COLORS.taverna);
    localStorage.setItem(THEME_KEY, theme);
}

/**
 * Get the currently stored theme.
 */
function getStoredTheme() {
    return localStorage.getItem(THEME_KEY) || 'taverna';
}

// Apply cached theme immediately on script load (prevents FOUC)
applyTheme(getStoredTheme());
