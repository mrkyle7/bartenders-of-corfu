-- Nothing in this database is public, except the public keys that check
-- login cookies.
--
-- The server talks to Supabase with the service role key, which bypasses row
-- level security and keeps its own grants, so this changes nothing for it.
-- Supabase's public REST API (the anon and authenticated roles, used with the
-- project's publishable key) loses every grant here, so even a table that
-- somehow lost its row level security would stay closed. tests/
-- test_database_security.py checks all of this; see "Database security" in
-- claude.md.

-- No grants to the public roles on anything that exists now...
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
-- (functions can be run by PUBLIC, every role, unless taken away)
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated, PUBLIC;

-- ...or on anything made later.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated, PUBLIC;

-- The one exception: anyone may read the public keys, so the games (through
-- cheetahmoongames.com's auth.js) can check a login cookie without waiting
-- for Bartenders to wake up. Public keys aren't secret. Reading only.
GRANT SELECT ON public_keys TO anon;
CREATE POLICY "Anyone can read public keys" ON public_keys FOR SELECT TO anon USING (true);
