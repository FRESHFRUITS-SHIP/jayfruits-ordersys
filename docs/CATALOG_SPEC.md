# CATALOG_SPEC.md — Jay Fruits

Status: not yet started (Phase 3-5 territory). This file is scaffolded now, in Phase 0,
so it exists as the landing place for that work — not because catalog design work is happening yet.

## Current state (Phase 0 baseline)
- 7 seed products in `schema.sql`, real menu presumably larger in live Supabase (not yet counted/exported as part of this audit — action item: export current live `products` table row count and category spread before Phase 3 starts).
- `category` field exists (used to group the WhatsApp List Message into sections, max 10 sections × 10 rows per Meta's limits).
- `variant_group` and `image_url` confirmed live (see DATABASE.md) but not yet populated at scale — variant UX (`find_variant_options`) only returns something useful once products actually share a `variant_group` value.

## Deferred to Phase 3 (not decided yet)
- Category → fruit family → variant → SKU hierarchy
- Full alias table (Phase 4)
- Smart menu UX for 80+ items (Phase 5)

This file will be filled in when Milestone 2 (Phases 3-5) actually starts.
