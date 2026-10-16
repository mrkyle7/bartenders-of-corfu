Feature: Telling the owner when players come back
  As the owner of Cheetah Moon Games
  I want a notification when someone signs in or opens a game
  But only once when they arrive, not for everything they do

  Background:
    Given the owner gets login alerts on their phone

  Scenario: Signing in after a long time away is reported
    Given a player who was last seen 7 hours ago
    When the player signs in
    Then the owner is told "Signed in to Cheetah Moon Games"

  Scenario: A new account is reported
    When a new player makes an account
    Then the owner is told "Made a Cheetah Moon account"

  Scenario: Opening another game with a saved sign-in is reported
    Given a player who was last seen 7 hours ago
    When the player opens "bezique"
    Then the response status should be 202
    And the owner is told "Opened Bezique"

  Scenario: Playing Bartenders is reported once, not for every page and move
    Given a player who was last seen 7 hours ago
    When the player opens Bartenders pages 5 times
    Then the owner is told "Opened Bartenders of Corfu"
    And the owner was told once

  Scenario: Opening cheetahmoongames.com with a saved sign-in is reported
    Given a player who was last seen 7 hours ago
    When the player opens cheetahmoongames.com
    Then the owner is told "Opened cheetahmoongames.com"

  Scenario: Coming back within 6 hours isn't reported
    Given a player who was last seen 2 hours ago
    When the player signs in
    And the player opens "bezique"
    Then the owner is told nothing

  Scenario: The owner's own visits aren't reported
    When the owner opens "bezique"
    Then the owner is told nothing

  Scenario: Only a signed-in player can be reported
    When someone without a sign-in reports opening "bezique"
    Then the response status should be 401
    And the owner is told nothing

  Scenario: The place must look like a game's name
    Given a player who was last seen 7 hours ago
    When the player opens "<b>hello</b>"
    Then the response status should be 400
    And the owner is told nothing

  Scenario: A game reports a guest it vouches for
    When The Boxer reports a guest called "Bob"
    Then the response status should be 202
    And the owner is told "Opened The Boxer" by "Guest Bob is here"

  Scenario: The same guest coming and going within 6 hours is reported once
    When The Boxer reports a guest called "Bob"
    And a while later The Boxer reports a guest called "Bob"
    Then the owner was told once

  Scenario: Only our games can report guests
    When something that isn't one of our games reports a guest called "Bob"
    Then the response status should be 401
    And the owner is told nothing
