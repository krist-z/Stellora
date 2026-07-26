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
