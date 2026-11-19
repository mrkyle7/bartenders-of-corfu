Feature: Undo moves
  As a group of players
  We want to be able to take back moves, one at a time
  So that mistakes can be corrected when everyone agrees

  Background:
    Given a started game with 2 players
    And player 1 has completed a turn

  Scenario: Any player can propose an undo
    When player 1 proposes to undo the last move
    Then an undo request should be pending for the game
    And player 1's vote should be recorded as agree

  Scenario: All players agreeing executes the undo
    Given player 1 has proposed to undo the last move
    When player 2 votes agree on the undo
    Then the undo request should be approved
    And the game state should be restored to before the last move

  Scenario: Any player disagreeing rejects the undo
    Given player 1 has proposed to undo the last move
    When player 2 votes disagree on the undo
    Then the undo request should be rejected
    And the game state should remain unchanged

  Scenario: A player cannot vote twice on the same undo request
    Given player 1 has proposed to undo the last move
    When player 1 tries to vote again on the undo
    Then the action should be rejected with a 409 error

  Scenario: Only one undo proposal is allowed at a time
    Given player 1 has proposed to undo the last move
    When player 2 also tries to propose an undo
    Then the action should be rejected with a 409 error

  Scenario: Cannot propose undo when there are no moves
    Given a started game with 2 players and no moves yet
    When player 1 proposes to undo the last move
    Then the action should be rejected with a 409 error

  Scenario: Move history is available after actions
    When player 1 fetches the move history
    Then the history should contain the completed turn's moves
    And the moves should record the action type and player

  Scenario: Game state can be replayed to any turn
    When player 1 requests the state at turn 0
    Then the returned state should be the initial game state

  Scenario: An eliminated player cannot propose an undo
    Given player 2 is eliminated
    When player 2 proposes to undo the last move
    Then the action should be rejected with a 409 error

  Scenario: Undo approval threshold excludes eliminated players
    Given player 2 is eliminated
    And player 1 has proposed to undo the last move
    When player 2 votes agree on the undo
    Then the undo request should be approved
  
  Scenario: Undoing a move restores the previous game state when claiming a store card
    Given player 2 has completed a turn
    And it is player 1's turn
    And a store card is available in row 2
    And player 1 has 3 spirits in their bladder
    When player 1 claims that card
    Then player 1 should have 1 card
    And player 1's store card should have 3 stored spirits
    And player 1's bladder should be empty
    Given player 1 has proposed to undo the last move
    When player 2 votes agree on the undo
    Then player 1 should have 0 cards
    And player 1 has 3 spirits in their bladder
    And a store card is available in row 2

  Scenario: An undo takes back only the last move, not the whole turn
    Given it is player 2's turn
    When the game state is recorded
    And player 2 draws 2 ingredients from the bag
    And player 2 proposes an undo and player 1 agrees
    Then the game should be back to the recorded state
    And player 2 should have no ingredients waiting to be assigned

  Scenario: Undos can be made one after another to take back several moves
    Given it is player 2's turn
    When the game state is recorded
    And player 2 draws 3 ingredients from the bag
    And player 2 drinks the drawn ingredients
    And player 2 ends their turn if it is still open
    And player 2 takes back each of those moves one at a time, with player 1 agreeing
    Then player 2 should have no ingredients waiting to be assigned
    And the game should be back to the recorded state

  Scenario: Making a taken-back bag draw again gets the same ingredients
    Given it is player 2's turn
    When player 2 draws 2 ingredients from the bag
    And player 2 proposes an undo and player 1 agrees
    And player 2 draws 2 ingredients from the bag
    Then the second draw should match the first

  Scenario: Taken-back draws come out again even after several undos
    Given it is player 2's turn
    When player 2 draws 3 ingredients from the bag
    And player 2 drinks the drawn ingredients
    And player 2 ends their turn if it is still open
    And player 2 takes back each of those moves one at a time, with player 1 agreeing
    And player 2 draws 3 ingredients from the bag
    Then the second draw should match the first

  Scenario: Once the turn ends the bag is random again
    Given it is player 2's turn
    When player 2 draws 3 ingredients from the bag
    And player 2 proposes an undo and player 1 agrees
    And player 2 draws 3 ingredients from the bag
    And player 2 drinks the drawn ingredients
    And player 2 ends their turn if it is still open
    Then the bag should not remember any draws

  Scenario: A move made while an undo is pending cancels the undo
    Given it is player 2's turn
    When player 2 draws 3 ingredients from the bag
    And player 1 proposes to undo the last move
    And player 2 drinks the drawn ingredients
    Then the undo request should no longer be pending
