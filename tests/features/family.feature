Feature: Families
  As a parent
  I want to see how my children are doing in the Cheetah Moon games
  So that I can help them with what they find hard

  Background:
    Given a parent "Mum" and a child "Zed"

  Scenario: A parent sees a child once the child says yes
    When "Mum" asks for "Zed" by email
    Then "Mum" has no children
    And "Zed" sees "Mum" asking
    When "Zed" says yes to "Mum"
    Then "Mum" has the child "Zed"
    And "Zed" has the parent "Mum"
    And a game asking with "Mum"'s cookie hears of "Zed"

  Scenario: A child can say no
    When "Mum" asks for "Zed" by email
    And "Zed" says no to "Mum"
    Then "Mum" has no children
    And "Mum" is asking for nobody

  Scenario: Nobody else can say yes for a child
    Given another player "Lou"
    When "Mum" asks for "Zed" by email
    And "Lou" says yes to "Mum"
    Then the response status should be 400
    And "Mum" has no children

  Scenario: Either of them can undo it
    When "Mum" asks for "Zed" by email
    And "Zed" says yes to "Mum"
    And "Zed" stops sharing with "Mum"
    Then "Mum" has no children

  Scenario: Something that isn't an email is refused
    When "Mum" asks for the email "not-an-email"
    Then the response status should be 400

  Scenario: Families need signing in
    When someone signed out asks for their family
    Then the response status should be 401
