-- Phase 3: discovery job queue and source evidence. Staging-first; additive only.

CREATE TABLE IF NOT EXISTS public.ld_discovery_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES public.ld_service_workspaces(id),
 requested_by text NOT NULL DEFAULT '',
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed','cancelled')),
 mode text NOT NULL DEFAULT 'web' CHECK(mode IN ('web','maps','seed')),
 niche text NOT NULL DEFAULT '',
 city text NOT NULL DEFAULT '',
 country text NOT NULL DEFAULT '',
 start_urls jsonb NOT NULL DEFAULT '[]'::jsonb,
 extra_signals jsonb NOT NULL DEFAULT '[]'::jsonb,
 query_plan jsonb NOT NULL DEFAULT '[]'::jsonb,
 max_queries integer NOT NULL DEFAULT 2 CHECK(max_queries BETWEEN 0 AND 4),
 max_results integer NOT NULL DEFAULT 6 CHECK(max_results BETWEEN 1 AND 15),
 max_sites integer NOT NULL DEFAULT 8 CHECK(max_sites BETWEEN 1 AND 20),
 queries_run integer NOT NULL DEFAULT 0,
 pages_scanned integer NOT NULL DEFAULT 0,
 leads_created integer NOT NULL DEFAULT 0,
 leads_linked integer NOT NULL DEFAULT 0,
 rejected_results integer NOT NULL DEFAULT 0,
 notes jsonb NOT NULL DEFAULT '[]'::jsonb,
 error text,
 created_at timestamptz NOT NULL DEFAULT now(),
 started_at timestamptz,
 completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS public.ld_discovery_results (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 job_id uuid NOT NULL REFERENCES public.ld_discovery_jobs(id),
 workspace_id uuid NOT NULL REFERENCES public.ld_service_workspaces(id),
 lead_id uuid REFERENCES public.ld_leads(id),
 source_url text NOT NULL,
 normalized_url text NOT NULL,
 name text NOT NULL DEFAULT '',
 email text,
 evidence_text text,
 email_source_url text,
 evidence_type text NOT NULL DEFAULT 'observed_page',
 status text NOT NULL DEFAULT 'collected' CHECK(status IN ('collected','lead_created','existing_lead','rejected','needs_review')),
 reason text,
 collected_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(job_id, normalized_url)
);

CREATE INDEX IF NOT EXISTS ld_discovery_jobs_queue_idx ON public.ld_discovery_jobs(workspace_id,status,created_at DESC);

CREATE INDEX IF NOT EXISTS ld_discovery_results_lead_idx ON public.ld_discovery_results(lead_id,collected_at DESC);
