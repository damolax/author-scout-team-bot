-- Letter Desk Phase 4 additive import audit and per-row branch drafts. No deletion of legacy data.

CREATE TABLE IF NOT EXISTS public.ld_import_rows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id uuid NOT NULL REFERENCES public.ld_import_batches(id),
  row_number integer NOT NULL,
  service_key text NOT NULL,
  disposition text NOT NULL CHECK(disposition IN ('created','linked','suppressed','invalid','skipped_duplicate')),
  identity_key text,
  lead_id uuid REFERENCES public.ld_leads(id),
  opportunity_id uuid REFERENCES public.ld_opportunities(id),
  message_record_id uuid REFERENCES public.ld_message_records(id),
  had_first_message boolean NOT NULL DEFAULT false,
  branch_templates jsonb NOT NULL DEFAULT '{}'::jsonb,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(batch_id,row_number)
);

ALTER TABLE public.ld_import_batches ADD COLUMN IF NOT EXISTS file_sha256 text;

ALTER TABLE public.ld_import_batches ADD COLUMN IF NOT EXISTS source_service text;

ALTER TABLE public.ld_import_batches ADD COLUMN IF NOT EXISTS owner_team_id integer REFERENCES public.teams(id);

ALTER TABLE public.ld_import_batches ADD COLUMN IF NOT EXISTS preview_summary jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.ld_import_batches ADD COLUMN IF NOT EXISTS rolled_back_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS ld_import_batches_team_sha_service_idx ON public.ld_import_batches(owner_team_id,source_service,file_sha256) WHERE rolled_back_at IS NULL AND status='completed';

CREATE INDEX IF NOT EXISTS ld_import_rows_batch_disposition_idx ON public.ld_import_rows(batch_id,disposition);

CREATE INDEX IF NOT EXISTS ld_import_rows_lead_idx ON public.ld_import_rows(lead_id);
