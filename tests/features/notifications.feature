Feature: Notifications
  Players who turned notifications on hear when it's their turn, unless
  they're looking at the game: game pages only poll while they're showing,
  and say when they're hidden.

  Background:
    Given a started game with 2 players
    And player 2 has turned on notifications

  Scenario: The next player is told it's their turn
    Given player 2 is not looking at the game
    And player 1 has completed a turn
    Then player 2 should be sent a notification saying "It's your turn"

  Scenario: A player looking at the game is not told
    Given player 2 is looking at the game
    And player 1 has completed a turn
    Then player 2 should not be sent a notification

  Scenario: Nobody is told while the turn stays with the same player
    Given player 2 is not looking at the game
    And the bag contains no special tokens
    When player 1 takes 1 ingredient from the bag
    Then player 2 should not be sent a notification

  Scenario: A device on the server's own network is refused
    When player 2 turns on notifications for "https://127.0.0.1/push"
    Then the action should be rejected with a 400 error

  Scenario: Only the owner can turn a device's notifications off
    When player 1 turns off player 2's notifications
    Then player 2 should still have notifications on
