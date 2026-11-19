// The table drawn at one fixed size, like a real box on a real table, then
// scaled to fit the screen (the way Board Game Arena does it).
// Because every piece keeps the same size and place whatever the screen,
// pieces can be animated as they move (bar/motion.js).
//
// Two layouts: wide (desktop) and narrow (phones). Each is laid out at its
// own fixed width and zoomed to fit.

const WIDE = 1240;
const NARROW = 540;
const NARROW_BELOW = 860; // matches the one-column layout in bar.css

let zoom = 1; // what the table is drawn at right now
let onChange = () => {};

const design = () => (document.documentElement.clientWidth < NARROW_BELOW ? 'narrow' : 'wide');

export const liveZoom = () => zoom;

// Fit the fixed-width table to the room the screen gives it.
export function layout() {
    const body = document.body;
    const which = design();
    body.classList.toggle('live-wide', which === 'wide');
    body.classList.toggle('live-narrow', which === 'narrow');
    const width = which === 'wide' ? WIDE : NARROW;
    const room = document.documentElement.clientWidth;
    const fit = Math.min(room / width, 1.2);
    zoom = Math.round(fit * 1000) / 1000;
    body.style.setProperty('--live-w', `${width}px`);
    body.style.setProperty('--live-zoom', String(zoom));
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
