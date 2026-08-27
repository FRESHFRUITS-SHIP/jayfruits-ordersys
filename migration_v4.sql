-- Phase 1 — Foundation & Safety
-- Adds the tables needed for webhook idempotency and the business-event audit log.
-- Safe to run multiple times (all "if not exists").

create table if not exists processed_webhook_events (
    message_id text primary key,
    received_at timestamptz not null default now(),
    processed_at timestamptz,
    status text not null default 'processing'  -- 'processing' | 'done' | 'failed'
);

create table if not exists audit_log (
    id bigserial primary key,
    trace_id text not null,
    customer_id bigint references customers(id),
    event_type text not null,   -- e.g. MESSAGE_RECEIVED, ORDER_CONFIRMED, ITEM_ADDED, PAYMENT_STARTED
    details jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_audit_log_trace_id on audit_log(trace_id);
create index if not exists idx_audit_log_customer_id on audit_log(customer_id);
create index if not exists idx_audit_log_event_type on audit_log(event_type);
