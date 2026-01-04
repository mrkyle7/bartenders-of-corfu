create table users (
  id uuid primary key,
  username text unique,
  email text unique,
  password bytea,
  created_at timestamptz default now(),
  password_changed_at timestamptz default now()
);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;