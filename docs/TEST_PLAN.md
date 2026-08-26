# TEST_PLAN.md — Jay Fruits

Status: no automated tests exist in the repo today (no `tests/` directory, no test runner in `requirements.txt`). This is expected at this stage — Phase 22 (Testing Lab) and Phase 23 (Golden Conversations) own this properly.

## Phase 0 note
Rather than build the full `tests/` tree now, the immediate priority is manual verification of the Phase 0 findings:
1. Confirm `pending_item`/`pending_order`/`variant_group`/`image_url` columns exist and behave as expected live (user confirmed done — 2026-08-25).
2. Manually re-run the golden path once `migration_v3.sql` is applied to a fresh/staging DB, to confirm `schema.sql` alone can now stand up a working bot.

## Deferred to Phase 22-23
Full `tests/unit|integration|webhook|pricing|quantity|catalog|cart|inventory|payment|conversation|ai|security|load|regression/` structure, plus the 100 golden conversation scenarios — both as specified in the master roadmap. Not started.
