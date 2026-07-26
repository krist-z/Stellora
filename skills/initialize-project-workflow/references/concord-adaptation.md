# Concord adaptation

This implementation maps selected Concord concepts from commit
`ed519a114648b21eba66149fce0af247d52efc4d`: one state source, revision CAS,
operation locking, next-action routing, parent-owned state writes,
single-writer implementation, evidence archives, persisted intent and technical
plan approvals, L3/L4 batch freeze, and shared/local configuration separation.
It intentionally does not vendor Concord code or create `.concord/` or
`docs/concord/`; license and notification boundaries are therefore preserved.
