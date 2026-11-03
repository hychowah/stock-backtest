# Decision 1: Verify compatibility at existing owners

The frozen Phase 8 captures and evidence already exercise independent restoration,
request and plan validation, and detached export. Existing queue and library
suites exercise current durable containers, but did not put those historical
contents through reopened owners. The variable-store suite also lacked a frozen
definition through its owner. Add those focused checks to the existing
compatibility suite. They retain fixed historical expectations and use current
private container writers. They do not establish migration from an old container
schema. The Phase 8 entry and current variable store both declare version 1
and the same entries and revisions columns.

Keep admission, restoration, storage and export decisions at their present
owners. A new compatibility gateway would duplicate those boundaries. No
financial policy, stored format, fallback or application qualification changes.
