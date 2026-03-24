let user;
let listGamesInProgress = false;
let initialLoadDone = false;
let myTurnCount = 0;
let myGamesStatusFilter = 'STARTED';

const PAGE_SIZE = 20;
let myGamesPage = 1;
let myGamesTotal = 0;
let joinGamesPage = 1;
let joinGamesTotal = 0;

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

function getTurnUsername(game) {
    if (game.status !== 'STARTED' || !game.game_state) return null;
    const turnId = game.game_state.player_turn;
    if (!turnId || !game.players) return null;
    const idx = game.players.indexOf(turnId);
    if (idx === -1 || !game.player_usernames) return null;
    return game.player_usernames[idx];
}

function isMyTurn(game) {
    return user && game.status === 'STARTED' && game.game_state && game.game_state.player_turn === user.id;
}

function buildGameItem(game) {
    const li = document.createElement('li');
    if (game.id) li.dataset.gameId = game.id;
    if (game.pending) li.dataset.pending = 'true';

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

    if (game.status === 'STARTED') {
        const turnEl = document.createElement('div');
        turnEl.className = 'game-turn';
        if (isMyTurn(game)) {
            turnEl.classList.add('my-turn');
            turnEl.textContent = 'Your turn!';
        } else {
            const turnName = getTurnUsername(game);
            if (turnName) turnEl.textContent = `${turnName}'s turn`;
        }
        if (turnEl.textContent) info.appendChild(turnEl);
    }

    li.appendChild(info);

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

function _emptyPlaceholder(text) {
    const li = document.createElement('li');
    li.className = 'game-section-empty';
    li.textContent = text;
    return li;
}

function _loadMoreItem(onClick) {
    const li = document.createElement('li');
    li.className = 'load-more-item';
    const btn = document.createElement('button');
    btn.className = 'load-more-btn';
    btn.textContent = 'Load more';
    btn.onclick = () => {
        btn.disabled = true;
        btn.textContent = 'Loading\u2026';
        onClick();
    };
    li.appendChild(btn);
    return li;
}

function setMyGamesFilter(status) {
    myGamesStatusFilter = status;
    document.querySelectorAll('.status-filter .filter-tab').forEach(btn => {
        const isActive = btn.dataset.status === status;
        btn.classList.toggle('active', isActive);
        btn.setAttribute('aria-selected', isActive);
    });
    myGamesPage = 1;
    loadMyGames(1, false);
}

async function loadMyGames(page, append = false) {
    if (!user) return;
    const list = document.getElementById('myGameList');
    let url = `/v1/games?player_id=${encodeURIComponent(user.id)}&page=${page}&page_size=${PAGE_SIZE}`;
    if (myGamesStatusFilter) {
        url += `&status=${encodeURIComponent(myGamesStatusFilter)}`;
    }
    const resp = await fetch(url);
    if (!resp.ok) {
        showGameListError('Failed to load your games. Please refresh.');
        return;
    }
    const data = await resp.json();
    myGamesPage = page;
    myGamesTotal = data.total;

    if (!append) {
        list.innerHTML = '';
        myTurnCount = 0;
    }
    const existingMore = list.querySelector('.load-more-item');
    if (existingMore) existingMore.remove();

    if (data.games.length === 0 && !append) {
        list.appendChild(_emptyPlaceholder('You have no active games.'));
    } else {
        data.games.forEach(g => {
            if (isMyTurn(g)) myTurnCount++;
            list.appendChild(buildGameItem(g));
        });
    }

    if (page * PAGE_SIZE < myGamesTotal) {
        list.appendChild(_loadMoreItem(() => loadMyGames(page + 1, true)));
    }
    updateNotificationBell();
}

async function loadJoinableGames(page, append = false) {
    const list = document.getElementById('joinGameList');
    const resp = await fetch(
        `/v1/games?status=NEW&page=${page}&page_size=${PAGE_SIZE}`
    );
    if (!resp.ok) {
        showGameListError('Failed to load joinable games. Please refresh.');
        return;
    }
    const data = await resp.json();
    joinGamesPage = page;
    joinGamesTotal = data.total;

    if (!append) list.innerHTML = '';
    const existingMore = list.querySelector('.load-more-item');
    if (existingMore) existingMore.remove();

    // Filter out games the user is already a member of
    const joinable = data.games.filter(
        g => !user || !g.players || !g.players.some(p => p === user.id)
    );

    if (joinable.length === 0 && !append) {
        list.appendChild(_emptyPlaceholder('No games available to join right now.'));
    } else {
        joinable.forEach(g => list.appendChild(buildGameItem(g)));
    }

    if (page * PAGE_SIZE < joinGamesTotal) {
        list.appendChild(_loadMoreItem(() => loadJoinableGames(page + 1, true)));
    }
}

async function createNewGame() {
    clearGameListError();
    const btn = document.querySelector("button[aria-label='Start new game']");
    if (btn) { btn.disabled = true; btn.textContent = 'Creating\u2026'; }

    const mySection = document.getElementById('myGamesSection');
    const myList = document.getElementById('myGameList');
    mySection.classList.remove('hidden');
    const emptyEl = myList.querySelector('.game-section-empty');
    if (emptyEl) emptyEl.remove();

    const placeholder = buildGameItem({
        host_username: user ? user.username : 'You',
        player_usernames: user ? [user.username] : [],
        players: user ? [user.id] : [],
        status: 'NEW',
        pending: true,
    });
    myList.prepend(placeholder);

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
        placeholder.dataset.gameId = data.id;
        delete placeholder.dataset.pending;
        const action = placeholder.querySelector('.game-action');
        action.innerHTML = '';
        const goBtn = document.createElement('button');
        goBtn.textContent = 'Go to Game';
        goBtn.onclick = () => window.location.href = `/game?id=${data.id}`;
        action.appendChild(goBtn);
        listGames();
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Start Mixing Cocktails'; }
    }
}

async function listGames() {
    if (listGamesInProgress) return;
    listGamesInProgress = true;
    clearGameListError();

    myGamesPage = 1;
    joinGamesPage = 1;

    const mySection = document.getElementById('myGamesSection');
    const myList = document.getElementById('myGameList');
    const joinList = document.getElementById('joinGameList');

    if (!initialLoadDone) {
        const spinnerHtml =
            '<li class="loading-placeholder">' +
            '<span class="spinner" aria-hidden="true"></span>Loading games\u2026</li>';
        if (user) myList.innerHTML = spinnerHtml;
        joinList.innerHTML = spinnerHtml;
    }

    try {
        if (!user) {
            mySection.classList.add('hidden');
        } else {
            mySection.classList.remove('hidden');
            await loadMyGames(1, false);
        }
        await loadJoinableGames(1, false);
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
        listGames();
    } else {
        if (actionEl !== null) actionEl.innerHTML = originalHTML;
        const data = await response.json().catch(() => ({}));
        showGameListError(data.error || 'Failed to join game. Please try again.');
    }
}

function updateNotificationBell() {
    const bell = document.getElementById('notificationBell');
    if (!bell) return;
    const badge = bell.querySelector('.notif-badge');
    if (myTurnCount > 0) {
        bell.classList.remove('hidden');
        badge.textContent = myTurnCount;
        bell.setAttribute('aria-label', `${myTurnCount} game${myTurnCount === 1 ? '' : 's'} waiting for your turn`);
    } else {
        bell.classList.add('hidden');
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
    setInterval(listGames, 30000);

    // Register service worker for PWA notifications
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    }

    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }

    // Background polling: tell SW to poll all games when tab is hidden
    document.addEventListener('visibilitychange', () => {
        if (!navigator.serviceWorker?.controller || !user) return;
        if (document.visibilityState === 'hidden') {
            navigator.serviceWorker.controller.postMessage({
                type: 'START_POLL',
                playerId: user.id,
                knownTurns: {},
            });
        } else {
            navigator.serviceWorker.controller.postMessage({ type: 'STOP_POLL' });
        }
    });
}
