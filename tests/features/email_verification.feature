Feature: Verifying your email
  As the owner of an email address
  I want accounts to prove they own their email before they can sign in
  So that nobody can register with my email and keep the account when I arrive

  Scenario: Registering emails a link instead of signing in
    When a player registers returning to "https://bezique.cheetahmoongames.com/"
    Then the response status should be 201
    And the player is not signed in
    And one verification email is sent to the player
    And the email links to "https://cheetahmoongames.com/verify-email?token="
    And the email links to "next=https%3A%2F%2Fbezique.cheetahmoongames.com%2F"

  Scenario: The password doesn't sign in until the email is verified
    Given a player has registered
    When the player logs in with their password
    Then the response status should be 403
    And the player is told to verify their email
    And the player is not signed in
    And another verification email is sent to the player

  Scenario: A wrong password doesn't say whether the email is verified
    Given a player has registered
    When the player logs in with the password "WrongPassword9"
    Then the response status should be 401
    And no more emails are sent

  Scenario: The link verifies the email and signs the player in
    Given a player has registered
    When the player uses the link
    Then the response status should be 200
    And the player is signed in
    And the player can log in with their password

  Scenario: A link works once
    Given a player has registered
    And the player has used the link
    When the player uses the link
    Then the response status should be 400

  Scenario: An expired link doesn't work
    Given a player has registered
    And the link has expired
    When the player uses the link
    Then the response status should be 400
    And the player still can't log in with their password

  Scenario: A made-up link doesn't work
    When someone uses the link token "not-a-real-token"
    Then the response status should be 400

  Scenario: At most three emails an hour
    Given a player has registered
    When the player logs in with their password 4 times
    Then 3 verification emails are sent to the player

  Scenario: Resetting the password verifies the email
    Given a player has registered
    When the player resets their password to "NewPassword2"
    Then the player can log in with "NewPassword2"

  Scenario: Changing email waits for the new address to be verified
    Given a verified player is signed in
    When the player changes their email to a new address
    Then the response status should be 200
    And one verification email is sent to the new address
    And the player's email is still the old one
    When the player uses the link
    Then the player's email is the new one

  Scenario: An old link can't change the email back
    Given a verified player is signed in
    And the player has asked to change their email to a new address
    And the player has asked to change their email to a second new address
    And the player has used the second link
    When the player uses the first link
    Then the response status should be 400
    And the player's email is the second new one

  Scenario: An email another account uses can't be taken
    Given a verified player is signed in
    And another player uses the address "taken"
    When the player changes their email to the address "taken"
    Then the response status should be 400
    And no more emails are sent
