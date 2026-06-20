-- Adds manual ordering support for the Dashboard (drag-to-prioritise) view.
-- Run this in the Supabase SQL editor (Dashboard → SQL Editor → New query).
-- Safe to run more than once.
--
-- sort_order is a float so tasks can be inserted between two others without
-- renumbering the whole list. NULL = not yet ordered.

alter table public.tasks
  add column if not exists sort_order double precision;
