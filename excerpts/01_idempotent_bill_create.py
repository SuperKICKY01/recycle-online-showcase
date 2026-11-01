# EXCERPT -- not runnable on its own.
# Source: server/app/bills.py, lines 630-641 and 1006-1039 (create_bill, POST /bills).
# Idea: the same idempotency_key always returns the SAME bill, never a second one --
# including when two copies of one bill race each other to the server.
# Comments shortened where they pointed at internal documents; code lines unchanged.

    try:
        async with tenant_connection(principal.tenant_id) as conn:
            # Idempotency: the same key returns the SAME bill, never a duplicate.
            existing = (
                await conn.execute(
                    text("SELECT id FROM purchase_bills WHERE idempotency_key = :k"),
                    {"k": body.idempotency_key},
                )
            ).scalar_one_or_none()
            if existing is not None:
                response.status_code = status.HTTP_200_OK
                return await _read_bill(conn, existing)

            # ... validate lines, assign doc_no, insert bill + lines + stock movement,
            # ... and (if the branch pays at the scale) the automatic payment --
            # ... all in this ONE transaction ...

    except IntegrityError as e:
        # A concurrent submit of the SAME bill lost the race. ASK THE DATABASE
        # whether that is what happened; do not try to recognise it from the
        # constraint name.
        #
        # The bill's PRIMARY KEY is client-generated too, so a device retrying the
        # same bill collides on `purchase_bills_pkey` OR on `uq_bills_tenant_idem`
        # depending on which index Postgres checks first -- not something the
        # handler can predict. The key resolving to a bill is the fact that
        # actually matters, and it is one SELECT away.
        async with tenant_connection(principal.tenant_id) as conn:
            existing = (
                await conn.execute(
                    text("SELECT id FROM purchase_bills WHERE idempotency_key = :k"),
                    {"k": body.idempotency_key},
                )
            ).scalar_one_or_none()
            if existing is not None:
                response.status_code = status.HTTP_200_OK
                return await _read_bill(conn, existing)
        # Not the idempotency race: this 500 is about to jam a device queue.
        _log_poison_candidate(principal, body, e)
        raise
    except SQLAlchemyError as e:
        # DataError (numeric overflow), CheckViolation, connection loss -- anything
        # the DB layer raises that we did not anticipate. Same blast radius, so
        # the same distinct log line.
        _log_poison_candidate(principal, body, e)
        raise
