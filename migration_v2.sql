-- Run this in Supabase SQL editor to upgrade an EXISTING v1 database to v2.
-- Safe to run even if some columns already exist (uses IF NOT EXISTS everywhere).

alter table products add column if not exists cost_price numeric;

alter table customers add column if not exists preferred_language text;
alter table customers add column if not exists page_token text;
create unique index if not exists customers_page_token_key on customers(page_token) where page_token is not null;

alter table orders add column if not exists source text not null default 'whatsapp';
alter table orders add column if not exists eta_minutes int;
alter table orders add column if not exists delivery_address text;
alter table orders add column if not exists is_duplicate_flag boolean not null default false;

alter table order_items add column if not exists cost_price numeric;

create table if not exists shop_settings (
  id bigint generated always as identity primary key,
  minimum_order_value numeric not null default 0,
  business_hours_start int not null default 7,
  business_hours_end int not null default 22,
  updated_at timestamptz not null default now()
);
insert into shop_settings (minimum_order_value, business_hours_start, business_hours_end)
  select 0, 7, 22
  where not exists (select 1 from shop_settings);

create index if not exists idx_orders_customer on orders(customer_id);
create index if not exists idx_orders_created on orders(created_at desc);
create index if not exists idx_orders_status on orders(status);
create index if not exists idx_order_items_order on order_items(order_id);

-- Backfill cost_price for the starter menu items, if they still have the default names
-- and no cost_price set yet. Safe no-op if you've already customized your menu.
update products set cost_price = 80  where name_en = 'Mango' and cost_price is null;
update products set cost_price = 35  where name_en = 'Banana' and cost_price is null;
update products set cost_price = 50  where name_en = 'Orange' and cost_price is null;
update products set cost_price = 65  where name_en = 'Grapes' and cost_price is null;
update products set cost_price = 100 where name_en = 'Pomegranate' and cost_price is null;
update products set cost_price = 30  where name_en = 'Watermelon' and cost_price is null;
update products set cost_price = 130 where name_en = 'Apple' and cost_price is null;
