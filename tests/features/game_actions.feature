Feature: Game turn actions
  As a player in a started game
  I want to take actions on my turn
  So that I can make progress towards winning

  Background:
    Given a started game with 2 players

  Scenario: Player takes ingredients from the bag and places them in a cup
    Given it is player 1's turn
    And player 1 has an empty cup 0
    And the bag contains no special tokens
    When player 1 takes 3 ingredients from the bag placing all in cup 0
    Then cup 0 should contain 3 ingredients
    And a move record should be created for the game
    And it should be player 2's turn


  Scenario: Player takes ingredients in two batches
    Given it is player 1's turn
    And the bag contains no special tokens
    When player 1 takes 1 ingredient from the bag
    Then it should be player 1's turn
    When player 1 takes 2 ingredients from the bag
    Then it should be player 2's turn
    And a move record should be created for the game

  Scenario: Player takes ingredients in two batches after player 1's go
    Given it is player 1's turn
    And the bag contains no special tokens
    When player 1 takes 3 ingredients from the bag
    Then it should be player 2's turn
    When player 2 takes 2 ingredients from the bag
    Then it should be player 2's turn
    When player 2 takes 1 ingredient from the bag
    Then it should be player 1's turn
    And a move record should be created for the game

  Scenario: Other actions are blocked while a take-ingredients batch is in progress
    Given it is player 1's turn
    And the bag contains no special tokens
    When player 1 takes 1 ingredient from the bag
    And player 1 goes for a wee
    Then the action should be rejected with a 409 error

  Scenario: Placing too many ingredients in a cup is rejected
    Given it is player 1's turn
    And player 1's cup 0 is full with 5 ingredients
    When player 1 tries to place an ingredient in cup 0
    Then the action should be rejected with a 400 error

  Scenario: Player sells a single-spirit drink for 1 point
    Given it is player 1's turn
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    When player 1 sells cup 0 with no declared specials
    Then player 1 should have 1 point
    And cup 0 should be empty
    And a move record should be created for the game

  Scenario: Player sells a double-spirit drink for 3 points
    Given it is player 1's turn
    And player 1's cup 0 contains 2 WHISKEY and 1 COLA
    When player 1 sells cup 0 with no declared specials
    Then player 1 should have 3 points

  Scenario: Player sells a Mojito cocktail for 10 points
    Given it is player 1's turn
    And player 1's cup 0 contains 2 RUM and 1 SODA
    And player 1 has "sugar" on their player mat
    When player 1 sells cup 0 declaring specials "sugar"
    Then player 1 should have 10 points
    And cup 0 should be empty

  Scenario: Selling an invalid cup combination is rejected
    Given it is player 1's turn
    And player 1's cup 0 contains 1 VODKA and 1 TONIC
    And player 1's cup 0 also contains 1 GIN
    When player 1 sells cup 0 with no declared specials
    Then the action should be rejected with a 400 error

  Scenario: Player drinks a cup
    Given it is player 1's turn
    And player 1's cup 0 contains 1 WHISKEY and 1 COLA
    When player 1 drinks cup 0
    Then player 1's bladder should contain 2 ingredients
    And player 1's drunk level should be 1
    And cup 0 should be empty

  Scenario: Player goes for a wee
    Given it is player 1's turn
    And player 1 has 3 ingredients in their bladder
    And player 1 has a drunk level of 2
    When player 1 goes for a wee
    Then player 1's bladder should be empty
    And player 1's drunk level should be 1
    And player 1's toilet tokens should decrease by 1
    And a move record should be created for the game

  Scenario: Player claims a card they can afford
    Given it is player 1's turn
    And a card with cost 1 mixer is available in row 1
    And player 1 has 1 mixer in their bladder
    When player 1 claims that card
    Then player 1 should have 1 card
    And a move record should be created for the game

  Scenario: Player cannot claim a card they cannot afford
    Given it is player 1's turn
    And a card with cost 2 spirits is available in row 1
    And player 1 has 0 spirits in their bladder
    When player 1 tries to claim that card
    Then the action should be rejected with a 400 error

  Scenario: Player refreshes a card row when drunk enough
    Given it is player 1's turn
    And player 1 has a drunk level of 3
    When player 1 refreshes card row 1
    Then row 1 should be refreshed with new cards
    And a move record should be created for the game

  Scenario: Player cannot refresh a card row when not drunk enough
    Given it is player 1's turn
    And player 1 has a drunk level of 2
    When player 1 tries to refresh card row 1
    Then the action should be rejected with a 400 error

  Scenario: Only the active player can take actions
    Given it is player 1's turn
    When player 2 tries to take an ingredient
    Then the action should be rejected with a 409 error

  Scenario: Player wins by reaching 40 points
    Given it is player 1's turn
    And player 1 has 37 points
    And player 1's cup 0 contains 1 GIN, 1 VODKA, 1 TEQUILA, 1 RUM and 1 COLA
    And player 1 has "sugar" and "lemon" on their player mat
    When player 1 sells cup 0 declaring specials "sugar,lemon"
    Then the game should be over
    And player 1 should be the winner
