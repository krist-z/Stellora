# State schema

`work-flow/state.md` contains exactly one `---workflow-state-json-v1---` block
and one end marker. The JSON is authoritative, uses UTF-8 and stable keys, and
is updated with an expected revision while the parent operation lock is held.
Recent events are bounded to 50; completed history is archived to documents.

Operation locks are atomically acquired and revisioned. Heartbeat, release, and
recovery compare the operation, task, role, workspace, and owner identity when
those fields are supplied. Recovery is explicit and stale-only; use
`lock recover --task-id <uuid> --role <role> --owner <operator> --reason <text>`
after the heartbeat exceeds `--stale-after-seconds` (default 300), or pass
`--force-stale` when the operator has recorded why the normal age gate cannot
be observed. Recovery appends an audit event to
`work-flow/.runtime/transactions/lock-recovery.jsonl`; never delete a lock by
hand.

The foreground parent runtime automatically heartbeats an operation while a CLI
leaf worker is running, beginning before workspace snapshot capture. A heartbeat
updates only the matching operation record and does not count as a worker workspace
change. Persistent guard contention beyond the configured stall window blocks the
worker; it is not treated as a harmless transient forever. Concurrent read-worker
heartbeats remain parent-owned and are never restored from another worker's snapshot.

The atomic mutation guard is a JSON record with a UUID, owner, operation ID, and
acquisition time. If a crash leaves it behind, use `lock recover-guard` to obtain
the observed identity, then repeat with the exact `--guard-id`, operator owner,
reason, and stale-age authorization. Recovery atomically moves the exact guard,
writes `lock.guard_recover` to the audit log, and never removes a different or
newly acquired guard. Normal lock mutation and guard recovery share an OS-level
mutex, closing the compare/claim path-reuse race.

Worker rollback never overwrites `operation-lock.json` from a stale workspace
snapshot. If a leaf worker corrupts that shared document, other business paths are
restored where possible and the command returns exit code 6 with the unresolved lock
path for explicit recovery.
