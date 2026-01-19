async function load() {
    const sp = new URLSearchParams(window.location.search);
    const gameResp = await fetch(`/v1/games/${sp.get("id")}`);
    if (gameResp.status == 401 || gameResp.status == 403) {
        window.alert("You're not a member of this of this game!");
        window.location.href = "/";
    }
    if (gameResp.ok) {
        const game = await gameResp.json();
        document.getElementById("gameId").innerText = game.id;
        const playerList = document.getElementById("playerList");
        playerList.innerText =
            game.players.map(p => p.username).join(', ');
    }
}