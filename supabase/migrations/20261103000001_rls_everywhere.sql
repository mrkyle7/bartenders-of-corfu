-- Row level security on every table in public. The server talks to Supabase
-- with the service role key, which bypasses RLS, so this changes nothing for
-- it; with no policies, the anon and authenticated keys (Supabase's public
-- REST API) can no longer read or write these tables.
ALTER TABLE game_moves ENABLE ROW LEVEL SECURITY;
ALTER TABLE undo_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_policy ENABLE ROW LEVEL SECURITY;

-- And any other table in public that hasn't got it (none should, but a
-- table made by hand in the dashboard would be open otherwise).
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND NOT rowsecurity LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
END $$;
