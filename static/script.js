let user;

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
}

function setUser(user) {
    document.getElementById('loginLink').classList.add('hidden');
    const helloUser = document.getElementById('helloUser');
    helloUser.classList.remove("hidden");
    helloUser.innerText = `Hello ${user.username} | `;
    document.getElementById('logoutLink').classList.remove('hidden');
}

// Function to create a new game
async function createNewGame() {
    const response = await fetch('/v1/games', {
        method: 'POST'
    });
    if (response.status == 401) {
        window.location.href = '/login';
    }
    const data = await response.json();
    console.log("Created Game ID:", data.id);
    listGames();
}

async function listGames() {
    const response = await fetch('/v1/games');
    const data = await response.json();
    const gameList = document.getElementById('gameList');
    gameList.innerHTML = '';
    data.games.forEach(async game => {
        const li = document.createElement('li');
        let host = 'Unknown';
        try {
            const userResp = await fetch(`/v1/users/${game.host}`)
            const user = await userResp.json()
            host = user.username
        } catch (e) {
            console.error(e)
        }
        li.textContent = `${host}'s Game: ${game.id}, players: ${game.players.join(', ')}`;
        if (game.players.some(p => p === user.id)) {
            const goToGameButton = document.createElement('button');
            goToGameButton.textContent = 'Go to Game';
            goToGameButton.onclick = () => window.location.href = `/game?id=${game.id}`;
            li.appendChild(goToGameButton);
        } else {
            const joinButton = document.createElement('button');
            joinButton.textContent = 'Join Game';
            joinButton.onclick = () => joinGame(game.id);
            li.appendChild(joinButton);
        }
        gameList.appendChild(li);
    });
}

async function joinGame(gameId) {
    const response = await fetch(`/v1/games/${gameId}/join`, {
        method: 'POST'
    });
    if (response.status == 401) {
        window.location.href = '/login';
    }
    if (response.ok) {
        listGames(); // Refresh the game list
    } else {
        const data = await response.json();
        alert(`Failed to join game: ${data.error}`);
    }
}

async function setLogOutLink() {
    document.getElementById('logoutLink').addEventListener('click', async (e) => {
        e.preventDefault();
        try {
            const response = await fetch('/logout', {
                method: 'POST'
            });
            if (response.ok) {
                await setUserHeader();
            }
        } catch (error) {
            console.error('Logout failed:', error);
        }
    });
}
