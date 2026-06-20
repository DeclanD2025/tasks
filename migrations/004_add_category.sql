-- Adds a freeform category/label per task (e.g. "Article: Why Alfred?",
-- "Book chapter: 3"). Run in the Supabase SQL editor. Safe to run repeatedly.
-- The app auto-detects this column and persists category once it exists;
-- until then it works locally.

alter table public.tasks
  add column if not exists category text;
