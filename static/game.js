function showGameError(msg) {
    const el = document.getElementById('gameError');
    el.textContent = msg;
    el.classList.remove('hidden');
}

function clearGameError() {
    const el = document.getElementById('gameError');
    el.textContent = '';
    el.classList.add('hidden');
}

function renderPlayers(players, game, me) {
    const playerList = document.getElementById("playerList");
    playerList.innerHTML = '';
    for (const player of players) {
        const entry = document.createElement('span');
        entry.className = 'player-entry';
        const nameSpan = document.createElement('span');
        nameSpan.textContent = player.username;
        entry.appendChild(nameSpan);
        if (me && me.id === game.host && player.id !== game.host) {
            const removeBtn = document.createElement('button');
            removeBtn.className = 'remove-player-btn';
            removeBtn.dataset.playerId = player.id;
            removeBtn.textContent = 'Remove';
            removeBtn.onclick = () => removePlayer(game.id, player.id);
            entry.appendChild(removeBtn);
        }
        playerList.appendChild(entry);
    }
}

async function load() {
    const sp = new URLSearchParams(window.location.search);
    const gameId = sp.get("id");

    let me = null;
    try {
        const meResp = await fetch('/userDetails');
        if (meResp.ok) {
            me = await meResp.json();
        }
    } catch (e) {
        console.error('Failed to fetch user details', e);
    }

    const gameResp = await fetch(`/v1/games/${gameId}`);
    if (gameResp.status == 401 || gameResp.status == 403) {
        window.alert("You're not a member of this game!");
        window.location.href = "/";
        return;
    }
    if (!gameResp.ok) {
        showGameError('Failed to load game. Please refresh.');
        return;
    }

    const game = await gameResp.json();
    document.getElementById("gameId").innerText = game.id;

    const userPromises = game.players.map(async pid => {
        try {
            const userResp = await fetch(`/v1/users/${encodeURIComponent(pid)}`);
            if (!userResp.ok) return { id: pid, username: 'Unknown' };
            const u = await userResp.json();
            return { id: pid, username: u.username };
        } catch (e) {
            console.error(e);
            return { id: pid, username: 'Unknown' };
        }
    });
    const players = await Promise.all(userPromises);
    renderPlayers(players, game, me);
}

async function removePlayer(gameId, playerId) {
    clearGameError();
    const resp = await fetch(`/v1/games/${gameId}/players/${playerId}`, {
        method: 'DELETE'
    });
    if (resp.ok) {
        await load();
    } else {
        const data = await resp.json().catch(() => ({}));
        showGameError(data.error || 'Failed to remove player. Please try again.');
    }
}
