# ROADMAP.md — Jay Fruits

The full 30-phase / 8-milestone roadmap is the agreed plan (established 2026-08-25). Rather than duplicate it here, this file tracks **progress against it**, updated as phases complete.

## Milestone 1 — 🛡️ Make current bot safe (Phases 0-2)
- **Phase 0 — Freeze & Audit: IN PROGRESS.** `/docs` structure created. Feature audit done (see CURRENT_STATE.md). Schema drift identified (see DATABASE.md) — user confirms live DB already has the missing columns; `migration_v3.sql` still needed to bring tracked SQL in sync.
- **Phase 1 — Foundation & Safety: NOT STARTED.** Key gaps identified: no idempotency, no global error boundary beyond payload-parsing errors, no correlation IDs, no audit log, no rate limiting (despite earlier belief it existed).
- **Phase 2 — Conversation State Engine: NOT STARTED.** Current state is implicit (`pending_item`/`pending_order` columns), not the explicit state enum the phase calls for.

## Milestones 2-8
Not started. Will be filled in as work begins on each, per the roadmap's phase list.

---
*This file is a progress tracker, not a redefinition of the plan — refer back to the original 30-phase roadmap for full phase content.*
