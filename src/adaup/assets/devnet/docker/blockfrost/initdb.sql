-- Run once by postgres-blockfrost's entrypoint on a fresh volume, before
-- db-sync-blockfrost creates its schema.
--
-- blockfrost-ryo's /pools/{pool_id} reads Calidus keys (CIP-151) with
-- pg_cardano and calls this wrapper, which its README asks deployments to
-- define so that a malformed registration answers false instead of failing the
-- request. Postgres resolves the functions when it plans the query, so the
-- endpoint fails without them even on a chain with no Calidus keys.
CREATE EXTENSION IF NOT EXISTS pg_cardano;

CREATE OR REPLACE FUNCTION safe_verify_cip88_pool_key_registration(input BYTEA)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN cardano.tools_verify_cip88_pool_key_registration(input);
EXCEPTION
    WHEN OTHERS THEN
        RETURN FALSE;
END;
$$ LANGUAGE plpgsql STABLE;
