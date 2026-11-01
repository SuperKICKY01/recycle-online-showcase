# EXCERPT -- not runnable on its own (the seeding, teardown and connection setup are omitted).
# Source: server/scripts/prove_rls.py, lines 356-412 (steps 3-6 of the RLS proof).
# Idea: a "proof" is a program run against a REAL PostgreSQL, connected as the application's
# own non-superuser role, that tries to break a rule and records every way it did not break.
# Two throwaway tenants A and B are seeded with identical natural keys; then, as tenant A:
#   step 3  fetch B's rows by their exact primary key      -> must see 0 rows
#   step 4  UPDATE / DELETE B's seller                       -> must affect 0 rows
#   step 5  INSERT a row carrying tenant_id = B              -> must be rejected
#   step 6  same pooled connection, new transaction, no tenant set -> must see nothing at all
# Any failure is appended to `failures`; the program's exit code is non-zero if the list is not
# empty. Code lines unchanged.

        banner("STEP 3 - context = A: fetch B's rows by EXACT primary key -> 0 rows")
        async with tenant_tx(conn, tenant_a):
            for t, pk in [("tenants", tenant_b), ("sellers", ids_b["seller"]),
                          ("purchase_bills", ids_b["bill"])]:
                n = (await conn.execute(
                    text(f"SELECT count(*) FROM {t} WHERE id = :pk"), {"pk": pk}
                )).scalar_one()
                print(f"    SELECT {t:16} WHERE id = <B's exact pk> -> {n} row(s)")
                if n != 0:
                    failures.append(f"{t}: B's row was fetchable by pk under A's context")

        banner("STEP 4 - context = A: UPDATE / DELETE B's seller -> 0 rows affected")
        async with tenant_tx(conn, tenant_a):
            ru = await conn.execute(
                text("UPDATE sellers SET name = 'HACKED' WHERE id = :pk"),
                {"pk": ids_b["seller"]})
            rd = await conn.execute(
                text("DELETE FROM sellers WHERE id = :pk"), {"pk": ids_b["seller"]})
            rc_update, rc_delete = ru.rowcount, rd.rowcount
        print(f"    UPDATE B's seller -> rowcount = {rc_update}")
        print(f"    DELETE B's seller -> rowcount = {rc_delete}")
        if rc_update != 0:
            failures.append("UPDATE crossed tenant boundary")
        if rc_delete != 0:
            failures.append("DELETE crossed tenant boundary")
        async with tenant_tx(conn, tenant_b):
            nm = (await conn.execute(
                text("SELECT name FROM sellers WHERE id = :pk"), {"pk": ids_b["seller"]}
            )).scalar_one_or_none()
        print(f"    B's seller name afterwards (checked as B) = {nm!r}")
        if nm != "Seller B":
            failures.append("B's seller was mutated/removed by A")

        banner("STEP 5 - context = A: INSERT a row with tenant_id = B -> rejected")
        try:
            async with tenant_tx(conn, tenant_a):
                await conn.execute(
                    text("INSERT INTO sellers (id, tenant_id, code, name)"
                         " VALUES (:id, :t, 'HACK', 'cross-tenant insert')"),
                    {"id": uuid.uuid4(), "t": tenant_b})
            print("    !!! INSERT SUCCEEDED - THIS IS A FAILURE !!!")
            failures.append("cross-tenant INSERT was allowed")
        except DBAPIError as e:
            first = str(e.orig).splitlines()[0] if e.orig else str(e).splitlines()[0]
            print(f"    INSERT rejected as expected: {first}")

        banner("STEP 6 - SAME connection, fresh tx, NO tenant context -> fail closed")
        async with no_context_tx(conn):
            setting = (await conn.execute(
                text("SELECT current_setting('app.tenant_id', true)"))).scalar_one_or_none()
            counts = await count_all(conn)
        print(f"    current_setting('app.tenant_id', true) = {setting!r}  "
              f"(LOCAL context from earlier tx did NOT leak)")
        for t, c in counts.items():
            print(f"    {t:22} rows visible = {c}")
        if any(c != 0 for c in counts.values()):
            failures.append("rows were visible with NO tenant context set")
