// EXCERPT -- not runnable on its own.
// Sources:
//   mobile/src/sync/types.ts, line 16 and lines 65-80 (the local bill record)
//   mobile/src/sync/outboxHandlers.ts, lines 83-114 (what each server answer means)
// Idea: a bill is written to the phone's own SQLite FIRST and sent later. Its idempotency key is
// generated once at creation and never regenerated, so any number of resends after a lost
// response or a crash can only ever produce one bill on the server. Every server answer is
// mapped to exactly one next action; "already exists" counts as success.
// Code lines unchanged.

// ---- types.ts ---------------------------------------------------------------------------

export type SyncState = "pending" | "syncing" | "synced" | "failed";

export interface LocalBill {
  /** Client-generated UUID; the SAME id the server stores (hard rule 3). */
  id: string;
  /**
   * Generated ONCE at creation and never regenerated — not on retry, not after
   * a crash, not after a lost response. Regenerating it would defeat the
   * server's dedup and create a duplicate bill for real money. It is a random
   * value frozen at birth, never derived from payload contents, so nothing
   * about the bill can change it.
   */
  idempotency_key: string;
  payload: BillPayload;
  sync_state: SyncState;
  attempt_count: number;
  /** Text of the most recent failure. Cleared on success. Never hidden from the UI. */
  last_error: string | null;
  // ... more fields (timestamps, backoff schedule) ...
}

// ---- outboxHandlers.ts ------------------------------------------------------------------

function classifySend(o: SendOutcome): OutboxDisposition {
  switch (o.kind) {
    case "accepted":
    case "duplicate":
      // "Already exists" is success: our key won a previous race or a lost
      // response actually landed — the bill IS on the server.
      return { next: "settled" };
    case "rejected":
      return { next: "terminal", reason: o.reason, code: "rejected" };
    case "rejected_resolvable":
      // Parks in a named state and returns when the office adds the price.
      return { next: "parked", reason: o.reason, code: o.code };
    case "session_expired":
      return { next: "retry", reason: o.reason };
    case "forbidden":
      // A 403 refuses every bill equally: the KIND stops, durably.
      return { next: "halt_kind", reason: o.reason, code: o.code };
    case "client_outdated":
      // A 426 refuses every bill equally too, and no sign-in helps: the KIND
      // stops until the app is updated (a new process). Same disposition as 403;
      // the code is a fixed marker, since a 426 carries none.
      return { next: "halt_kind", reason: o.reason, code: "client_outdated" };
    case "unavailable":
      return { next: "retry", reason: o.reason };
  }
}

export function billSendHandler(deps: OutboxDeps): OutboxHandler<LocalBill, SendOutcome> {
  const backoffFor = (attempt: number): number => {
    const raw = deps.backoffBaseMs * 2 ** Math.max(0, attempt - 1);
    return Math.min(raw, deps.backoffMaxMs);
  };
  // ...
}
