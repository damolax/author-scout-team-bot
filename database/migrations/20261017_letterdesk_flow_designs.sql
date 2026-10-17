-- Phase 5 draft-only visual conversation design, append-only revision history.
-- No legacy flow tables or Gmail routes are modified.

CREATE TABLE IF NOT EXISTS public.ld_flow_designs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES public.ld_service_workspaces(id),
 name text NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 110),
 language text NOT NULL DEFAULT 'en',
 status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','archived')),
 revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
 document jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (workspace_id,name)
);

CREATE TABLE IF NOT EXISTS public.ld_flow_design_revisions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 design_id uuid NOT NULL REFERENCES public.ld_flow_designs(id),
 revision integer NOT NULL CHECK(revision > 0),
 snapshot jsonb NOT NULL,
 edit_note text,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(design_id,revision)
);

CREATE INDEX IF NOT EXISTS ld_flow_designs_workspace_idx ON public.ld_flow_designs(workspace_id,status,updated_at DESC);

CREATE INDEX IF NOT EXISTS ld_flow_design_revisions_latest_idx ON public.ld_flow_design_revisions(design_id,revision DESC);
