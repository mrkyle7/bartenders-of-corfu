-- Signing in with Google. google_id is the account's Google user ID (the ID
-- token's `sub`), which never changes even if the Google email does.
-- An account found by email is linked on its first Google sign-in.
-- Accounts made by signing in with Google have no password (password is null)
-- until the player sets one with a reset link.
ALTER TABLE users ADD COLUMN google_id TEXT UNIQUE;
