-- Gateway journal schema for a hosted Supabase (Postgres) instance.
--
-- Mirrors quant-app-v1/backend/app/services/journal_log.py so real (actual)
-- and simulated (paper) trades can be analysed in Supabase / connected BI
-- tools alongside the local SQLite copy the app writes.
--
-- Apply with:  supabase db push   (or paste into the SQL editor)

create table if not exists journal_entries (
  id           text primary key,
  symbol       text not null,
  side         text not null check (side in ('buy', 'sell')),
  quantity     double precision not null,
  entry_price  double precision not null,
  entry_time   timestamptz not null,
  hypothesis   text not null,
  entry_context text default '',
  exit_price   double precision,
  exit_time    timestamptz,
  exit_context text,
  pnl          double precision,
  pnl_pct      double precision,
  rating       smallint check (rating between 1 and 5),
  lessons      text,
  tags         jsonb default '[]'::jsonb,
  status       text not null default 'open' check (status in ('open', 'closed')),
  source       text not null default 'manual' check (source in ('paper', 'actual', 'manual')),
  fill_id      text,
  created_at   timestamptz not null,
  updated_at   timestamptz not null
);

create index if not exists journal_entries_symbol_idx  on journal_entries (symbol);
create index if not exists journal_entries_status_idx  on journal_entries (status);
create index if not exists journal_entries_source_idx  on journal_entries (source);
create index if not exists journal_entries_created_idx on journal_entries (created_at);

create table if not exists journal_fill_log (
  fill_id    text primary key,
  entry_id   text,
  source     text not null default 'paper',
  applied_at timestamptz not null
);

-- Paper vs actual performance at a glance.
create or replace view journal_performance_by_source as
select
  source,
  count(*)                                                   as total_trades,
  count(*) filter (where status = 'closed')                  as closed_trades,
  count(*) filter (where status = 'closed' and pnl > 0)      as winning_trades,
  coalesce(sum(pnl) filter (where status = 'closed'), 0)     as total_pnl,
  avg(pnl) filter (where status = 'closed' and pnl > 0)      as avg_win,
  avg(pnl) filter (where status = 'closed' and pnl <= 0)     as avg_loss
from journal_entries
group by source;

-- Row Level Security: restrict by a Supabase auth uid if you attach one.
alter table journal_entries   enable row level security;
alter table journal_fill_log  enable row level security;

-- Default policy for service-role access (the Gateway backend); swap in a
-- per-user policy once Supabase Auth is wired to Gateway sessions.
create policy "service role full access"
  on journal_entries for all
  using (true)
  with check (true);
