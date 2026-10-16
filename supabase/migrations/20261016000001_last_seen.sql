-- When each player was last seen in any Cheetah Moon game or signing in
-- (app/activity.py). A player seen again after a long gap counts as coming
-- back, and the site's owner is sent a notification.
ALTER TABLE users ADD COLUMN last_seen_at TIMESTAMPTZ;
