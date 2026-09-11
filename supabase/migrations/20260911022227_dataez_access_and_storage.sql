-- Backend-only SQL access. No Supabase Auth policies: the application uses
-- its own JWTs and checks account/store ownership in FastAPI.
-- This role owns application tables because the app creates per-file tables.
-- NOLOGIN until a password is provisioned through a secure operator channel.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dataez_app') THEN
    CREATE ROLE dataez_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END $$;
GRANT dataez_app TO postgres;
GRANT USAGE, CREATE ON SCHEMA public TO dataez_app;
GRANT USAGE ON SCHEMA extensions TO dataez_app;
ALTER ROLE dataez_app SET search_path = public, extensions;
REVOKE CREATE ON SCHEMA public FROM PUBLIC, anon, authenticated;

DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO dataez_app', r.tablename);
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.tablename);
  END LOOP;
  FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname='public' LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO dataez_app', r.sequencename);
  END LOOP;
  FOR r IN SELECT p.oid::regprocedure AS signature FROM pg_proc p
    JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'
    AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass
      AND d.objid=p.oid AND d.deptype='e') LOOP
    EXECUTE format('ALTER FUNCTION %s OWNER TO dataez_app', r.signature);
    EXECUTE format('ALTER FUNCTION %s SET search_path = public, extensions, pg_temp', r.signature);
  END LOOP;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE dataez_app IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE dataez_app IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE dataez_app REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Covers every dynamic CREATE TABLE path without depending on API startup.
-- Invoker rights: the creator only hardens the table they just created.
CREATE SCHEMA IF NOT EXISTS dataez_internal;
REVOKE ALL ON SCHEMA dataez_internal FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA dataez_internal TO dataez_app;
CREATE OR REPLACE FUNCTION dataez_internal.protect_new_tables()
RETURNS event_trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
DECLARE r record;
BEGIN
  FOR r IN SELECT c.oid::regclass AS relation FROM pg_event_trigger_ddl_commands() d
    JOIN pg_class c ON c.oid=d.objid JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE d.classid='pg_class'::regclass AND n.nspname='public' AND c.relkind IN ('r','p')
  LOOP
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY',r.relation);
    EXECUTE format('REVOKE ALL ON TABLE %s FROM PUBLIC, anon, authenticated',r.relation);
  END LOOP;
END $$;
REVOKE ALL ON FUNCTION dataez_internal.protect_new_tables() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION dataez_internal.protect_new_tables() TO dataez_app;
DROP EVENT TRIGGER IF EXISTS dataez_protect_new_tables;
CREATE EVENT TRIGGER dataez_protect_new_tables ON ddl_command_end
  WHEN TAG IN ('CREATE TABLE','CREATE TABLE AS','SELECT INTO')
  EXECUTE FUNCTION dataez_internal.protect_new_tables();

INSERT INTO storage.buckets(id,name,public,file_size_limit)
VALUES ('dataez-files','dataez-files',false,20971520)
ON CONFLICT(id) DO UPDATE SET public=false,file_size_limit=20971520;
