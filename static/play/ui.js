// Shared UI primitives for the Table View: DOM helper, bottom sheet,
// event banners and the flying-token animation.

// el('div.foo', {aria-label: 'x'}, child, 'text') — tiny DOM builder.
export function el(spec, attrs = {}, ...children) {
    const [tag, ...classes] = spec.split('.');
    const node = document.createElement(tag || 'div');
    if (classes.length) node.className = classes.join(' ');
    for (const [k, v] of Object.entries(attrs)) {
        if (v === undefined || v === null || v === false) continue;
        if (k === 'onclick') node.addEventListener('click', v);
        else if (k === 'text') node.textContent = v;
        else if (k === 'html') node.innerHTML = v;
        else node.setAttribute(k, v === true ? '' : v);
    }
    for (const child of children.flat()) {
        if (child === null || child === undefined) continue;
        node.append(child.nodeType ? child : document.createTextNode(child));
    }
    return node;
}

// ─── Bottom sheet ────────────────────────────────────────────────────────────

let sheetCloseCallback = null;

export function openSheet(title, contentNodes, { onClose } = {}) {
    closeSheet();
    sheetCloseCallback = onClose ?? null;
    const backdrop = document.getElementById('sheetBackdrop');
    const sheet = document.getElementById('sheet');
    sheet.replaceChildren(
        el('div.sheet-grip', { 'aria-hidden': 'true' }),
        el('div.sheet-head', {},
            el('h2.sheet-title', { text: title }),
            el('button.sheet-close', { 'aria-label': 'Close', onclick: closeSheet, text: '✕' }),
        ),
        el('div.sheet-body', {}, contentNodes),
    );
    backdrop.classList.add('open');
    sheet.classList.add('open');
    sheet.setAttribute('aria-hidden', 'false');
    sheet.querySelector('.sheet-close').focus();
}

export function isSheetOpen() {
    return document.getElementById('sheet').classList.contains('open');
}

export function closeSheet() {
    const backdrop = document.getElementById('sheetBackdrop');
    const sheet = document.getElementById('sheet');
    if (!sheet.classList.contains('open')) return;
    backdrop.classList.remove('open');
    sheet.classList.remove('open');
    sheet.setAttribute('aria-hidden', 'true');
    if (sheetCloseCallback) {
        const cb = sheetCloseCallback;
        sheetCloseCallback = null;
        cb();
    }
}

export function sheetOption({ label, sub, icon, disabled, reason, onclick, primary }) {
    const btn = el('button.sheet-option', {
        onclick,
        disabled: !!disabled,
        'aria-label': label + (reason ? ` — ${reason}` : ''),
    },
        icon ? el('span.sheet-option-icon', { text: icon, 'aria-hidden': 'true' }) : null,
        el('span.sheet-option-main', {},
            el('span.sheet-option-label', { text: label }),
            (disabled && reason) ? el('span.sheet-option-reason', { text: reason })
                : sub ? el('span.sheet-option-sub', { text: sub }) : null,
        ),
    );
    if (primary) btn.classList.add('primary');
    return btn;
}

// ─── Event banners ───────────────────────────────────────────────────────────

const bannerQueue = [];
let bannerShowing = false;

export function banner(text, { icon = '', tone = 'info', ms = 2600 } = {}) {
    bannerQueue.push({ text, icon, tone, ms });
    if (!bannerShowing) nextBanner();
}

function nextBanner() {
    const item = bannerQueue.shift();
    if (!item) {
        bannerShowing = false;
        return;
    }
    bannerShowing = true;
    const host = document.getElementById('banners');
    const node = el('div.banner', { role: 'status', 'data-tone': item.tone },
        item.icon ? el('span.banner-icon', { text: item.icon, 'aria-hidden': 'true' }) : null,
        el('span', { text: item.text }),
    );
    host.append(node);
    requestAnimationFrame(() => node.classList.add('show'));
    setTimeout(() => {
        node.classList.remove('show');
        setTimeout(() => {
            node.remove();
            nextBanner();
        }, 300);
    }, item.ms);
}

export function toastError(message) {
    banner(message, { icon: '⚠️', tone: 'error', ms: 3200 });
}

// ─── Animations ──────────────────────────────────────────────────────────────

// Fly a visual clone of `tokenEl` from its position to `targetEl`'s centre.
export function flyToken(tokenEl, targetEl) {
    if (!tokenEl || !targetEl) return;
    const from = tokenEl.getBoundingClientRect();
    const to = targetEl.getBoundingClientRect();
    if (!from.width || !to.width) return;
    const clone = tokenEl.cloneNode(true);
    clone.classList.add('fly-clone');
    clone.style.left = `${from.left}px`;
    clone.style.top = `${from.top}px`;
    clone.style.width = `${from.width}px`;
    clone.style.height = `${from.height}px`;
    document.body.append(clone);
    requestAnimationFrame(() => {
        clone.style.transform =
            `translate(${to.left + to.width / 2 - from.left - from.width / 2}px, ` +
            `${to.top + to.height / 2 - from.top - from.height / 2}px) scale(0.6)`;
        clone.style.opacity = '0.2';
    });
    setTimeout(() => clone.remove(), 650);
}

export function pulse(elOrId) {
    const node = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
    if (!node) return;
    node.classList.remove('pulse-once');
    void node.offsetWidth; // restart the animation
    node.classList.add('pulse-once');
}
