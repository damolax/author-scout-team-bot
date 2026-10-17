-- Phase 1 / migration safety tables. Apply to a Neon staging branch before production.
-- Additive; never deletes legacy data.

CREATE TABLE IF NOT EXISTS public.ld_legacy_links (
 source_table text NOT NULL CHECK(source_table IN ('prospects','messages')),
 legacy_id integer NOT NULL,
 team_id integer NOT NULL REFERENCES public.teams(id),
 target_id uuid,
 disposition text NOT NULL CHECK(disposition IN ('migrated','deleted_tombstone','skipped')),
 recorded_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source_table,legacy_id)
);

CREATE TABLE IF NOT EXISTS public.ld_message_records (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 conversation_id uuid NOT NULL REFERENCES public.ld_conversations(id),
 legacy_message_id integer UNIQUE,
 recipient_email text NOT NULL,
 subject text NOT NULL DEFAULT '',
 body text NOT NULL DEFAULT '',
 body_english text NOT NULL DEFAULT '',
 sender_email text,
 status text NOT NULL DEFAULT 'needs_review' CHECK(status IN ('needs_review','approved','queued','sending','sent','replied','failed','suppressed')),
 legacy_status text,
 sent_at_original text,
 reply_notes text,
 provider_message_id text,
 raw_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ld_legacy_links_team_idx ON public.ld_legacy_links(team_id,source_table);

CREATE INDEX IF NOT EXISTS ld_message_records_conversation_idx ON public.ld_message_records(conversation_id,created_at DESC);

CREATE INDEX IF NOT EXISTS ld_message_records_status_idx ON public.ld_message_records(status,created_at DESC);
