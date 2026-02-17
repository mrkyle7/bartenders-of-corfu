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
        const players = []
        const userPromises = game.players.map(async p => {
            try {
                const userResp = await fetch(`/v1/users/${encodeURIComponent(p)}`);
                if (!userResp.ok) throw new Error(`Failed to fetch user ${p}: ${userResp.status}`);
                return await userResp.json();
            } catch (e) {
                console.error(e);
                return null;
            }
        });
        const resolved = (await Promise.all(userPromises)).filter(Boolean);
        players.push(...resolved);
        playerList.innerText =
            players.map(p => p.username).join(', ');
    }
}