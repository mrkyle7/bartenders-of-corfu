ALTER TABLE users
  ADD COLUMN status text NOT NULL DEFAULT 'active',
  ADD COLUMN is_admin boolean NOT NULL DEFAULT false,
  ADD COLUMN deactivated_at timestamptz,
  ADD COLUMN deactivated_by uuid REFERENCES users(id),
  ADD COLUMN deleted_at timestamptz;
