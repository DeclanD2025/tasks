-- Synced activity/usage log for the Stats page.
-- Run this in the Supabase SQL editor (Dashboard → SQL Editor → New query).
-- Safe to run more than once.
--
-- Append-only event stream: app opens (sessions) plus task
-- create/complete/reopen/delete. The app auto-detects this table, back-fills
-- any local history once, and writes here going forward.

create table if not exists public.events (
  id       uuid primary key default gen_random_uuid(),
  type     text not null,
  task_id  uuid,
  area     text,
  priority text,
  ts       timestamptz not null default now()
);

create index if not exists events_ts_idx on public.events (ts);

-- Match the tasks table's access model: allow the anon (publishable) key to
-- read and append. No update/delete policy = the log can't be tampered with.
alter table public.events enable row level security;

drop policy if exists "events_anon_select" on public.events;
create policy "events_anon_select" on public.events for select using (true);

drop policy if exists "events_anon_insert" on public.events;
create policy "events_anon_insert" on public.events for insert with check (true);
