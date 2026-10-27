Feature: Signing in with Google
  As a player
  I want to sign in with my Google account
  So that I don't need another password, and keep my account if I already have one

  Scenario: A new player gets an account by signing in with Google
    When a new player signs in with Google as "Ada Lovelace"
    Then the response status should be 201
    And the player is signed in
    And the account is new
    And the account has the Google email
    And the account has no password
    And the account's email is verified

  Scenario: Signing in with Google again finds the same account
    Given a player has signed in with Google before
    When the player signs in with Google
    Then the response status should be 200
    And it is the same account as before

  Scenario: An account with the same email is linked to Google
    Given a registered player with password "Password1"
    When the player signs in with Google using the same email
    Then the response status should be 200
    And it is the registered player's account
    And the player is signed in
    And the player's account is linked to Google

  # Registering doesn't check the email, so someone could register with
  # another person's email and wait for them to sign in with Google.
  Scenario: Linking to Google removes the password and signs others out
    Given a registered player with password "Password1"
    When the player signs in with Google using the same email
    Then the player can no longer log in with "Password1"
    And whoever was signed in with the password is signed out
    And the account has no password

  Scenario: Signing in with Google verifies the email
    Given a player has registered but not verified their email
    When the player signs in with Google using the same email
    Then it is the registered player's account
    And the account's email is verified

  Scenario: A password set after linking keeps working
    Given a player has signed in with Google before
    And the player has set a password "Password2"
    When the player signs in with Google
    Then the player can log in with "Password2"

  Scenario: Matching email is checked without case
    Given a registered player with password "Password1"
    When the player signs in with Google using the same email in capitals
    Then it is the registered player's account

  Scenario: An email Google hasn't verified is not linked
    Given a registered player with password "Password1"
    When someone signs in with Google using the same email, unverified
    Then the response status should be 403
    And the player is not signed in
    And the player's account is not linked to Google

  Scenario: A token made for another app is refused
    When someone signs in with a Google token made for another app
    Then the response status should be 401
    And the player is not signed in

  Scenario: Google sign-in is off until it is set up
    Given Google sign-in is not set up
    When a new player signs in with Google as "Ada Lovelace"
    Then the response status should be 503
