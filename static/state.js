/**
 * state.js — Centralised mutable state for the game UI.
 * Vanilla ES2022.
 */

const state = {
    gameId:        null,
    game:          null,   // live game object from API
    me:            null,   // current user {id, username}
    players:       {},     // map pid → {id, username}
    pollTimer:     null,
    replayMode:    false,
    replayTurns:   [],     // list of turn numbers from history
    replayCursor:  -1,     // index into _replayTurns (-1 = live)
    historyMoves:  [],     // cached moves from /history
    pendingUndo:   null,   // current pending undo request object

    // Modal state
    takeStep:           0,   // 0 = pick, 1 = assign
    takeDisplaySelected: [], // [{ingredient, source:'display', idx}]
    takeBagPending:      [], // [{ingredient, source:'pending'}]
    sellCupIndex:        null,
    drinkCupIndex:       null,
    cupDoublerCard:      null,
    cupDoublerCardEl:    null,
    currentGs:           null,  // latest rendered game state (for modal use)
};

export default state;
