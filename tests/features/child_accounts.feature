Feature: Child accounts
  A parent makes an account for a child who hasn't got an email. The child
  can't sign in to it: the parent switches to it to let them play, and back
  again with their own password.

  Scenario: A parent makes a child account and it's their child straight away
    Given a parent "Mum"
    When "Mum" makes a child account called "Kit"
    Then "Mum" has the child account "Kit"

  Scenario: Switching to a child account and back
    Given a parent "Mum"
    And "Mum" made a child account called "Kit"
    When "Mum" switches to "Kit"
    Then the login cookie is "Kit"'s, played for "Mum"
    And as "Kit" they can't change the password
    When they switch back with the password "wrong-password1"
    Then the switch back is refused
    When they switch back with "Mum"'s password
    Then the login cookie is "Mum"'s own

  Scenario: Nobody can sign in to a child account
    Given a parent "Mum"
    And "Mum" made a child account called "Kit"
    Then nobody can sign in as "Kit"

  Scenario: Only the parent who made it can switch to it
    Given a parent "Mum"
    And "Mum" made a child account called "Kit"
    And another player "Lou"
    When "Lou" switches to "Kit"
    Then the switch is refused
