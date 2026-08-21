-- Jay Fruit's order system — FULL SCHEMA (v2)
-- If starting fresh: run this whole file in Supabase SQL editor.
-- If upgrading from v1: run migration.sql instead (adds columns without dropping data).

create table if not exists products (
  id bigint generated always as identity primary key,
  name_en text not null,
  name_hi text,
  unit text not null default 'kg',
  price numeric not null,
  cost_price numeric,                    -- what you pay per unit — used for profit tracking. Null = unknown, margin hidden.
  is_available boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists customers (
  id bigint generated always as identity primary key,
  wa_number text unique not null,
  name text,
  address text,
  preferred_language text,               -- 'en' or 'hi' — set automatically from their first message
  page_token text unique,                -- random token for their personal menu/history page link
  created_at timestamptz not null default now()
);

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

create table if not exists orders (
  id bigint generated always as identity primary key,
  customer_id bigint references customers(id),
  status text not null default 'new',
  fulfillment text not null default 'delivery',
  payment_mode text not null default 'unset',
  payment_status text not null default 'pending',
  total numeric not null default 0,
  notes text,
  raw_message text,
  source text not null default 'whatsapp',  -- 'whatsapp' or 'phone'
  eta_minutes int,
  delivery_address text,
  is_duplicate_flag boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists order_items (
  id bigint generated always as identity primary key,
  order_id bigint references orders(id) on delete cascade,
  product_id bigint references products(id),
  product_name text not null,
  quantity numeric not null,
  unit text not null,
  unit_price numeric not null,
  cost_price numeric,
  line_total numeric not null
);

create index if not exists idx_orders_customer on orders(customer_id);
create index if not exists idx_orders_created on orders(created_at desc);
create index if not exists idx_orders_status on orders(status);
create index if not exists idx_order_items_order on order_items(order_id);

insert into products (name_en, name_hi, unit, price, cost_price) values
  ('Mango', 'आम', 'kg', 120, 80),
  ('Banana', 'केला', 'dozen', 60, 35),
  ('Orange', 'संतरा', 'kg', 80, 50),
  ('Grapes', 'अंगूर', 'kg', 100, 65),
  ('Pomegranate', 'अनार', 'kg', 150, 100),
  ('Watermelon', 'तरबूज़', 'piece', 50, 30),
  ('Apple', 'सेब', 'kg', 180, 130)
on conflict do nothing;
