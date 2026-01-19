create table public_keys (
  kid uuid primary key,
  public_key bytea,
  created_at timestamptz default now(),
  valid boolean default TRUE
);

ALTER TABLE public_keys ENABLE ROW LEVEL SECURITY;