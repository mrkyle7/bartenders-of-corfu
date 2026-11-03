-- Child accounts: made by a parent (cheetahmoongames.com/family), with no
-- email or password, so a child can't sign in to one on their own. The
-- parent switches to it to play, and back again with their own password
-- (app/family.py). `managed_by` is the parent who made it; they're linked as
-- parent and child (family_links) when it's made.
ALTER TABLE users ADD COLUMN managed_by UUID REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX idx_users_managed_by ON users(managed_by);
