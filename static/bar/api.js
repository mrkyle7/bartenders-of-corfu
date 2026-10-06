// Thin fetch wrappers for the Table View UI. Every call resolves to parsed
// JSON or throws ApiError with a user-safe message.

export class ApiError extends Error {
    constructor(message, status) {
        super(message);
        this.status = status;
    }
}

async function request(path, options = {}) {
    let resp;
    try {
        resp = await fetch(path, {
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
    } catch {
        throw new ApiError('Connection problem — check your network and try again.', 0);
    }
    if (resp.status === 401) {
        window.location.href = '/login';
        throw new ApiError('Please log in.', 401);
    }
    let data = null;
    try {
        data = await resp.json();
    } catch {
        // non-JSON body; fall through
    }
    if (!resp.ok) {
        throw new ApiError(data?.error ?? 'Something went wrong — please try again.', resp.status);
    }
    return data;
}

const get = (path) => request(path);
const post = (path, body) => request(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
const patch = (path, body) => request(path, { method: 'PATCH', body: JSON.stringify(body) });
const del = (path) => request(path, { method: 'DELETE' });

export const api = {
    me: () => get('/userDetails'),
    user: (id) => get(`/v1/users/${id}`),
    game: (id) => get(`/v1/games/${id}`),
    validActions: (id) => get(`/v1/games/${id}/valid-actions`),
    history: (id) => get(`/v1/games/${id}/history`),
    stateAtTurn: (id, turn) => get(`/v1/games/${id}/history/${turn}`),
    botStrategies: () => get('/v1/bot-strategies'),
    gameModes: () => get('/v1/game-modes'),

    join: (id) => post(`/v1/games/${id}/join`),
    addBot: (id, strategy) => post(`/v1/games/${id}/add-bot`, { strategy }),
    removePlayer: (id, playerId) => del(`/v1/games/${id}/players/${playerId}`),
    setModes: (id, modes) => patch(`/v1/games/${id}/modes`, { game_modes: modes }),
    start: (id) => post(`/v1/games/${id}/start`),

    drawFromBag: (id, count) => post(`/v1/games/${id}/actions/draw-from-bag`, { count }),
    takeIngredients: (id, assignments) => post(`/v1/games/${id}/actions/take-ingredients`, { assignments }),
    sellCup: (id, body) => post(`/v1/games/${id}/actions/sell-cup`, body),
    drinkCup: (id, cupIndex) => post(`/v1/games/${id}/actions/drink-cup`, { cup_index: cupIndex }),
    goForAWee: (id) => post(`/v1/games/${id}/actions/go-for-a-wee`),
    claimCard: (id, body) => post(`/v1/games/${id}/actions/claim-card`, body),
    drinkStoredSpirit: (id, cardIndex, count) => post(`/v1/games/${id}/actions/drink-stored-spirit`, { store_card_index: cardIndex, count }),
    useStoredSpirit: (id, cardIndex, cupIndex) => post(`/v1/games/${id}/actions/use-stored-spirit`, { store_card_index: cardIndex, cup_index: cupIndex }),
    rerollSpecials: (id, chosen) => post(`/v1/games/${id}/actions/reroll-specials`, { chosen_specials: chosen }),
    refreshCardRow: (id, row) => post(`/v1/games/${id}/actions/refresh-card-row`, { row_position: row }),
    endTurn: (id) => post(`/v1/games/${id}/actions/end-turn`),
    quit: (id) => post(`/v1/games/${id}/actions/quit`),
    cancel: (id) => post(`/v1/games/${id}/cancel`),
    proposeUndo: (id) => post(`/v1/games/${id}/undo`),
    voteUndo: (id, requestId, vote) => post(`/v1/games/${id}/undo/vote`, { request_id: requestId, vote }),
};
