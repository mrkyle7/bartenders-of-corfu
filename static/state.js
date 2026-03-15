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
    lastKnownTurn: null,   // player_turn UUID from last render (for notification detection)

    // Modal state (cup doubler still uses modal)
    cupDoublerCard:      null,
    cupDoublerCardEl:    null,
    currentGs:           null,  // latest rendered game state

    // Staging area state (inline take ingredients flow)
    stagingItems:        [],    // [{ingredient, source:'display'|'pending', idx?, disposition?, cup_index?}]
    stagingActive:       false, // true when staging area is visible
    stagingTakeCount:    0,     // total items to take this turn
    stagingAlreadyTaken: 0,     // items already taken in previous batches
};

export default state;
