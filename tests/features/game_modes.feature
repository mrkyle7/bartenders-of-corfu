Feature: Former game modes
  As a player
  I want the rules that used to be lobby options to just be the rules
  So that every game plays the same way

  # Selling both glasses and claiming a card as a free action are standard
  # rules now, and re-rolling specials is gone. The lobby offers no modes.

  Scenario: No optional game modes are advertised
    When the available game modes are listed
    Then the list should be empty

  Scenario: Retired game modes are rejected in the lobby
    Given a new game with 2 players in the lobby
    When the host tries to enable the "sell_both_cups" game mode
    Then the action should be rejected with a 400 error

  Scenario: Unknown game modes are rejected
    Given a new game with 2 players in the lobby
    When the host tries to enable the "definitely_not_a_real_mode" game mode
    Then the action should be rejected with a 400 error

  Scenario: Non-host cannot change game modes
    Given a new game with 2 players in the lobby
    When the non-host tries to enable the "sell_both_cups" game mode
    Then the action should be rejected with a 403 error

  Scenario: Game modes are locked once the game starts
    Given a started game with 2 players
    When the host tries to enable the "sell_both_cups" game mode after start
    Then the action should be rejected with a 409 error

  # ── Selling both glasses ───────────────────────────────────────────────────

  Scenario: Player sells both glasses in one action
    Given a started game with 2 players
    And it is player 1's turn
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    And player 1's cup 1 contains 2 WHISKEY and 1 COLA
    When player 1 sells both cups with no declared specials
    Then player 1 should have 4 points
    And cup 0 should be empty
    And player 1's cup 1 should be empty
    And it should be player 2's turn

  Scenario: Selling both rejects an invalid cup combination on either cup
    Given a started game with 2 players
    And it is player 1's turn
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    And player 1's cup 1 contains 1 GIN and 1 COLA
    When player 1 tries to sell both cups with no declared specials
    Then the action should be rejected with a 400 error
    And player 1 should have 0 points

  Scenario: Selling both rejects the same special declared on both cups
    Given a started game with 2 players
    And it is player 1's turn
    And player 1's cup 0 contains 2 RUM and 1 SODA
    And player 1's cup 1 contains 2 RUM and 1 SODA
    And player 1 has "sugar" on their player mat
    When player 1 tries to sell both cups declaring sugar on each
    Then the action should be rejected with a 400 error

  Scenario: Selling the same cup twice in one action is rejected
    Given a started game with 2 players
    And it is player 1's turn
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    When player 1 tries to sell cup 0 twice in one action
    Then the action should be rejected with a 400 error

  # ── Claiming a card is a free action ───────────────────────────────────────

  Scenario: Claiming a card is a free action
    Given a started game with 2 players
    And it is player 1's turn
    And player 1's bladder has 1 VODKA spirit
    And a store card is available in row 3
    When player 1 claims that card
    Then the request should succeed
    And the claim should be recorded as a free action
    And it should still be player 1's turn

  Scenario: A take in progress blocks a claim
    Given a started game with 2 players
    And it is player 1's turn
    And player 1's bladder has 1 VODKA spirit
    And a store card is available in row 3
    And player 1 has a take in progress with 1 ingredient already taken
    When player 1 tries to claim that card
    Then the action should be rejected with a 409 error

  # ── Re-rolling specials is gone ────────────────────────────────────────────

  Scenario: Re-rolling specials is rejected
    Given a started game with 2 players
    And it is player 1's turn
    And player 1 has "lemon" on their player mat
    When player 1 tries to re-roll specials "lemon"
    Then the action should be rejected with a 400 error
