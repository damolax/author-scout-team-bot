-- Durable encrypted chunk staging and resumable, service-scoped 50,000-row imports.
-- Data batches expire after completion; no outbound sending.

CREATE TABLE IF NOT EXISTS public.ld_bulk_upload_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES public.ld_service_workspaces(id),
 team_id integer NOT NULL REFERENCES public.teams(id),
 owner_account_id integer NOT NULL REFERENCES public.web_accounts(id),
 filename text NOT NULL,
 bytes_total integer NOT NULL CHECK (bytes_total BETWEEN 1 AND 67108864),
 part_size integer NOT NULL DEFAULT 1048576,
 part_count integer NOT NULL CHECK (part_count BETWEEN 1 AND 64),
 sha256 text NOT NULL CHECK (length(sha256)=64),
 status text NOT NULL DEFAULT 'uploading' CHECK (status IN ('uploading','previewing','ready','queued','processing','completed','failed','cancelled')),
 preview_summary jsonb,
 preview_sample jsonb,
 preview_sheet text,
 preview_columns jsonb,
 processed_parts integer NOT NULL DEFAULT 0,
 processed_rows integer NOT NULL DEFAULT 0,
 accepted_rows integer NOT NULL DEFAULT 0,
 skipped_rows integer NOT NULL DEFAULT 0,
 rows_total integer,
 last_error text,
 lease_expires_at timestamptz,
 started_at timestamptz,
 finished_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(team_id,workspace_id,sha256),
 CHECK(processed_parts>=0),
 CHECK(processed_rows>=0)
);

CREATE TABLE IF NOT EXISTS public.ld_bulk_upload_parts (
 job_id uuid NOT NULL REFERENCES public.ld_bulk_upload_jobs(id) ON DELETE CASCADE,
 part_number integer NOT NULL CHECK (part_number BETWEEN 0 AND 63),
 size_bytes integer NOT NULL CHECK (size_bytes BETWEEN 1 AND 1048576),
 sha256 text NOT NULL CHECK (length(sha256)=64),
 encrypted_bytes bytea NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(job_id,part_number)
);

CREATE INDEX IF NOT EXISTS ld_bulk_jobs_owner_status_idx ON public.ld_bulk_upload_jobs(team_id,workspace_id,status,created_at DESC);

CREATE INDEX IF NOT EXISTS ld_bulk_jobs_worker_idx ON public.ld_bulk_upload_jobs(status,created_at) WHERE status IN ('queued','processing');
