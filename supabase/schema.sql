-- Gateway v1 schema — owner-scoped data model (SRS §7).
--
-- Apply with:  supabase db push   (or paste into the SQL editor)
--
-- Every row that belongs to a person carries an owner id equal to
-- ``auth.users.id``. Row Level Security is enabled on every table and there is
-- no permissive policy anywhere: an anonymous request reads zero rows, and a
-- signed-in request sees only its own. The API additionally scopes queries by
-- the verified principal (SRS DR-4); RLS is the second line, not the first.
--
-- This supersedes the earlier journal-mirror schema. Those tables were part of
-- a deferred surface (SRS §8) and are not created here; if an instance has
-- them, leave them alone — nothing in v1 reads or writes them.

-- ---------------------------------------------------------------------------
-- Identity mirror
-- ---------------------------------------------------------------------------

create table if not exists profiles (
  id            uuid primary key references auth.users (id) on delete cascade,
  email         text not null,
  display_name  text,
  created_at    timestamptz not null default now()
);

create table if not exists preferences (
  user_id         uuid primary key references profiles (id) on delete cascade,
  theme           text not null default 'dark',
  default_timezone text not null default 'UTC',
  watchlists      jsonb not null default '[]'::jsonb,
  saved_layouts   jsonb not null default '{}'::jsonb,
  updated_at      timestamptz not null default now()
);

-- NFR-29. The id is text so it can hold either an auth.users UUID or the
-- lazily provisioned gateway_users id the API already uses.
create table if not exists notice_acceptances (
  user_id     text primary key,
  version     text not null,
  accepted_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Research artefacts
-- ---------------------------------------------------------------------------

create table if not exists strategies (
  id          uuid primary key default gen_random_uuid(),
  owner_id    uuid not null references profiles (id) on delete cascade,
  name        text not null,
  created_at  timestamptz not null default now()
);
create index if not exists strategies_owner_idx on strategies (owner_id);

create table if not exists strategy_versions (
  id            uuid primary key default gen_random_uuid(),
  strategy_id   uuid not null references strategies (id) on delete cascade,
  version       integer not null check (version > 0),
  spec          jsonb not null,
  content_hash  text not null,
  created_at    timestamptz not null default now(),
  unique (strategy_id, version)
);

create table if not exists backtest_runs (
  id                  uuid primary key default gen_random_uuid(),
  owner_id            uuid not null references profiles (id) on delete cascade,
  strategy_version_id uuid not null references strategy_versions (id) on delete cascade,
  receipt             jsonb not null,   -- data hash, window, costs, engine version, seed
  metrics             jsonb not null,
  created_at          timestamptz not null default now()
);
create index if not exists backtest_runs_owner_idx on backtest_runs (owner_id);

-- ---------------------------------------------------------------------------
-- Simulated trading (never broker facts)
-- ---------------------------------------------------------------------------

create table if not exists portfolios (
  id             uuid primary key default gen_random_uuid(),
  owner_id       uuid not null references profiles (id) on delete cascade,
  cash           numeric(18, 2) not null default 100000,
  base_currency  text not null default 'USD',
  created_at     timestamptz not null default now()
);
create index if not exists portfolios_owner_idx on portfolios (owner_id);

create table if not exists orders (
  id            uuid primary key default gen_random_uuid(),
  portfolio_id  uuid not null references portfolios (id) on delete cascade,
  symbol        text not null,
  side          text not null check (side in ('buy', 'sell')),
  qty           numeric(18, 6) not null check (qty > 0),
  type          text not null check (type in ('market', 'limit', 'stop', 'stop_limit')),
  status        text not null default 'pending_new',
  simulated     boolean not null default true check (simulated),
  created_at    timestamptz not null default now()
);
create index if not exists orders_portfolio_idx on orders (portfolio_id);

create table if not exists fills (
  id          uuid primary key default gen_random_uuid(),
  order_id    uuid not null references orders (id) on delete cascade,
  price       numeric(18, 6) not null,
  qty         numeric(18, 6) not null,
  costs       jsonb not null default '{}'::jsonb,
  simulated   boolean not null default true check (simulated),
  filled_at   timestamptz not null default now()
);

create table if not exists positions (
  portfolio_id  uuid not null references portfolios (id) on delete cascade,
  symbol        text not null,
  qty           numeric(18, 6) not null default 0,
  avg_price     numeric(18, 6) not null default 0,
  primary key (portfolio_id, symbol)
);

-- ---------------------------------------------------------------------------
-- Bot runner
-- ---------------------------------------------------------------------------

create table if not exists bot_runs (
  id                  uuid primary key default gen_random_uuid(),
  owner_id            uuid not null references profiles (id) on delete cascade,
  strategy_version_id uuid not null references strategy_versions (id) on delete cascade,
  status              text not null default 'running' check (status in ('running', 'stopped', 'failed')),
  started_at          timestamptz not null default now(),
  stopped_at          timestamptz
);
create index if not exists bot_runs_owner_idx on bot_runs (owner_id);

create table if not exists bot_logs (
  id            bigserial primary key,
  bot_run_id    uuid not null references bot_runs (id) on delete cascade,
  bar_time      timestamptz not null,
  signal        jsonb not null default '{}'::jsonb,
  risk_verdict  text,
  action        text
);
create index if not exists bot_logs_run_idx on bot_logs (bot_run_id, bar_time);

-- ---------------------------------------------------------------------------
-- Row Level Security (DR-1 … DR-5)
-- ---------------------------------------------------------------------------

alter table profiles          enable row level security;
alter table preferences       enable row level security;
alter table notice_acceptances enable row level security;
alter table strategies        enable row level security;
alter table strategy_versions enable row level security;
alter table backtest_runs     enable row level security;
alter table portfolios        enable row level security;
alter table orders            enable row level security;
alter table fills             enable row level security;
alter table positions         enable row level security;
alter table bot_runs          enable row level security;
alter table bot_logs          enable row level security;

-- Owner-identified rows: match the authenticated principal exactly.
create policy profiles_owner on profiles
  for all using (auth.uid() = id) with check (auth.uid() = id);

create policy preferences_owner on preferences
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy notice_acceptances_owner on notice_acceptances
  for all using (auth.uid()::text = user_id) with check (auth.uid()::text = user_id);

create policy strategies_owner on strategies
  for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

create policy backtest_runs_owner on backtest_runs
  for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

create policy portfolios_owner on portfolios
  for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

create policy bot_runs_owner on bot_runs
  for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- Child rows: ownership is inherited through the parent. The `exists` clause
-- is what stops a caller inserting a run under somebody else's strategy.
create policy strategy_versions_owner on strategy_versions
  for all using (
    exists (select 1 from strategies s where s.id = strategy_versions.strategy_id and s.owner_id = auth.uid())
  ) with check (
    exists (select 1 from strategies s where s.id = strategy_versions.strategy_id and s.owner_id = auth.uid())
  );

create policy orders_owner on orders
  for all using (
    exists (select 1 from portfolios p where p.id = orders.portfolio_id and p.owner_id = auth.uid())
  ) with check (
    exists (select 1 from portfolios p where p.id = orders.portfolio_id and p.owner_id = auth.uid())
  );

create policy fills_owner on fills
  for all using (
    exists (
      select 1 from orders o join portfolios p on p.id = o.portfolio_id
      where o.id = fills.order_id and p.owner_id = auth.uid()
    )
  ) with check (
    exists (
      select 1 from orders o join portfolios p on p.id = o.portfolio_id
      where o.id = fills.order_id and p.owner_id = auth.uid()
    )
  );

create policy positions_owner on positions
  for all using (
    exists (select 1 from portfolios p where p.id = positions.portfolio_id and p.owner_id = auth.uid())
  ) with check (
    exists (select 1 from portfolios p where p.id = positions.portfolio_id and p.owner_id = auth.uid())
  );

create policy bot_logs_owner on bot_logs
  for all using (
    exists (select 1 from bot_runs r where r.id = bot_logs.bot_run_id and r.owner_id = auth.uid())
  ) with check (
    exists (select 1 from bot_runs r where r.id = bot_logs.bot_run_id and r.owner_id = auth.uid())
  );

-- DR-6: rows that predate ownership have no owner and match no policy, so they
-- are invisible to every user route. They are never auto-assigned (DR-7).

-- DR-5 check: an anonymous client must see nothing.
--   select count(*) from strategies;   -- as anon: 0

-- ---------------------------------------------------------------------------
-- Notice acceptance RPCs (NFR-29)
-- ---------------------------------------------------------------------------
-- Same SECURITY DEFINER + `_gw_check` shape as the auth/preferences RPCs.
-- The API derives p_user_id from the verified principal, never from the
-- browser, and the RLS policy above independently scopes direct table reads.

create or replace function public.gw_get_notice_acceptance(p_secret text, p_user_id text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  perform public._gw_check(p_secret);
  return (
    select jsonb_build_object('version', n.version, 'accepted_at', n.accepted_at)
    from public.notice_acceptances n
    where n.user_id = p_user_id
    limit 1
  );
end;
$$;

create or replace function public.gw_accept_notice(p_secret text, p_user_id text, p_version text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  result jsonb;
begin
  perform public._gw_check(p_secret);
  insert into notice_acceptances (user_id, version, accepted_at)
  values (p_user_id, p_version, now())
  on conflict (user_id) do update
    set version = excluded.version, accepted_at = excluded.accepted_at
  returning jsonb_build_object('version', version, 'accepted_at', accepted_at) into result;
  return result;
end;
$$;
