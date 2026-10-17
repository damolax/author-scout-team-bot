-- Phase 6 encrypted Gmail connector, verified sender identities and safe campaigns.
-- Additive Neon STAGING only; no message sending activated by migration.

CREATE TABLE IF NOT EXISTS public.ld_gmail_connections (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 team_id integer NOT NULL REFERENCES public.teams(id),
 web_account_id integer NOT NULL REFERENCES public.web_accounts(id),
 google_subject text NOT NULL,
 primary_email text NOT NULL,
 refresh_token_encrypted text NOT NULL,
 scopes text[] NOT NULL DEFAULT ARRAY[]::text[],
 status text NOT NULL DEFAULT 'connected' CHECK(status IN ('connected','needs_reauth','disconnected')),
 verified_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (team_id,google_subject)
);

CREATE TABLE IF NOT EXISTS public.ld_gmail_oauth_states (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 team_id integer NOT NULL REFERENCES public.teams(id),
 web_account_id integer NOT NULL REFERENCES public.web_accounts(id),
 nonce_sha256 text NOT NULL UNIQUE,
 requested_scope text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL DEFAULT (now()+interval '10 minutes'),
 used_at timestamptz
);

CREATE TABLE IF NOT EXISTS public.ld_gmail_sender_identities (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 connection_id uuid NOT NULL REFERENCES public.ld_gmail_connections(id),
 email text NOT NULL,
 display_name text,
 verification_status text NOT NULL DEFAULT 'unverified' CHECK(verification_status IN ('verified','unverified','pending')),
 verification_source text NOT NULL DEFAULT 'manual_candidate' CHECK(verification_source IN ('google_primary','gmail_send_as','manual_candidate')),
 enabled boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(connection_id,email)
);

CREATE TABLE IF NOT EXISTS public.ld_campaigns (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES public.ld_service_workspaces(id),
 name text NOT NULL,
 status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','paused','active','completed','archived')),
 sender_identity_id uuid REFERENCES public.ld_gmail_sender_identities(id),
 max_daily integer NOT NULL DEFAULT 10 CHECK(max_daily BETWEEN 1 AND 30),
 min_interval_seconds integer NOT NULL DEFAULT 180 CHECK(min_interval_seconds BETWEEN 120 AND 86400),
 send_window_start smallint NOT NULL DEFAULT 9 CHECK(send_window_start BETWEEN 0 AND 23),
 send_window_end smallint NOT NULL DEFAULT 17 CHECK(send_window_end BETWEEN 1 AND 24),
 timezone_name text NOT NULL DEFAULT 'UTC',
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(workspace_id,name)
);

CREATE TABLE IF NOT EXISTS public.ld_campaign_queue (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 campaign_id uuid NOT NULL REFERENCES public.ld_campaigns(id),
 message_record_id uuid NOT NULL REFERENCES public.ld_message_records(id),
 sender_identity_id uuid NOT NULL REFERENCES public.ld_gmail_sender_identities(id),
 recipient_email text NOT NULL,
 permission_basis text NOT NULL CHECK(permission_basis IN ('explicit_opt_in','existing_customer','documented_legitimate_interest')),
 permission_evidence text NOT NULL,
 approval_account_id integer NOT NULL REFERENCES public.web_accounts(id),
 status text NOT NULL DEFAULT 'pending_review' CHECK(status IN ('pending_review','approved','sending','sent','held','cancelled','failed','uncertain')),
 scheduled_at timestamptz,
 approved_at timestamptz,
 claimed_at timestamptz,
 sent_at timestamptz,
 provider_message_id text,
 failure_code text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(message_record_id),
 CHECK(length(trim(permission_evidence)) >= 18)
);

CREATE TABLE IF NOT EXISTS public.ld_campaign_sender_health (
 sender_identity_id uuid PRIMARY KEY REFERENCES public.ld_gmail_sender_identities(id),
 last_sent_at timestamptz,
 sent_today integer NOT NULL DEFAULT 0,
 sent_day date,
 last_error text,
 paused_until timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS ld_campaign_queue_provider_message_id_idx ON public.ld_campaign_queue(provider_message_id) WHERE provider_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ld_campaign_queue_due_idx ON public.ld_campaign_queue(status,scheduled_at);

CREATE INDEX IF NOT EXISTS ld_gmail_connections_owner_idx ON public.ld_gmail_connections(team_id,web_account_id);

CREATE INDEX IF NOT EXISTS ld_campaign_sender_identity_idx ON public.ld_campaigns(sender_identity_id);

-- Campaign ownership prevents teammates from sending from another account without authorization.
ALTER TABLE public.ld_campaigns ADD COLUMN IF NOT EXISTS owner_web_account_id integer REFERENCES public.web_accounts(id);
