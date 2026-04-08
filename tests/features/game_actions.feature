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

  Scenario: Player takes ingredients from the open display and places them in a cup
    Given it is player 1's turn
    And player 1 has an empty cup 0
    And the open display contains 5 COLA
    When player 1 takes 3 COLA from the open display placing all in cup 0
    Then cup 0 should contain exactly 3 COLA
    And a move record should be created for the game
    And it should be player 2's turn

  Scenario: Player takes special ingredients from the open display which gets placed on their player mat
    Given it is player 1's turn
    And player 1 has an empty cup 0
    And player 1 has no special tokens on their player mat
    And the open display contains 4 COLA and 1 SPECIAL
    When player 1 takes 1 special from the open display and rolls BITTERS
    Then player 1's player mat should have 1 BITTERS
    And it should be player 1's turn
    When player 1 takes 2 COLA from the open display placing all in cup 0
    Then cup 0 should contain exactly 2 COLA
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

  Scenario: Multi-batch take records all ingredients in the history payload
    Given it is player 1's turn
    And the bag contains no special tokens
    When player 1 takes 1 ingredient from the bag
    And player 1 takes 2 ingredients from the bag
    Then the move history should record 3 taken ingredients

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
    And the bag contains no special tokens
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
    And a refresher card is available in row 1
    And player 1 has 2 mixers in their bladder
    When player 1 claims that card
    Then player 1 should have 1 card
    And a move record should be created for the game

  Scenario: Claiming a karaoke card replaces the slot from the deck
    Given it is player 1's turn
    And a karaoke card is available in row 1
    And player 1 has 3 spirits in their bladder
    When player 1 claims that card
    Then player 1 should have 1 card
    And row 1 should have 4 cards

  Scenario: Player cannot claim a card they cannot afford
    Given it is player 1's turn
    And a store card is available in row 1
    And player 1 has 0 spirits in their bladder
    When player 1 tries to claim that card
    Then the action should be rejected with a 400 error

  Scenario: Player refreshes a card row when drunk enough
    Given it is player 1's turn
    And player 1 has a drunk level of 3
    When player 1 refreshes card row 2
    Then row 2 should be refreshed with new cards
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

  Scenario: Reaching 40 points triggers last round, not instant win
    Given it is player 1's turn
    And player 1 has 37 points
    And player 1's cup 0 contains 1 GIN, 1 VODKA, 1 TEQUILA, 1 RUM and 1 COLA
    And player 1 has "sugar" and "lemon" on their player mat
    When player 1 sells cup 0 declaring specials "sugar,lemon"
    Then the last round should be active
    And it should be player 2's turn
    And the game should not be over

  Scenario: Game ends after last round completes with equal turns
    Given it is player 1's turn
    And player 1 has 37 points
    And player 1's cup 0 contains 1 GIN, 1 VODKA, 1 TEQUILA, 1 RUM and 1 COLA
    And player 1 has "sugar" and "lemon" on their player mat
    And player 2 has 1 ingredients in their bladder
    When player 1 sells cup 0 declaring specials "sugar,lemon"
    Then the last round should be active
    When player 2 goes for a wee
    Then the game should be over
    And player 1 should be the winner

  Scenario: Last player in turn order reaching 40 ends the game immediately
    Given it is player 1's turn
    And player 1 has 1 ingredients in their bladder
    And player 2 has 37 points
    And player 2's cup 0 contains 1 GIN, 1 VODKA, 1 TEQUILA, 1 RUM and 1 COLA
    And player 2 has "sugar" and "lemon" on their player mat
    When player 1 goes for a wee
    And player 2 sells cup 0 declaring specials "sugar,lemon"
    Then the game should be over
    And player 2 should be the winner

  Scenario: During last round another player scores higher and wins
    Given it is player 1's turn
    And player 1 has 37 points
    And player 1's cup 0 contains 1 GIN, 1 VODKA, 1 TEQUILA, 1 RUM and 1 COLA
    And player 1 has "sugar" and "lemon" on their player mat
    And player 2 has 38 points
    And player 2's cup 0 contains 1 GIN, 1 VODKA, 1 TEQUILA, 1 RUM and 1 COLA
    And player 2 has "sugar" and "lemon" on their player mat
    When player 1 sells cup 0 declaring specials "sugar,lemon"
    Then the last round should be active
    When player 2 sells cup 0 declaring specials "sugar,lemon"
    Then the game should be over
    And player 2 should be the winner

  Scenario: Karaoke win during last round is instant
    Given it is player 1's turn
    And player 1 has 37 points
    And player 1's cup 0 contains 1 GIN, 1 VODKA, 1 TEQUILA, 1 RUM and 1 COLA
    And player 1 has "sugar" and "lemon" on their player mat
    And player 2 has claimed 2 karaoke cards
    And a karaoke card is available in row 1
    And player 2 has 3 spirits in their bladder
    When player 1 sells cup 0 declaring specials "sugar,lemon"
    Then the last round should be active
    When player 2 claims that card
    Then the game should be over
    And player 2 should be the winner

  Scenario: Last player standing wins when opponent is hospitalised
    Given it is player 1's turn
    And player 1 has 1 ingredients in their bladder
    And player 2 has a drunk level of 5
    And player 2's cup 0 contains 1 WHISKEY and 1 COLA
    When player 1 goes for a wee
    And player 2 drinks cup 0
    Then the game should be over
    And player 1 should be the winner

  Scenario: Last player standing wins when opponent's bladder overflows
    Given it is player 1's turn
    And player 1 has 1 ingredients in their bladder
    And player 2 has 8 ingredients in their bladder
    And player 2's cup 0 contains 1 COLA and 1 SODA
    When player 1 goes for a wee
    And player 2 drinks cup 0
    Then the game should be over
    And player 1 should be the winner

  Scenario: Player wins by claiming the third karaoke card
    Given it is player 1's turn
    And player 1 has claimed 2 karaoke cards
    And a karaoke card is available in row 1
    And player 1 has 3 spirits in their bladder
    When player 1 claims that card
    Then the game should be over
    And player 1 should be the winner

  Scenario: RefreshCardRow is blocked while a take-ingredients batch is in progress
    Given it is player 1's turn
    And player 1 has a drunk level of 3
    And the bag contains no special tokens
    When player 1 takes 1 ingredient from the bag
    And player 1 tries to refresh card row 1
    Then the action should be rejected with a 409 error

  Scenario: SellCup is blocked while a take-ingredients batch is in progress
    Given it is player 1's turn
    And the bag contains no special tokens
    When player 1 takes 1 ingredient from the bag
    And player 1 tries to sell cup 0
    Then the action should be rejected with a 409 error

  Scenario: DrinkCup is blocked while a take-ingredients batch is in progress
    Given it is player 1's turn
    And the bag contains no special tokens
    When player 1 takes 1 ingredient from the bag
    And player 1 tries to drink cup 0
    Then the action should be rejected with a 409 error

  Scenario: ClaimCard is blocked while a take-ingredients batch is in progress
    Given it is player 1's turn
    And the bag contains no special tokens
    And a refresher card is available in row 1
    And player 1 has 2 mixers in their bladder
    When player 1 takes 1 ingredient from the bag
    And player 1 tries to claim that card
    Then the action should be rejected with a 409 error

  # ── Priority 1: Card type effects ────────────────────────────────────────────

  Scenario: Refresher card makes matching mixer subtract drunk even when spirits consumed
    Given it is player 1's turn
    And player 1 holds a COLA refresher card
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    When player 1 drinks cup 0
    Then player 1's drunk level should be 0

  Scenario: Store card transfers all matching bladder spirits to stored_spirits on claim
    Given it is player 1's turn
    And a store card is available in row 2
    And player 1 has 3 spirits in their bladder
    When player 1 claims that card
    Then player 1 should have 1 card
    And player 1's store card should have 3 stored spirits
    And player 1's bladder should be empty

  Scenario: Store card cost cannot be paid using same-type stored spirits
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 2 stored spirits
    And a store card is available in row 2
    And player 1 has 0 spirits in their bladder
    When player 1 tries to claim that card
    Then the action should be rejected with a 400 error

  Scenario: Karaoke card claim cannot use stored spirits toward the cost
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 1 stored spirit
    And player 1 has 2 spirits in their bladder
    And a karaoke card is available in row 1
    When player 1 claims that card
    Then the action should be rejected with a 400 error

  Scenario: CupDoubler doubles points for a non-cocktail sell
    Given it is player 1's turn
    And player 1's cup 0 has the cup doubler effect
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    When player 1 sells cup 0 with no declared specials
    Then player 1 should have 2 points

  Scenario: CupDoubler does not double points for a cocktail sell
    Given it is player 1's turn
    And player 1's cup 0 has the cup doubler effect
    And player 1's cup 0 contains 2 RUM and 1 SODA
    And player 1 has "sugar" on their player mat
    When player 1 sells cup 0 declaring specials "sugar"
    Then player 1 should have 10 points

  Scenario: Claiming a CupDoubler card without a cup_index is rejected
    Given it is player 1's turn
    And a cup doubler card is available in row 2
    And player 1 has 3 spirits in their bladder
    When player 1 tries to claim that cup doubler card without a cup_index
    Then the action should be rejected with a 400 error

  # ── Priority 2: Row and deck mechanics ───────────────────────────────────────

  Scenario: RefreshCardRow is blocked for row 1 even when player is drunk enough
    Given it is player 1's turn
    And player 1 has a drunk level of 3
    When player 1 tries to refresh card row 1
    Then the action should be rejected with a 400 error

  Scenario: Refreshing row 2 discards a karaoke card rather than returning it to row 1
    Given it is player 1's turn
    And player 1 has a drunk level of 3
    And a karaoke card is available in row 2
    When player 1 refreshes card row 2
    Then row 2 should be refreshed with new cards
    And the refreshed card should not appear in row 1

  Scenario: Claiming a card when the deck is empty leaves the row slot vacant
    Given it is player 1's turn
    And the deck is empty
    And a refresher card is available in row 2
    And player 1 has 2 mixers in their bladder
    When player 1 claims that card
    Then row 2 should have 2 cards

  Scenario: At game start row 1 has 3 karaoke cards and rows 2 and 3 have 3 cards each
    Given it is player 1's turn
    Then row 1 should have 3 cards
    And all cards in row 1 should be karaoke type
    And row 2 should have 3 cards
    And row 3 should have 3 cards
    And the deck should have 12 cards remaining

  # ── Priority 3: StoreCard ongoing effects ────────────────────────────────────

  Scenario: GoForAWee does not flush stored spirits from a Store card
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 2 stored spirits
    And player 1 has 3 ingredients in their bladder
    When player 1 goes for a wee
    Then player 1's bladder should be empty
    And player 1's store card should have 2 stored spirits

  # ── Priority 4: Tequila Slammer scoring ──────────────────────────────────────

  Scenario: Player sells a Tequila Slammer for 3 points
    Given it is player 1's turn
    And player 1's cup 0 contains 2 TEQUILA
    When player 1 sells cup 0 with no declared specials
    Then player 1 should have 3 points
    And cup 0 should be empty

  Scenario: Tequila with a mixer is not a valid drink and is rejected
    Given it is player 1's turn
    And player 1's cup 0 contains 2 TEQUILA and 1 COLA
    When player 1 sells cup 0 with no declared specials
    Then the action should be rejected with a 400 error

  # ── Priority 5: Edge cases ────────────────────────────────────────────────────

  Scenario: GoForAWee with no toilet tokens remaining still clears bladder and sobers up
    Given it is player 1's turn
    And player 1 has used all toilet tokens
    And player 1 has 3 ingredients in their bladder
    And player 1 has a drunk level of 2
    When player 1 goes for a wee
    Then player 1's bladder should be empty
    And player 1's drunk level should be 1
    And player 1's bladder capacity should be 4

  Scenario: bladder_capacity does not go below the minimum of 4
    Given it is player 1's turn
    And player 1 has used all toilet tokens
    And player 1 has 1 ingredients in their bladder
    When player 1 goes for a wee
    Then player 1's bladder capacity should be 4

  Scenario: GoForAWee is rejected with an empty bladder
    Given it is player 1's turn
    And player 1 has a drunk level of 2
    When player 1 goes for a wee
    Then the action should be rejected with a 409 error

  Scenario: TakeIngredients is rejected when bag and display have fewer than take_count ingredients
    Given it is player 1's turn
    And the bag and display together have fewer than 3 ingredients
    When player 1 tries to take an ingredient
    Then the action should be rejected with a 409 error

  Scenario: Game state at turn 1 reflects the state after the first completed turn
    Given player 1 has completed a turn
    When player 1 requests the state at turn 1
    Then the returned state should reflect turn 1

  Scenario: Requesting game state at a non-existent turn is rejected
    Given it is player 1's turn
    When player 1 requests the state at turn 999
    Then the action should be rejected with a 404 error

  Scenario: A player who is not a game member cannot access the move history
    Given player 1 has completed a turn
    When a non-member tries to fetch the move history
    Then the action should be rejected with a 403 error

  Scenario: Player 2 is eliminated when drunk and bladder limits are both exceeded simultaneously
    Given it is player 1's turn
    And player 1 has 1 ingredients in their bladder
    And player 2 has a drunk level of 5
    And player 2 has 8 ingredients in their bladder
    And player 2's cup 0 contains 1 WHISKEY and 1 COLA
    When player 1 goes for a wee
    And player 2 drinks cup 0
    Then player 2 should be eliminated
    And the game should be over
    And player 1 should be the winner

  Scenario: Eliminated player's bladder, cups, and store card spirits return to the bag
    Given it is player 1's turn
    And the bag contains no special tokens
    And player 1 has 1 ingredients in their bladder
    And player 2 has a drunk level of 5
    And player 2 has 0 ingredients in their bladder
    And player 2's cup 0 contains 1 WHISKEY
    And player 2's cup 1 contains 1 RUM and 1 COLA
    And player 2 holds a VODKA store card with 2 stored spirits
    And the current bag size is recorded
    When player 1 goes for a wee
    And player 2 drinks cup 0
    Then player 2 should be eliminated
    And player 2's bladder should be empty
    And player 2's cup 0 should be empty
    And player 2's cup 1 should be empty
    And player 2's store card should have 0 stored spirits
    And the bag should contain 6 more ingredients than before

  Scenario: Ingredients return to the bag when a player is eliminated by bladder overflow
    Given it is player 1's turn
    And the bag contains no special tokens
    And player 1 has 1 ingredients in their bladder
    And player 2 has 8 ingredients in their bladder
    And player 2's cup 0 contains 1 COLA and 1 SODA
    And player 2's cup 1 contains 1 TONIC
    And the current bag size is recorded
    When player 1 goes for a wee
    And player 2 drinks cup 0
    Then player 2 should be eliminated
    And player 2's bladder should be empty
    And player 2's cup 0 should be empty
    And player 2's cup 1 should be empty
    And the bag should contain 12 more ingredients than before

  Scenario: Ingredients return to the bag when a player quits
    Given it is player 1's turn
    And the bag contains no special tokens
    And player 1 has 2 ingredients in their bladder
    And player 1's cup 0 contains 1 GIN and 1 TONIC
    And player 1 holds a VODKA store card with 1 stored spirit
    And the current bag size is recorded
    When player 1 quits the game
    Then player 1's bladder should be empty
    And player 1's cup 0 should be empty
    And player 1's store card should have 0 stored spirits
    And the bag should contain 5 more ingredients than before

  # ── Drink Stored Spirit ──────────────────────────────────────────────────────

  Scenario: Drink stored spirit increases drunk level and adds to bladder
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 3 stored spirits
    And player 1 has a drunk level of 0
    When player 1 drinks 2 stored spirits from card 0
    Then player 1's drunk level should be 2
    And player 1's bladder should contain 2 ingredients
    And player 1's store card should have 1 stored spirit
    And it should still be player 1's turn

  Scenario: Drink stored spirit rejected when card has no spirits
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 0 stored spirits
    When player 1 tries to drink 1 stored spirit from card 0
    Then the action should be rejected with a 400 error

  Scenario: Drink stored spirit rejected for non-store card
    Given it is player 1's turn
    And player 1 holds a COLA refresher card
    When player 1 tries to drink 1 stored spirit from card 0
    Then the action should be rejected with a 400 error

  Scenario: Drink stored spirit rejected when not your turn
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 2 stored spirits
    When player 2 tries to drink 1 stored spirit from card 0
    Then the action should be rejected with a 409 error

  # ── Use Stored Spirit ────────────────────────────────────────────────────────

  Scenario: Use stored spirit moves spirit from store card to cup
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 2 stored spirits
    And player 1 has an empty cup 0
    When player 1 uses a stored spirit from card 0 into cup 0
    Then player 1's cup 0 should contain 1 ingredients
    And player 1's store card should have 1 stored spirit
    And it should still be player 1's turn

  Scenario: Use stored spirit rejected when cup is full
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 1 stored spirit
    And player 1's cup 0 contains 5 VODKA
    When player 1 tries to use a stored spirit from card 0 into cup 0
    Then the action should be rejected with a 400 error

  Scenario: Use stored spirit rejected when card has no spirits
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 0 stored spirits
    When player 1 tries to use a stored spirit from card 0 into cup 0
    Then the action should be rejected with a 400 error

  # ── Integration: Drink stored to qualify for refresh row ─────────────────────

  Scenario: Drink stored spirits to reach drunk level 3 then refresh row
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 3 stored spirits
    And player 1 has a drunk level of 0
    When player 1 drinks 3 stored spirits from card 0
    Then player 1's drunk level should be 3
    And it should still be player 1's turn
    When player 1 refreshes card row 2
    Then the action should succeed

  # ── Integration: Use stored spirit then sell cup ─────────────────────────────

  Scenario: Use stored spirit to add to cup then sell
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 1 stored spirit
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    When player 1 uses a stored spirit from card 0 into cup 0
    Then player 1's cup 0 should contain 3 ingredients
    And it should still be player 1's turn

  # ── Specialist Card: Claiming ──────────────────────────────────────────────

  Scenario: Claiming a specialist card awards 2 points
    Given it is player 1's turn
    And a specialist card for VODKA is available in row 2
    And player 1's bladder has 2 VODKA spirits
    When player 1 claims that card
    Then player 1 should have 2 points
    And player 1 should have 1 card
    And a move record should be created for the game

  Scenario: Claiming a specialist card does not consume bladder spirits
    Given it is player 1's turn
    And a specialist card for VODKA is available in row 2
    And player 1's bladder has 2 VODKA spirits
    When player 1 claims that card
    Then player 1's bladder should contain 2 ingredients

  Scenario: Cannot claim specialist card with fewer than 2 matching bladder spirits
    Given it is player 1's turn
    And a specialist card for VODKA is available in row 2
    And player 1's bladder has 1 VODKA spirit
    When player 1 tries to claim that card
    Then the action should be rejected with a 400 error

  Scenario: Cannot claim specialist card with 0 matching bladder spirits
    Given it is player 1's turn
    And a specialist card for VODKA is available in row 2
    And player 1 has 0 spirits in their bladder
    When player 1 tries to claim that card
    Then the action should be rejected with a 400 error

  Scenario: Cannot claim specialist card using stored spirits from a store card
    Given it is player 1's turn
    And player 1 holds a VODKA store card with 3 stored spirits
    And a specialist card for VODKA is available in row 2
    And player 1 has 0 spirits in their bladder
    When player 1 tries to claim that card
    Then the action should be rejected with a 400 error

  Scenario: Cannot claim specialist card with wrong spirit type in bladder
    Given it is player 1's turn
    And a specialist card for VODKA is available in row 2
    And player 1's bladder has 3 GIN spirits
    When player 1 tries to claim that card
    Then the action should be rejected with a 400 error

  # ── Specialist Card: Sell Bonus ────────────────────────────────────────────

  Scenario: Specialist bonus adds 2 points to non-cocktail sell with matching spirit
    Given it is player 1's turn
    And player 1 holds a VODKA specialist card
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    When player 1 sells cup 0 with no declared specials
    Then player 1 should have 3 points

  Scenario: Specialist bonus does not apply to cocktail sells
    Given it is player 1's turn
    And player 1 holds a RUM specialist card
    And player 1's cup 0 contains 2 RUM and 1 SODA
    And player 1 has "sugar" on their player mat
    When player 1 sells cup 0 declaring specials "sugar"
    Then player 1 should have 10 points

  Scenario: Specialist bonus does not apply when spirit type does not match
    Given it is player 1's turn
    And player 1 holds a GIN specialist card
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    When player 1 sells cup 0 with no declared specials
    Then player 1 should have 1 point

  Scenario: Specialist bonus on double-spirit drink with matching specialist
    Given it is player 1's turn
    And player 1 holds a WHISKEY specialist card
    And player 1's cup 0 contains 2 WHISKEY and 1 COLA
    When player 1 sells cup 0 with no declared specials
    Then player 1 should have 5 points

  Scenario: Specialist bonus applies after cup doubler doubling
    Given it is player 1's turn
    And player 1 holds a VODKA specialist card
    And player 1's cup 0 has the cup doubler effect
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    When player 1 sells cup 0 with no declared specials
    Then player 1 should have 4 points

  Scenario: Specialist bonus is zero for cocktail even with cup doubler
    Given it is player 1's turn
    And player 1 holds a RUM specialist card
    And player 1's cup 0 has the cup doubler effect
    And player 1's cup 0 contains 2 RUM and 1 SODA
    And player 1 has "sugar" on their player mat
    When player 1 sells cup 0 declaring specials "sugar"
    Then player 1 should have 10 points

  Scenario: Specialist bonus on Tequila Slammer
    Given it is player 1's turn
    And player 1 holds a TEQUILA specialist card
    And player 1's cup 0 contains 2 TEQUILA
    When player 1 sells cup 0 with no declared specials
    Then player 1 should have 5 points

  Scenario: Specialist card effect is permanent across multiple sells
    Given it is player 1's turn
    And the bag contains no special tokens
    And player 1 holds a VODKA specialist card
    And player 1's cup 0 contains 1 VODKA and 1 COLA
    And player 1's cup 1 contains 1 VODKA and 1 COLA
    When player 1 sells cup 0 with no declared specials
    Then player 1 should have 3 points
    When player 2 takes 3 ingredients from the bag
    And player 1 sells cup 1 with no declared specials
    Then player 1 should have 6 points

  # ── ReRollSpecials ──────────────────────────────────────────────────────────

  Scenario: Player re-rolls a single special and gets a new one
    Given it is player 1's turn
    And player 1 has "sugar" on their player mat
    When player 1 re-rolls specials "sugar" and rolls "lemon"
    Then player 1's player mat should have 1 LEMON
    And a move record should be created for the game
    And it should be player 2's turn

  Scenario: Player re-rolls multiple specials
    Given it is player 1's turn
    And player 1 has "sugar" and "lemon" on their player mat
    When player 1 re-rolls specials "sugar,lemon" and rolls "bitters,cointreau"
    Then player 1's player mat should have 1 BITTERS and 1 COINTREAU
    And it should be player 2's turn

  Scenario: Player re-rolls a special and rolls nothing — special is lost
    Given it is player 1's turn
    And player 1 has "sugar" on their player mat
    When player 1 re-rolls specials "sugar" and rolls "nothing"
    Then player 1's player mat should be empty
    And it should be player 2's turn

  Scenario: Player re-rolls all specials with mixed results
    Given it is player 1's turn
    And player 1 has "sugar" and "lemon" on their player mat
    When player 1 re-rolls specials "sugar,lemon" and rolls "bitters,nothing"
    Then player 1's player mat should have 1 BITTERS
    And it should be player 2's turn

  Scenario: Re-roll can yield the same special type
    Given it is player 1's turn
    And player 1 has "sugar" on their player mat
    When player 1 re-rolls specials "sugar" and rolls "sugar"
    Then player 1's player mat should have 1 SUGAR
    And it should be player 2's turn

  Scenario: ReRollSpecials with no specials chosen is rejected
    Given it is player 1's turn
    And player 1 has "sugar" on their player mat
    When player 1 tries to re-roll with no specials
    Then the action should be rejected with a 400 error

  Scenario: ReRollSpecials with a special not on the mat is rejected
    Given it is player 1's turn
    And player 1 has "sugar" on their player mat
    When player 1 tries to re-roll specials "lemon"
    Then the action should be rejected with a 400 error

  Scenario: ReRollSpecials is rejected when not your turn
    Given it is player 1's turn
    And player 1 has "sugar" on their player mat
    When player 2 tries to re-roll specials "sugar"
    Then the action should be rejected with a 409 error

  Scenario: ReRollSpecials is blocked while a take-ingredients batch is in progress
    Given it is player 1's turn
    And the bag contains no special tokens
    And player 1 has "sugar" on their player mat
    When player 1 takes 1 ingredient from the bag
    And player 1 tries to re-roll specials "sugar"
    Then the action should be rejected with a 409 error

  Scenario: Bag contents unchanged after ReRollSpecials
    Given it is player 1's turn
    And player 1 has "sugar" on their player mat
    When player 1 re-rolls specials "sugar" and rolls "nothing"
    Then the bag size should be unchanged
