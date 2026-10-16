-- Letter Desk 2.0 staging-only, idempotent backfill of existing Author Scout records.
-- Prerequisites: 20261016_letterdesk_unified_neon_phase1.sql and 20261016_letterdesk_legacy_records.sql.
-- No original prospects/messages are deleted or updated. Deleted messages become tombstones only.
-- Apply statements inside a single transaction; run the audit SQL after the transaction.

ALTER TABLE public.ld_conversations ADD COLUMN IF NOT EXISTS legacy_message_id integer;

CREATE UNIQUE INDEX IF NOT EXISTS ld_conversations_legacy_message_id_key ON public.ld_conversations(legacy_message_id) WHERE legacy_message_id IS NOT NULL;

INSERT INTO public.ld_service_workspaces(team_id,service_key,display_name)
 SELECT t.id,s.service_key,s.display_name FROM public.teams t CROSS JOIN
 (VALUES ('author','Author Scouting'),('automation','Automation Scouting'),('website-design','Website Design Scouting'),('digital-planner','Digital Planner Scouting'),('shopify','Shopify Scouting'),('google-maps','Google Maps Scouting')) AS s(service_key,display_name)
 ON CONFLICT (team_id,service_key) DO NOTHING;

INSERT INTO public.ld_leads(team_id,dedupe_key,name,kind,email,website,country,source_url,contact_verification,details)
 SELECT p.claimed_team_id,p.normalized_key,p.name,'person',
 NULLIF(trim(p.email),''),NULLIF(trim(p.website),''),NULLIF(trim(p.country),''),
 COALESCE(NULLIF(trim(p.email_source_url),''),NULLIF(trim(p.discovery_source_url),'')),
 COALESCE(NULLIF(trim(p.verification_status),''),'unverified'),
 jsonb_build_object(
   'legacy_prospect_id',p.id,'genre',p.genre,'books',p.books,'bio',p.bio,
   'recent_activity',p.recent_activity,'source_urls',p.source_urls,
   'email_source_url',p.email_source_url,'discovery_platform',p.discovery_platform,
   'discovery_source_type',p.discovery_source_type,'discovery_query',p.discovery_query,
   'discovery_evidence',p.discovery_evidence,'discovery_confidence',p.discovery_confidence,
   'legacy_claimed_at',p.claimed_at,'legacy_updated_at',p.updated_at
 ) FROM public.prospects p
 JOIN public.teams t ON t.id=p.claimed_team_id
 ON CONFLICT(team_id,dedupe_key) DO NOTHING;

INSERT INTO public.ld_legacy_links(source_table,legacy_id,team_id,target_id,disposition)
 SELECT 'prospects',p.id,p.claimed_team_id,l.id,'migrated'
 FROM public.prospects p JOIN public.ld_leads l
 ON l.team_id=p.claimed_team_id AND l.dedupe_key=p.normalized_key
 ON CONFLICT(source_table,legacy_id) DO NOTHING;

INSERT INTO public.ld_opportunities(workspace_id,lead_id,status,service_details,evidence_summary)
 SELECT ws.id,l.id,
 CASE WHEN p.verification_status='verified_public' THEN 'research_complete' ELSE 'research_needed' END,
 jsonb_build_object('legacy_prospect_id',p.id,'genre',p.genre,'books',p.books),
 NULLIF(trim(p.discovery_evidence),'')
 FROM public.prospects p
 JOIN public.ld_legacy_links link ON link.source_table='prospects' AND link.legacy_id=p.id
 JOIN public.ld_leads l ON l.id=link.target_id
 JOIN public.ld_service_workspaces ws ON ws.team_id=p.claimed_team_id AND ws.service_key='author'
 WHERE link.disposition='migrated'
 ON CONFLICT(workspace_id,lead_id) DO NOTHING;

INSERT INTO public.ld_conversations(opportunity_id,status,message_count,reply_classification,legacy_message_id)
 SELECT o.id,
 CASE WHEN m.status='sent' THEN 'awaiting_reply' ELSE 'draft' END,
 CASE WHEN m.status='sent' THEN 1 ELSE 0 END,
 NULLIF(trim(m.reply_status),''),m.id
 FROM public.messages m
 JOIN public.ld_legacy_links link ON link.source_table='prospects' AND link.legacy_id=m.prospect_id
 JOIN public.ld_opportunities o ON o.lead_id=link.target_id
 JOIN public.ld_service_workspaces ws ON ws.id=o.workspace_id AND ws.team_id=m.team_id AND ws.service_key='author'
 WHERE m.status IN ('ready','sent')
 ON CONFLICT(legacy_message_id) DO NOTHING;

INSERT INTO public.ld_message_records(conversation_id,legacy_message_id,recipient_email,subject,body,body_english,sender_email,status,legacy_status,sent_at_original,reply_notes,raw_metadata)
 SELECT c.id,m.id,COALESCE(NULLIF(trim(m.recipient_email),''),NULLIF(trim(p.email),''),''),
 COALESCE(m.subject,''),COALESCE(m.body,''),COALESCE(m.body_english,''),
 NULLIF(trim(m.sender_email),''),
 CASE WHEN m.status='sent' THEN 'sent' ELSE 'needs_review' END,
 m.status,m.sent_at,m.reply_notes,
 jsonb_build_object('old_team_id',m.team_id,'legacy_opened_at',m.opened_at,'legacy_replied_at',m.replied_at,'sent_via',m.sent_via,'auto_sent',m.auto_sent,'legacy_created_at',m.created_at,'legacy_updated_at',m.updated_at)
 FROM public.messages m
 JOIN public.ld_conversations c ON c.legacy_message_id=m.id
 JOIN public.prospects p ON p.id=m.prospect_id
 WHERE m.status IN ('ready','sent')
 ON CONFLICT(legacy_message_id) DO NOTHING;

INSERT INTO public.ld_legacy_links(source_table,legacy_id,team_id,target_id,disposition)
 SELECT 'messages',m.id,m.team_id,
 CASE WHEN m.status='deleted' THEN NULL ELSE c.id END,
 CASE WHEN m.status='deleted' THEN 'deleted_tombstone' ELSE 'migrated' END
 FROM public.messages m
 LEFT JOIN public.ld_conversations c ON c.legacy_message_id=m.id
 WHERE m.status IN ('ready','sent','deleted')
 ON CONFLICT(source_table,legacy_id) DO NOTHING;
