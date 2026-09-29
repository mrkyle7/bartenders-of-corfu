Feature: Forgotten password
  As a player who has forgotten their password
  I want a reset link emailed to me
  So that I can choose a new password and carry on playing

  Background:
    Given a registered player with email "reset@example.com"

  Scenario: A reset link is emailed to the account's address
    When someone asks to reset the password for "reset@example.com"
    Then the response status should be 202
    And one reset email is sent to "reset@example.com"
    And the email links to "https://cheetahmoongames.com/reset-password?token="

  Scenario: The email address is matched without case
    When someone asks to reset the password for "RESET@Example.com"
    Then one reset email is sent to "reset@example.com"

  Scenario: The return address travels with the link
    When someone asks to reset the password for "reset@example.com" returning to "https://bezique.cheetahmoongames.com/"
    Then the email links to "next=https%3A%2F%2Fbezique.cheetahmoongames.com%2F"

  Scenario: Unknown emails get the same answer and no email
    When someone asks to reset the password for "nobody@example.com"
    Then the response status should be 202
    And no email is sent

  Scenario: The link sets a new password and signs the player in
    Given the player has asked for a reset link
    When the player uses the link with the new password "NewPassword2"
    Then the response status should be 200
    And the player is signed in
    And the player can log in with "NewPassword2"
    And the player can't log in with "Password1"

  Scenario: Signing in elsewhere with the old password ends
    Given the player is signed in on another device
    And the player has asked for a reset link
    When the player uses the link with the new password "NewPassword2"
    Then the other device is signed out

  Scenario: A link only works once
    Given the player has asked for a reset link
    And the player has used the link with the new password "NewPassword2"
    When the player uses the link with the new password "Another3pass"
    Then the response status should be 400
    And the error says the link has expired or been used

  Scenario: An expired link doesn't work
    Given the player has asked for a reset link
    And the link has expired
    When the player uses the link with the new password "NewPassword2"
    Then the response status should be 400
    And the error says the link has expired or been used

  Scenario: A made-up link doesn't work
    When someone uses the link token "not-a-real-token" with the new password "NewPassword2"
    Then the response status should be 400
    And the error says the link has expired or been used

  Scenario: A weak new password is refused and the link still works
    Given the player has asked for a reset link
    When the player uses the link with the new password "short"
    Then the response status should be 400
    And the error says "Password must be at least 8 characters long"
    When the player uses the link with the new password "NewPassword2"
    Then the response status should be 200

  Scenario: Only a few links an hour
    When someone asks to reset the password for "reset@example.com" 4 times
    Then 3 reset emails are sent to "reset@example.com"

  Scenario: Asking for a new link doesn't cancel the old one
    Given the player has asked for a reset link
    And the player has asked for another reset link
    When the player uses the first link with the new password "NewPassword2"
    Then the response status should be 200
    When the player uses the second link with the new password "Another3pass"
    Then the response status should be 400
