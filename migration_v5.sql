-- Phase 2 — Conversation State Engine
-- Adds explicit state tracking to replace the implicit pending_item/pending_order-only model.
-- Safe to run multiple times.

alter table customers add column if not exists conversation_state text not null default 'NEW';
alter table customers add column if not exists interrupted_state text;
alter table customers add column if not exists state_updated_at timestamptz not null default now();

create index if not exists idx_customers_conversation_state on customers(conversation_state);