Feature: Undo turn
  As a group of players
  We want to be able to undo the last completed turn
  So that mistakes can be corrected when everyone agrees

  Background:
    Given a started game with 2 players
    And player 1 has completed a turn

  Scenario: Any player can propose an undo
    When player 1 proposes to undo the last turn
    Then an undo request should be pending for the game
    And player 1's vote should be recorded as agree

  Scenario: All players agreeing executes the undo
    Given player 1 has proposed to undo the last turn
    When player 2 votes agree on the undo
    Then the undo request should be approved
    And the game state should be restored to before the last turn

  Scenario: Any player disagreeing rejects the undo
    Given player 1 has proposed to undo the last turn
    When player 2 votes disagree on the undo
    Then the undo request should be rejected
    And the game state should remain unchanged

  Scenario: A player cannot vote twice on the same undo request
    Given player 1 has proposed to undo the last turn
    When player 1 tries to vote again on the undo
    Then the action should be rejected with a 409 error

  Scenario: Only one undo proposal is allowed at a time
    Given player 1 has proposed to undo the last turn
    When player 2 also tries to propose an undo
    Then the action should be rejected with a 409 error

  Scenario: Cannot propose undo when there are no moves
    Given a started game with 2 players and no moves yet
    When player 1 proposes to undo the last turn
    Then the action should be rejected with a 409 error

  Scenario: Move history is available after actions
    When player 1 fetches the move history
    Then the history should contain 1 move
    And the move should record the action type and player

  Scenario: Game state can be replayed to any turn
    When player 1 requests the state at turn 0
    Then the returned state should be the initial game state

  Scenario: An eliminated player cannot propose an undo
    Given player 2 is eliminated
    When player 2 proposes to undo the last turn
    Then the action should be rejected with a 409 error

  Scenario: Undo approval threshold excludes eliminated players
    Given player 2 is eliminated
    And player 1 has proposed to undo the last turn
    When player 2 votes agree on the undo
    Then the undo request should be approved
