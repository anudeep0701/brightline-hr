-- Separate credentials have no workspace role and no database login privileges.
CREATE TABLE ingestion_api_keys (
    id varchar(36) PRIMARY KEY,
    tenant_id varchar(64) NOT NULL REFERENCES tenants(id),
    digest varchar(64) NOT NULL UNIQUE,
    name varchar(100) NOT NULL,
    created_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CONSTRAINT ck_ingestion_key_digest CHECK (length(digest) = 64)
);
CREATE INDEX ix_ingestion_api_keys_tenant_id ON ingestion_api_keys(tenant_id);
ALTER TABLE ingestion_api_keys ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE ingestion_api_keys FROM PUBLIC;
-- Supabase default roles may have default table grants; keep this table backend-only.
DO $$
DECLARE browser_role text;
BEGIN
    FOREACH browser_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = browser_role) THEN
            EXECUTE 'REVOKE ALL ON TABLE ingestion_api_keys FROM ' || quote_ident(browser_role);
        END IF;
    END LOOP;
END $$;
