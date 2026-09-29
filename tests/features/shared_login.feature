Feature: Shared cheetahmoongames.com login
  As a player of any Cheetah Moon game
  I want to sign in once on cheetahmoongames.com
  So that every game knows who I am

  Scenario: Login page sends players to the shared sign-in page
    Given the shared sign-in page is "https://cheetahmoongames.com/login"
    When a player opens the login page
    Then they are redirected to "https://cheetahmoongames.com/login?next=https%3A%2F%2Fbartenders.cheetahmoongames.com%2F"

  Scenario: Players come back to the page that needed them to sign in
    Given the shared sign-in page is "https://cheetahmoongames.com/login"
    When a player is sent to the login page from "https://bartenders.cheetahmoongames.com/game?id=42"
    Then they are redirected to "https://cheetahmoongames.com/login?next=https%3A%2F%2Fbartenders.cheetahmoongames.com%2Fgame%3Fid%3D42"

  Scenario: A return address on another site is ignored
    Given the shared sign-in page is "https://cheetahmoongames.com/login"
    When a player opens the login page with next "//evil.example/steal"
    Then they are redirected to "https://cheetahmoongames.com/login?next=https%3A%2F%2Fbartenders.cheetahmoongames.com%2F"

  Scenario: Without a shared sign-in page the login page is served here
    Given there is no shared sign-in page
    When a player opens the login page
    Then the login form is shown

  Scenario: Games can fetch the key that checks a login cookie
    Given a registered user
    When a game fetches the public key for the user's login cookie
    Then the response status should be 200
    And the key verifies the user's login cookie

  Scenario: Unknown keys are not found
    When a game fetches the public key "00000000-0000-0000-0000-000000000000"
    Then the response status should be 404

  Scenario: Malformed key ids are not found
    When a game fetches the public key "not-a-key"
    Then the response status should be 404
