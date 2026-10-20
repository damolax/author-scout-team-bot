-- Approved per-field changes only. Never logs tokens, sends, or deletes messages.
CREATE TABLE IF NOT EXISTS public.ld_prospect_field_audit (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 team_id integer NOT NULL REFERENCES public.teams(id),
 workspace_id uuid NOT NULL REFERENCES public.ld_service_workspaces(id),
 lead_id uuid NOT NULL REFERENCES public.ld_leads(id),
 opportunity_id uuid NOT NULL REFERENCES public.ld_opportunities(id),
 reviewer_account_id integer NOT NULL REFERENCES public.web_accounts(id),
 field_name text NOT NULL,
 previous_value text,
 accepted_value text NOT NULL,
 source_file_sha256 text NOT NULL,
 file_row_number integer NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ld_prospect_field_audit_lookup ON public.ld_prospect_field_audit(team_id,lead_id,created_at DESC);
ALTER TABLE public.ld_prospect_field_audit ADD COLUMN IF NOT EXISTS decision text NOT NULL DEFAULT 'accepted' CHECK(decision IN ('accepted','rejected'));
