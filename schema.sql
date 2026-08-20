-- Run this in Supabase SQL editor

create table if not exists products (
  id bigint generated always as identity primary key,
  name_en text not null,
  name_hi text,
  unit text not null default 'kg',       -- kg, dozen, piece, box
  price numeric not null,
  is_available boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists customers (
  id bigint generated always as identity primary key,
  wa_number text unique not null,        -- WhatsApp number, e.g. 919876543210
  name text,
  address text,
  created_at timestamptz not null default now()
);

create table if not exists orders (
  id bigint generated always as identity primary key,
  customer_id bigint references customers(id),
  status text not null default 'new',    -- new, confirmed, out_for_delivery, delivered, cancelled
  fulfillment text not null default 'delivery',  -- delivery, pickup
  payment_mode text not null default 'unset',    -- upi, cod, unset
  payment_status text not null default 'pending', -- pending, paid, na
  total numeric not null default 0,
  notes text,
  raw_message text,                      -- original customer text, for debugging/audit
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists order_items (
  id bigint generated always as identity primary key,
  order_id bigint references orders(id) on delete cascade,
  product_id bigint references products(id),
  product_name text not null,            -- snapshot, in case product renamed/deleted later
  quantity numeric not null,
  unit text not null,
  unit_price numeric not null,
  line_total numeric not null
);

-- seed starter menu — edit prices/items to match your actual shop
insert into products (name_en, name_hi, unit, price) values
  ('Mango', 'आम', 'kg', 120),
  ('Banana', 'केला', 'dozen', 60),
  ('Orange', 'संतरा', 'kg', 80),
  ('Grapes', 'अंगूर', 'kg', 100),
  ('Pomegranate', 'अनार', 'kg', 150),
  ('Watermelon', 'तरबूज़', 'piece', 50),
  ('Apple', 'सेब', 'kg', 180)
on conflict do nothing;
