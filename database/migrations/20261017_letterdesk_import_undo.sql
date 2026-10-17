-- Phase 8 reversible imports: retained audit, explicit reviewer and summary.
ALTER TABLE public.ld_import_batches ADD COLUMN IF NOT EXISTS undo_summary jsonb;
ALTER TABLE public.ld_import_batches ADD COLUMN IF NOT EXISTS undo_account_id integer REFERENCES public.web_accounts(id);
CREATE INDEX IF NOT EXISTS ld_import_batches_undo_lookup ON public.ld_import_batches(owner_team_id,source_service,status,created_at DESC);
