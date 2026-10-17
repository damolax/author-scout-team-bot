-- Phase 7 minimal-authorized thread reply intake, audited review and frozen flow assignments.
-- Only additive Neon staging schema; no sending enabled.

ALTER TABLE public.ld_campaign_queue ADD COLUMN IF NOT EXISTS provider_thread_id text;

CREATE INDEX IF NOT EXISTS ld_campaign_queue_thread_idx ON public.ld_campaign_queue(sender_identity_id,provider_thread_id) WHERE provider_thread_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.ld_reply_inbox (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 team_id integer NOT NULL REFERENCES public.teams(id),
 workspace_id uuid NOT NULL REFERENCES public.ld_service_workspaces(id),
 conversation_id uuid NOT NULL REFERENCES public.ld_conversations(id),
 campaign_queue_id uuid REFERENCES public.ld_campaign_queue(id),
 gmail_connection_id uuid REFERENCES public.ld_gmail_connections(id),
 provider_message_id text,
 source text NOT NULL CHECK(source IN ('manual','gmail_thread')),
 manual_dedupe_key text,
 sender_email text NOT NULL,
 received_at timestamptz NOT NULL,
 body_encrypted text NOT NULL,
 suggested_outcome text NOT NULL,
 outcome_confidence text NOT NULL CHECK(outcome_confidence IN ('high','low','uncertain')),
 final_outcome text,
 status text NOT NULL DEFAULT 'pending_review' CHECK(status IN ('pending_review','reviewed','stopped')),
 flow_message_code text,
 proposed_next_code text,
 proposed_draft_encrypted text,
 reviewer_account_id integer REFERENCES public.web_accounts(id),
 reviewed_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (team_id,manual_dedupe_key),
 CHECK(length(sender_email)<=254)
);

CREATE UNIQUE INDEX IF NOT EXISTS ld_reply_provider_dedupe_idx ON public.ld_reply_inbox(gmail_connection_id,provider_message_id) WHERE gmail_connection_id IS NOT NULL AND provider_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ld_reply_workspace_review_idx ON public.ld_reply_inbox(workspace_id,status,received_at DESC);

CREATE INDEX IF NOT EXISTS ld_reply_conversation_idx ON public.ld_reply_inbox(conversation_id,received_at DESC);

CREATE TABLE IF NOT EXISTS public.ld_conversation_flow_bindings (
 conversation_id uuid PRIMARY KEY REFERENCES public.ld_conversations(id),
 flow_design_id uuid REFERENCES public.ld_flow_designs(id),
 flow_revision integer NOT NULL DEFAULT 1,
 service_key text NOT NULL,
 snapshot jsonb NOT NULL,
 current_code text NOT NULL DEFAULT 'Message01',
 assigned_account_id integer REFERENCES public.web_accounts(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ld_gmail_reply_sync (
 connection_id uuid PRIMARY KEY REFERENCES public.ld_gmail_connections(id),
 last_checked_at timestamptz,
 last_success_at timestamptz,
 last_error_code text,
 scanned_threads bigint NOT NULL DEFAULT 0,
 fetched_replies bigint NOT NULL DEFAULT 0,
 status text NOT NULL DEFAULT 'not_started' CHECK(status IN ('not_started','healthy','scope_missing','error','disconnected')),
 updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ld_queue_awaiting_reply_idx ON public.ld_campaign_queue(sender_identity_id,provider_thread_id,sent_at) WHERE status='sent' AND provider_thread_id IS NOT NULL;

-- Fair round-robin thread checks prevent older active conversations starving.
CREATE TABLE IF NOT EXISTS public.ld_gmail_thread_watch (
 queue_id uuid PRIMARY KEY REFERENCES public.ld_campaign_queue(id),
 last_checked_at timestamptz,
 last_error_code text,
 updated_at timestamptz NOT NULL DEFAULT now()
);
