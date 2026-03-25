Feature: Color theme
  As a registered user
  I want to change my UI color theme
  So that I can personalise the game interface

  Background:
    Given a registered user

  Scenario: Player changes their color theme
    When the user changes their theme to "mediterranean"
    Then the response status should be 200
    And the response should confirm the theme is "mediterranean"

  Scenario: Changed theme persists in user details
    When the user changes their theme to "sunset"
    And the user fetches their details
    Then the user details should show the theme as "sunset"

  Scenario: Invalid theme name is rejected
    When the user changes their theme to "neon"
    Then the response status should be 400

  Scenario: Unauthenticated theme change is rejected
    When an unauthenticated user changes their theme to "nightclub"
    Then the response status should be 401
