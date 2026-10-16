-- Letter Desk 2.0 — additive initial Neon schema.
-- FOR STAGING FIRST. Does not modify or delete existing prospects/messages/teams.
-- All DDL below uses IF NOT EXISTS and the ld_ prefix to avoid changing legacy tables.

CREATE TABLE IF NOT EXISTS public.ld_service_workspaces (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 team_id integer NOT NULL REFERENCES public.teams(id),
 service_key text NOT NULL CHECK (service_key IN ('author','automation','website-design','digital-planner','shopify','google-maps')),
 display_name text NOT NULL,
 settings jsonb NOT NULL DEFAULT '{}'::jsonb,
 is_active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(team_id,service_key)
);

CREATE TABLE IF NOT EXISTS public.ld_leads (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 team_id integer NOT NULL REFERENCES public.teams(id),
 dedupe_key text NOT NULL,
 name text NOT NULL,
 kind text NOT NULL DEFAULT 'business' CHECK (kind IN ('person','business')),
 email text, website text, maps_url text, country text, city text,
 source_url text, details jsonb NOT NULL DEFAULT '{}'::jsonb,
 contact_verification text NOT NULL DEFAULT 'unverified',
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (team_id,dedupe_key)
);

CREATE TABLE IF NOT EXISTS public.ld_opportunities (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES public.ld_service_workspaces(id),
 lead_id uuid NOT NULL REFERENCES public.ld_leads(id),
 status text NOT NULL DEFAULT 'new',
 fit_score integer CHECK (fit_score IS NULL OR (fit_score BETWEEN 0 AND 100)),
 evidence_summary text, service_details jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(workspace_id, lead_id)
);

CREATE TABLE IF NOT EXISTS public.ld_evidence (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 lead_id uuid NOT NULL REFERENCES public.ld_leads(id),
 opportunity_id uuid REFERENCES public.ld_opportunities(id),
 source_url text NOT NULL,
 observation text, confidence text NOT NULL DEFAULT 'unconfirmed',
 collected_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ld_import_batches (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES public.ld_service_workspaces(id),
 filename text NOT NULL,
 file_storage_key text,
 source_format text CHECK(source_format IN ('csv','xlsx','xlsm')),
 status text NOT NULL DEFAULT 'pending',
 rows_total integer NOT NULL DEFAULT 0,
 rows_imported integer NOT NULL DEFAULT 0,
 rows_skipped integer NOT NULL DEFAULT 0,
 column_map jsonb NOT NULL DEFAULT '{}'::jsonb,
 issues jsonb NOT NULL DEFAULT '[]'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz
);

CREATE TABLE IF NOT EXISTS public.ld_message_flows (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES public.ld_service_workspaces(id),
 name text NOT NULL,
 version integer NOT NULL DEFAULT 1,
 status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','archived')),
 language text NOT NULL DEFAULT 'en',
 max_messages_per_contact integer NOT NULL DEFAULT 3 CHECK(max_messages_per_contact BETWEEN 1 AND 12),
 max_no_reply_followups integer NOT NULL DEFAULT 1 CHECK(max_no_reply_followups BETWEEN 0 AND 3),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(workspace_id,name,version)
);

CREATE TABLE IF NOT EXISTS public.ld_message_nodes (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 flow_id uuid NOT NULL REFERENCES public.ld_message_flows(id) ON DELETE CASCADE,
 node_code text NOT NULL,
 variant_group text,
 stage text NOT NULL DEFAULT 'generic',
 subject_template text NOT NULL DEFAULT '',
 body_template text NOT NULL DEFAULT '',
 delay_minutes integer NOT NULL DEFAULT 0 CHECK(delay_minutes >= 0),
 review_required boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(flow_id,node_code)
);

CREATE TABLE IF NOT EXISTS public.ld_message_edges (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 from_node_id uuid NOT NULL REFERENCES public.ld_message_nodes(id) ON DELETE CASCADE,
 to_node_id uuid REFERENCES public.ld_message_nodes(id) ON DELETE CASCADE,
 outcome text NOT NULL CHECK(outcome IN ('positive','question','objection','not_now','negative','opt_out','no_reply','bounce','uncertain')),
 action text NOT NULL CHECK(action IN ('draft_for_review','queue_approved','stop','wait','manual_review')),
 guard_conditions jsonb NOT NULL DEFAULT '{}'::jsonb,
 CHECK(outcome NOT IN ('negative','opt_out','bounce') OR (action='stop' AND to_node_id IS NULL)),
 CHECK(action <> 'stop' OR to_node_id IS NULL),
 UNIQUE(from_node_id,outcome)
);

CREATE TABLE IF NOT EXISTS public.ld_suppressions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 team_id integer NOT NULL REFERENCES public.teams(id),
 normalized_email text NOT NULL,
 reason text NOT NULL CHECK(reason IN ('opt_out','explicit_decline','hard_bounce','legal','manual')),
 source text,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(team_id,normalized_email)
);

CREATE TABLE IF NOT EXISTS public.ld_sender_assignments (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES public.ld_service_workspaces(id),
 google_account_ref text NOT NULL,
 gmail_address text NOT NULL,
 alias_email text NOT NULL,
 alias_verified boolean NOT NULL DEFAULT false,
 is_default boolean NOT NULL DEFAULT false,
 enabled boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(workspace_id,google_account_ref,alias_email)
);

CREATE TABLE IF NOT EXISTS public.ld_conversations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 opportunity_id uuid NOT NULL REFERENCES public.ld_opportunities(id),
 flow_id uuid REFERENCES public.ld_message_flows(id),
 current_node_id uuid REFERENCES public.ld_message_nodes(id),
 status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','awaiting_reply','needs_review','qualified','won','lost','stopped')),
 message_count integer NOT NULL DEFAULT 0,
 no_reply_followups integer NOT NULL DEFAULT 0,
 reply_classification text,
 next_action_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ld_outreach_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 team_id integer NOT NULL REFERENCES public.teams(id),
 conversation_id uuid REFERENCES public.ld_conversations(id),
 event_key text,
 event_type text NOT NULL,
 provider_message_id text,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 occurred_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(team_id,event_key)
);

CREATE INDEX IF NOT EXISTS ld_opportunities_status_idx ON public.ld_opportunities(workspace_id,status);

CREATE INDEX IF NOT EXISTS ld_evidence_lead_idx ON public.ld_evidence(lead_id,collected_at DESC);

CREATE INDEX IF NOT EXISTS ld_conversations_actions_idx ON public.ld_conversations(status,next_action_at);

CREATE INDEX IF NOT EXISTS ld_suppressions_email_idx ON public.ld_suppressions(normalized_email);
