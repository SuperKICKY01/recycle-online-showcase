# EXCERPT -- not runnable on its own.
# Sources:
#   server/migrations/versions/0020_payments.py, lines 142-144 and 419-428 (the policy pattern)
#   server/app/db.py, lines 141-149 (where every request sets its tenant)
# Idea: tenant isolation lives in PostgreSQL, not in each handler. Every business table has
# tenant_id and a FORCED row-level-security policy; the application sets the tenant with
# set_config(..., is_local=true), i.e. SET LOCAL -- transaction-scoped, so it can never leak to
# the next request that reuses the pooled connection. No tenant set = zero rows (fails closed).
# Grants and role names omitted; code lines otherwise unchanged.

# ---- 0020_payments.py: the predicate and the policy -------------------------------------

# Reusable RLS predicate. The same expression 0001 uses on every tenant table,
# so the value an INSERT writes and the value the policy tests are one thing.
_TENANT_MATCH = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

    # -------------------------------------------------------------------- RLS
    # Enabled AFTER the backfill that wrote these tables, exactly as 0015/0018/0019.
    for table in ("payments", "payment_allocations"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = {_TENANT_MATCH}) "
            f"WITH CHECK (tenant_id = {_TENANT_MATCH})"
        )


# ---- db.py: tenant_connection, the one way a request reaches the database ----------------

    async with engine.connect() as conn:
        if isolation_level is not None:
            conn = await conn.execution_options(isolation_level=isolation_level)
        async with conn.begin():
            if tenant_id is not None:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"),
                    {"t": str(tenant_id)},
                )
            # ... (the audit actor is set the same way, then) ...
            yield conn
