let user;
let listGamesInProgress = false;
let initialLoadDone = false;

async function setUserHeader() {
    const response = await fetch('/userDetails')
    if (!response.ok) {
        showLogin()
    } else {
        user = await response.json()
        setUser(user)
    }
}

function showLogin() {
    document.getElementById('loginLink').classList.remove('hidden');
    document.getElementById('logoutLink').classList.add('hidden');
    document.getElementById('helloUser').classList.add('hidden');
    const adminLink = document.getElementById('adminLink');
    if (adminLink) adminLink.classList.add('hidden');
}

function setUser(u) {
    document.getElementById('loginLink').classList.add('hidden');
    const helloUser = document.getElementById('helloUser');
    helloUser.classList.remove("hidden");
    helloUser.innerText = `Hello ${u.username} | `;
    document.getElementById('logoutLink').classList.remove('hidden');
    const adminLink = document.getElementById('adminLink');
    if (adminLink) {
        if (u.is_admin) {
            adminLink.classList.remove('hidden');
        } else {
            adminLink.classList.add('hidden');
        }
    }
}

function showGameListError(msg) {
    const el = document.getElementById('gameListError');
    el.textContent = msg;
    el.classList.remove('hidden');
}

function clearGameListError() {
    const el = document.getElementById('gameListError');
    el.textContent = '';
    el.classList.add('hidden');
}

const STATUS_LABEL = { NEW: 'Not Started', STARTED: 'In Progress', ENDED: 'Ended' };

function buildGameItem(game) {
    const li = document.createElement('li');
    if (game.id) li.dataset.gameId = game.id;
    if (game.pending) li.dataset.pending = 'true';

    // Info column
    const info = document.createElement('div');
    info.className = 'game-info';

    const title = document.createElement('div');
    title.className = 'game-title';
    title.textContent = `${game.host_username}'s Game`;
    info.appendChild(title);

    const playersEl = document.createElement('div');
    playersEl.className = 'game-players';
    if (game.player_usernames && game.player_usernames.length) {
        playersEl.textContent = `Players: ${game.player_usernames.join(', ')}`;
    } else {
        playersEl.textContent = `${game.players ? game.players.length : 1} / 4 players`;
    }
    info.appendChild(playersEl);

    const statusEl = document.createElement('div');
    statusEl.className = 'game-status';
    const playerCount = game.players ? game.players.length : 1;
    statusEl.textContent = `${STATUS_LABEL[game.status] ?? game.status} \u00b7 ${playerCount}/4 players`;
    info.appendChild(statusEl);

    li.appendChild(info);

    // Action column
    const action = document.createElement('div');
    action.className = 'game-action';

    if (game.pending) {
        const spinner = document.createElement('span');
        spinner.className = 'spinner';
        spinner.setAttribute('aria-hidden', 'true');
        action.appendChild(spinner);
    } else {
        const isFull = (game.players ? game.players.length : 0) >= 4;
        if (user && game.players && game.players.some(p => p === user.id)) {
            const btn = document.createElement('button');
            btn.textContent = 'Go to Game';
            btn.onclick = () => window.location.href = `/game?id=${game.id}`;
            action.appendChild(btn);
        } else if (game.status !== 'NEW') {
            const label = document.createElement('span');
            label.className = 'game-full-label';
            label.textContent = STATUS_LABEL[game.status] ?? game.status;
            action.appendChild(label);
        } else if (isFull) {
            const label = document.createElement('span');
            label.className = 'game-full-label';
            label.textContent = 'Game Full';
            action.appendChild(label);
        } else if (!user) {
            const btn = document.createElement('button');
            btn.textContent = 'Login to Join';
            btn.onclick = () => window.location.href = '/login';
            action.appendChild(btn);
        } else {
            const btn = document.createElement('button');
            btn.textContent = 'Join Game';
            btn.onclick = () => joinGame(game.id);
            action.appendChild(btn);
        }
    }

    li.appendChild(action);
    return li;
}

async function createNewGame() {
    clearGameListError();
    const btn = document.querySelector("button[aria-label='Start new game']");
    if (btn) { btn.disabled = true; btn.textContent = 'Creating\u2026'; }

    // Optimistic: immediately prepend a placeholder row
    const gameList = document.getElementById('gameList');
    const placeholder = buildGameItem({
        host_username: user ? user.username : 'You',
        player_usernames: user ? [user.username] : [],
        players: user ? [user.id] : [],
        status: 'NEW',
        pending: true,
    });
    gameList.prepend(placeholder);

    try {
        const response = await fetch('/v1/games', { method: 'POST' });
        if (response.status == 401) {
            placeholder.remove();
            window.location.href = '/login';
            return;
        }
        if (!response.ok) {
            placeholder.remove();
            const data = await response.json().catch(() => ({}));
            showGameListError(data.error || 'Failed to create game. Please try again.');
            return;
        }
        const data = await response.json();
        // Upgrade placeholder: set real ID and show Go to Game
        placeholder.dataset.gameId = data.id;
        delete placeholder.dataset.pending;
        const action = placeholder.querySelector('.game-action');
        action.innerHTML = '';
        const goBtn = document.createElement('button');
        goBtn.textContent = 'Go to Game';
        goBtn.onclick = () => window.location.href = `/game?id=${data.id}`;
        action.appendChild(goBtn);
        // Background sync
        listGames();
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Start Mixing Cocktails'; }
    }
}

async function listGames() {
    if (listGamesInProgress) return;
    listGamesInProgress = true;
    clearGameListError();

    const gameList = document.getElementById('gameList');

    // First load only: show a spinner while fetching
    if (!initialLoadDone) {
        gameList.innerHTML =
            '<li class="loading-placeholder">' +
            '<span class="spinner" aria-hidden="true"></span>Loading games\u2026</li>';
    }

    try {
        const response = await fetch('/v1/games');
        if (!response.ok) {
            showGameListError('Failed to load games. Please refresh the page.');
            return;
        }
        const data = await response.json();

        // Build all items off-DOM (no async lookups needed — data is already enriched)
        const lis = data.games.map(game => buildGameItem(game));

        // Atomic swap: only clear once new items are ready
        gameList.innerHTML = '';
        lis.forEach(li => gameList.appendChild(li));
        initialLoadDone = true;
    } catch (e) {
        console.error(e);
        showGameListError('Failed to load games. Please refresh the page.');
    } finally {
        listGamesInProgress = false;
    }
}

async function joinGame(gameId) {
    clearGameListError();

    // Optimistic update: flip action to "Go to Game" immediately
    const li = document.querySelector(`li[data-game-id="${gameId}"]`);
    let actionEl = null;
    let originalHTML = null;
    if (li) {
        actionEl = li.querySelector('.game-action');
        originalHTML = actionEl.innerHTML;
        actionEl.innerHTML = '';
        const btn = document.createElement('button');
        btn.textContent = 'Go to Game';
        btn.onclick = () => window.location.href = `/game?id=${gameId}`;
        actionEl.appendChild(btn);
    }

    const response = await fetch(`/v1/games/${gameId}/join`, { method: 'POST' });
    if (response.status == 401) {
        window.location.href = '/login';
        return;
    }
    if (response.ok) {
        // Sync in background — UI already shows the right state
        listGames();
    } else {
        // Revert optimistic update and show error
        if (actionEl !== null) actionEl.innerHTML = originalHTML;
        const data = await response.json().catch(() => ({}));
        showGameListError(data.error || 'Failed to join game. Please try again.');
    }
}

async function setLogOutLink() {
    document.getElementById('logoutLink').addEventListener('click', async (e) => {
        e.preventDefault();
        try {
            const response = await fetch('/logout', { method: 'POST' });
            if (response.ok) {
                user = null;
                await setUserHeader();
                await listGames();
            }
        } catch (error) {
            console.error('Logout failed:', error);
        }
    });
}

async function init() {
    await setUserHeader();
    await listGames();
    // Keep the list fresh in the background
    setInterval(listGames, 30000);
}
