-- P0 — session expiry (catalog item #30): pending_item/pending_order should
-- not be treated as still-valid context if the customer replies hours/days
-- later. Adds timestamps so the code can decide when to expire them.
-- Safe to run multiple times.

alter table customers add column if not exists pending_item_set_at timestamptz;
alter table customers add column if not exists pending_order_set_at timestamptz;