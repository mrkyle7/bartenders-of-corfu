// Live view: the table drawn at one fixed size, like a real box on a real
// table, then scaled to fit the screen (the way Board Game Arena does it).
// Because every piece keeps the same size and place whatever the screen,
// pieces can be animated as they move (bar/motion.js).
//
// Two layouts: wide (desktop) and narrow (phones). Each is laid out at its
// own fixed width and zoomed to fit; − and + zoom further in or out.

const KEY_ON = 'bar-live';
const KEY_ZOOM = 'bar-live-zoom';
const WIDE = 1240;
const NARROW = 540;
const NARROW_BELOW = 860; // matches the one-column layout in bar.css
const STEPS = [0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.25, 1.4, 1.6];

const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } },
};

let on = store.get(KEY_ON) === '1';
let zoom = 1; // what the table is drawn at right now
let zoomer = null;
let onChange = () => {};

const design = () => (document.documentElement.clientWidth < NARROW_BELOW ? 'narrow' : 'wide');
const userZoom = () => {
    const z = Number(store.get(`${KEY_ZOOM}-${design()}`));
    return STEPS.includes(z) ? z : 1;
};

export const isLive = () => on;
export const liveZoom = () => (on ? zoom : 1);

export function setLive(value) {
    on = value;
    store.set(KEY_ON, on ? '1' : '0');
    layout();
}

// Fit the fixed-width table to the room the screen gives it.
export function layout() {
    const body = document.body;
    body.classList.toggle('is-live', on);
    const which = design();
    body.classList.toggle('live-wide', on && which === 'wide');
    body.classList.toggle('live-narrow', on && which === 'narrow');
    if (!on) {
        body.style.removeProperty('--live-zoom');
        body.style.removeProperty('--live-w');
        if (zoomer) zoomer.hidden = true;
        return;
    }
    const width = which === 'wide' ? WIDE : NARROW;
    const room = document.documentElement.clientWidth;
    const fit = Math.min(room / width, 1.2);
    zoom = Math.round(fit * userZoom() * 1000) / 1000;
    body.style.setProperty('--live-w', `${width}px`);
    body.style.setProperty('--live-zoom', String(zoom));
    renderZoomer();
}

function step(direction) {
    const now = userZoom();
    const i = STEPS.indexOf(now) + direction;
    if (i < 0 || i >= STEPS.length) return;
    store.set(`${KEY_ZOOM}-${design()}`, String(STEPS[i]));
    layout();
    onChange();
}

function renderZoomer() {
    if (!zoomer) {
        zoomer = document.createElement('div');
        zoomer.className = 'zoomer';
        zoomer.setAttribute('role', 'group');
        zoomer.setAttribute('aria-label', 'Table zoom');
        const out = Object.assign(document.createElement('button'), { type: 'button', className: 'zoom-btn', textContent: '−' });
        out.setAttribute('aria-label', 'Zoom the table out');
        out.dataset.k = 'zoom-out';
        out.onclick = () => step(-1);
        const level = Object.assign(document.createElement('span'), { className: 'zoom-level' });
        level.setAttribute('aria-live', 'polite');
        const inn = Object.assign(document.createElement('button'), { type: 'button', className: 'zoom-btn', textContent: '+' });
        inn.setAttribute('aria-label', 'Zoom the table in');
        inn.dataset.k = 'zoom-in';
        inn.onclick = () => step(1);
        zoomer.append(out, level, inn);
        document.body.append(zoomer);
    }
    zoomer.hidden = false;
    const z = userZoom();
    zoomer.querySelector('.zoom-level').textContent = `${Math.round(z * 100)}%`;
    zoomer.querySelector('[data-k="zoom-out"]').disabled = z === STEPS[0];
    zoomer.querySelector('[data-k="zoom-in"]').disabled = z === STEPS[STEPS.length - 1];
}

// Re-fit on resize; tell the page so it can redraw at the new size.
export function initLive(changed) {
    onChange = changed;
    let last = design();
    window.addEventListener('resize', () => {
        layout();
        if (design() !== last) {
            last = design();
            onChange();
        }
    });
    layout();
}
