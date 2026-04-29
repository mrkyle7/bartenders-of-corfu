Feature: Game modes
  As a host
  I want to enable optional rule variations in the lobby
  So that I can play test variations of the game

  Scenario: Host enables sell_both_cups mode in the lobby
    Given a new game with 2 players in the lobby
    When the host enables the "sell_both_cups" game mode
    Then the request should succeed
    And the game's enabled modes should include "sell_both_cups"

  Scenario: Host disables a previously-enabled mode
    Given a new game with 2 players in the lobby
    And the host has enabled the "sell_both_cups" game mode
    When the host clears all game modes
    Then the request should succeed
    And the game should have no enabled modes

  Scenario: Non-host cannot change game modes
    Given a new game with 2 players in the lobby
    When the non-host tries to enable the "sell_both_cups" game mode
    Then the action should be rejected with a 403 error

  Scenario: Unknown game modes are rejected
    Given a new game with 2 players in the lobby
    When the host tries to enable the "definitely_not_a_real_mode" game mode
    Then the action should be rejected with a 400 error

  Scenario: Game modes are locked once the game starts
    Given a started game with 2 players
    When the host tries to enable the "sell_both_cups" game mode after start
    Then the action should be rejected with a 409 error

  Scenario: Selected game modes persist into the started game
    Given a new game with 2 players in the lobby
    And the host has enabled the "sell_both_cups" game mode
    When the host starts the game
    Then the started game's enabled modes should include "sell_both_cups"

  Scenario: Available game modes are advertised by the API
    When the available game modes are listed
    Then the list should include "sell_both_cups"

  # ── Sell both cups action ──────────────────────────────────────────────────

  Scenario: Player sells both cups in one action when sell_both_cups mode is on
    Given a started game with 2 players and sell_both_cups mode enabled
    And it is player 1's turn
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    And player 1's cup 1 contains 2 WHISKEY and 1 COLA
    When player 1 sells both cups with no declared specials
    Then player 1 should have 4 points
    And cup 0 should be empty
    And player 1's cup 1 should be empty
    And it should be player 2's turn

  Scenario: Sell-both action is rejected when sell_both_cups mode is off
    Given a started game with 2 players
    And it is player 1's turn
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    And player 1's cup 1 contains 2 WHISKEY and 1 COLA
    When player 1 tries to sell both cups with no declared specials
    Then the action should be rejected with a 400 error

  Scenario: Sell-both rejects an invalid cup combination on either cup
    Given a started game with 2 players and sell_both_cups mode enabled
    And it is player 1's turn
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    And player 1's cup 1 contains 1 GIN and 1 COLA
    When player 1 tries to sell both cups with no declared specials
    Then the action should be rejected with a 400 error
    And player 1 should have 0 points

  Scenario: Sell-both rejects when the same special is declared on both cups
    Given a started game with 2 players and sell_both_cups mode enabled
    And it is player 1's turn
    And player 1's cup 0 contains 2 RUM and 1 SODA
    And player 1's cup 1 contains 2 RUM and 1 SODA
    And player 1 has "sugar" on their player mat
    When player 1 tries to sell both cups declaring sugar on each
    Then the action should be rejected with a 400 error

  Scenario: Sell-both with the same cup_index twice is rejected
    Given a started game with 2 players and sell_both_cups mode enabled
    And it is player 1's turn
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    When player 1 tries to sell cup 0 twice in one action
    Then the action should be rejected with a 400 error

  Scenario: Sell-both counts as a single main action (turn advances once)
    Given a started game with 2 players and sell_both_cups mode enabled
    And it is player 1's turn
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    And player 1's cup 1 contains 1 RUM and 1 COLA
    When player 1 sells both cups with no declared specials
    Then it should be player 2's turn
    And a move record should be created for the game
