# EXCERPT -- not runnable on its own.
# Source: server/app/payments.py, lines 284-336 and 403-412 (create_payment, POST /payments).
# Idea: money paid against a bill can never exceed the bill's total. Two layers:
#   1. the route locks the bill row and refuses past the remaining amount (with the figure);
#   2. a database trigger (migration 0026) re-checks the same rule under the same lock, so a
#      writer that slips past layer 1 is still refused (SQLSTATE RA001).
# Comments shortened where they pointed at internal documents; code lines unchanged.

            # ---- every allocation against the ledger, bill row LOCKED ----
            # FOR NO KEY UPDATE, not FOR UPDATE: it serialises two payments
            # allocating to one bill (so P2 cannot be broken by a race under
            # READ COMMITTED) while leaving FOR KEY SHARE alone, so a line
            # INSERT elsewhere is not stalled behind this counter.
            for a in body.allocations:
                bill = (
                    await conn.execute(
                        text(
                            "SELECT id, seller_id, total_amount, voided_at"
                            " FROM purchase_bills WHERE id = :b FOR NO KEY UPDATE"
                        ),
                        {"b": a.bill_id},
                    )
                ).mappings().first()
                if bill is None:
                    raise _bill_unknown(a.bill_id)
                if bill["voided_at"] is not None:
                    raise _invalid(
                        "bill_voided", "บิลนี้ถูกยกเลิกแล้ว จัดสรรเงินให้ไม่ได้",
                        bill_id=str(a.bill_id),
                    )
                if bill["seller_id"] != body.seller_id:
                    # P3 at the edge.
                    raise _invalid(
                        "seller_mismatch", "บิลนี้ไม่ใช่ของผู้ขายรายที่จ่ายเงินให้",
                        bill_id=str(a.bill_id), bill_seller_id=str(bill["seller_id"]),
                    )
                paid = Decimal(
                    (
                        await conn.execute(
                            text(
                                "SELECT coalesce(sum(x.amount), 0) FROM payment_allocations x"
                                " JOIN payments p ON p.id = x.payment_id"
                                " WHERE x.bill_id = :b AND p.voided_at IS NULL"
                            ),
                            {"b": a.bill_id},
                        )
                    ).scalar_one()
                )
                remaining = Decimal(bill["total_amount"]) - paid
                if a.amount > remaining:
                    # P2 at the edge: live allocations to a bill never exceed
                    # its total. The remaining figure is named so the counter
                    # can reissue with the right amount.
                    raise _invalid(
                        "allocation_exceeds_bill",
                        "ยอดที่จัดสรรเกินยอดคงค้างของบิล",
                        bill_id=str(a.bill_id), total_amount=str(bill["total_amount"]),
                        paid_amount=str(paid), remaining=str(remaining),
                        requested=str(a.amount),
                    )

            # ... insert the payment and its allocations ...

    except SQLAlchemyError as e:
        if _sqlstate_of(e) == _ALLOCATION_CAP_SQLSTATE:
            # THE DATABASE'S CAP (migration 0026) refused the allocation: the bill's live
            # allocations would exceed its total. The route's own check above refuses this first
            # under its row lock, so reaching here means a writer got past that check -- the same
            # refusal, the same code, PERMANENT; it names no remaining figure because the
            # database's message is not parsed for one.
            raise _invalid(
                "allocation_exceeds_bill", "ยอดที่จัดสรรเกินยอดคงค้างของบิล",
            ) from e
        _log_poison_candidate(principal, body, e)
        raise
