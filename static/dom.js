/**
 * dom.js — DOM helper utilities.
 * Vanilla ES2022, no dependencies.
 */

/**
 * Create an element with attributes and children.
 * @param {string} tag - HTML tag name
 * @param {Object} [attrs] - Attributes/properties to set
 * @param {...(Node|string)} children - Child nodes or text
 * @returns {HTMLElement}
 */
export function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    if (attrs) {
        for (const [k, v] of Object.entries(attrs)) {
            if (k === 'className') el.className = v;
            else if (k === 'dataset') Object.assign(el.dataset, v);
            else if (k.startsWith('on') && typeof v === 'function') el[k] = v;
            else if (k === 'textContent') el.textContent = v;
            else el.setAttribute(k, v);
        }
    }
    for (const child of children) {
        if (child == null) continue;
        el.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    }
    return el;
}

/** Shorthand for document.createTextNode */
export function text(str) {
    return document.createTextNode(str);
}

/** Shorthand for getElementById */
export function el(id) {
    return document.getElementById(id);
}


export function showError(msg) {
    const bar = el('gbErrorBar');
    bar.textContent = msg;
    bar.classList.add('visible');
}

export function clearError() {
    const bar = el('gbErrorBar');
    bar.textContent = '';
    bar.classList.remove('visible');
}

export function showModalError(elId, msg) {
    const bar = el(elId);
    if (!bar) return;
    bar.textContent = msg;
    bar.classList.add('visible');
}

export function clearModalError(elId) {
    const bar = el(elId);
    if (!bar) return;
    bar.textContent = '';
    bar.classList.remove('visible');
}

export function setButtonBusy(btn, busy, originalText) {
    if (!btn) return;
    if (busy) {
        btn.disabled = true;
        btn._origChildren = [...btn.childNodes].map(n => n.cloneNode(true));
        const spinner = h('span', { className: 'spinner', 'aria-hidden': 'true' });
        btn.replaceChildren(spinner, text(originalText || 'Working…'));
    } else {
        btn.disabled = false;
        if (btn._origChildren) btn.replaceChildren(...btn._origChildren);
    }
}

export function formatTime(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    } catch { return iso; }
}

export function flash(elId, cssClass, msg, durationMs = 2500) {
    const container = el(elId);
    if (!container) return;
    container.className = `gb-flash ${cssClass}`;
    container.textContent = msg;
    setTimeout(() => { container.className = 'gb-flash'; container.textContent = ''; }, durationMs);
}

export function switchTab(name) {
    ['history','replay'].forEach(t => {
        const btn = el(`gbTabBtn${t.charAt(0).toUpperCase()+t.slice(1)}`);
        const pane = el(`gbTab${t.charAt(0).toUpperCase()+t.slice(1)}`);
        const active = t === name;
        if (btn)  { btn.classList.toggle('active', active); btn.setAttribute('aria-selected', String(active)); }
        if (pane) { pane.classList.toggle('active', active); }
    });
}

/** Open a modal overlay with focus trapping */
export function openModal(id) {
    const overlay = el(id);
    if (!overlay) return;
    overlay.classList.remove('hidden');
    setTimeout(() => {
        const focusable = overlay.querySelector('button:not([disabled]), select, [tabindex="0"]');
        if (focusable) focusable.focus();
        else overlay.focus();
    }, 30);
    overlay._escHandler = e => { if (e.key === 'Escape') closeModal(id); };
    document.addEventListener('keydown', overlay._escHandler);
}

/** Close a modal overlay */
export function closeModal(id) {
    const overlay = el(id);
    if (!overlay) return;
    overlay.classList.add('hidden');
    if (overlay._escHandler) {
        document.removeEventListener('keydown', overlay._escHandler);
        overlay._escHandler = null;
    }
    const bag = el('gbBagVisual');
    if (bag) bag.focus();
}
