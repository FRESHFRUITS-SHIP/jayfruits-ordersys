-- Phase 0 audit fix: brings tracked schema in sync with columns that already
-- exist live in Supabase (added manually, outside version control).
-- Safe to run even if these already exist (uses IF NOT EXISTS everywhere).
-- Run this so a fresh environment (staging, disaster recovery, a teammate's
-- local setup) reproduces the real, working schema — not a stale one.

alter table customers add column if not exists pending_item jsonb;
alter table customers add column if not exists pending_order jsonb;

alter table products add column if not exists variant_group text;
alter table products add column if not exists image_url text;
