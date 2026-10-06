// Invite links for a game waiting to start. The link opens the game's
// lobby, where a friend can take a seat.

export function inviteUrl(gameId) {
    return `${window.location.origin}/bar?id=${encodeURIComponent(gameId)}`;
}

// Copy text to the clipboard. Returns true when it worked.
export async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch { /* fall back below */ }
    }
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.top = '-1000px';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        ta.setSelectionRange(0, text.length);
        const ok = document.execCommand('copy');
        ta.remove();
        return ok;
    } catch {
        return false;
    }
}

// A read-only box showing the link, with a Copy button beside it.
// ``classes`` lets each view style it: { box, input, button }.
export function inviteBox(gameId, { classes = {}, onCopied } = {}) {
    const url = inviteUrl(gameId);
    const box = document.createElement('div');
    box.className = `invite ${classes.box ?? ''}`.trim();

    const label = document.createElement('label');
    label.className = 'invite-label';
    label.htmlFor = 'inviteLink';
    label.textContent = 'Invite friends with this link';

    const row = document.createElement('div');
    row.className = 'invite-row';

    const input = document.createElement('input');
    input.id = 'inviteLink';
    input.type = 'text';
    input.readOnly = true;
    input.value = url;
    input.className = `invite-url ${classes.input ?? ''}`.trim();
    input.setAttribute('aria-label', 'Invite link for this game');
    input.addEventListener('focus', () => input.select());

    const button = document.createElement('button');
    button.type = 'button';
    button.className = `invite-copy ${classes.button ?? ''}`.trim();
    button.textContent = 'Copy link';
    button.setAttribute('aria-label', 'Copy the invite link');
    button.addEventListener('click', async () => {
        const ok = await copyText(url);
        if (ok) {
            button.textContent = 'Copied!';
            setTimeout(() => { button.textContent = 'Copy link'; }, 1600);
            onCopied?.(true);
        } else {
            input.focus();
            input.select();
            onCopied?.(false);
        }
    });

    row.append(input, button);
    box.append(label, row);
    return box;
}
