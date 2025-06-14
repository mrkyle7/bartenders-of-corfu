// Function to create a new game
async function createNewGame() {
    const response = await fetch('/v1/games', {
        method: 'POST'
    });
    const data = await response.json();
    console.log("Created Game ID:", data.id);
    listGames();
}

async function listGames() {
    const response = await fetch('/v1/games');
    const data = await response.json();
    const gameList = document.getElementById('gameList');
    gameList.innerHTML = '';
    data.games.forEach(game => {
        const li = document.createElement('li');
        li.textContent = `Game ID: ${game.id}`;
        gameList.appendChild(li);
    });
}