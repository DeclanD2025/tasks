-- Adds recurrence support to the tasks table.
-- Run this in the Supabase SQL editor (Dashboard → SQL Editor → New query).
-- Safe to run more than once.
--
-- Values used by the app: NULL (no repeat), 'daily', 'weekly', 'monthly'.

alter table public.tasks
  add column if not exists recurrence text;

-- Optional: constrain to the supported values.
alter table public.tasks
  drop constraint if exists tasks_recurrence_check;
alter table public.tasks
  add constraint tasks_recurrence_check
  check (recurrence is null or recurrence in ('daily', 'weekly', 'monthly'));
