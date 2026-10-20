-- Letter Desk 2.0 migration acceptance (read-only assertions).
-- Must run in Neon STAGING after both DDL files and backfill.
DO $audit$
DECLARE
 p_count bigint; m_count bigint; migrated_leads bigint; migrated_messages bigint; tombstones bigint;
 missing_leads bigint; missing_messages bigint; restored_deleted bigint; accidental_status bigint;
BEGIN
 SELECT count(*) INTO p_count FROM public.prospects;
 SELECT count(*) INTO m_count FROM public.messages WHERE status IN ('ready','sent');
 SELECT count(*) INTO migrated_leads FROM public.ld_legacy_links WHERE source_table='prospects' AND disposition='migrated';
 SELECT count(*) INTO migrated_messages FROM public.ld_message_records WHERE legacy_message_id IS NOT NULL;
 SELECT count(*) INTO tombstones FROM public.ld_legacy_links WHERE source_table='messages' AND disposition='deleted_tombstone';
 SELECT count(*) INTO missing_leads FROM public.prospects p LEFT JOIN public.ld_legacy_links l ON l.source_table='prospects' AND l.legacy_id=p.id WHERE l.legacy_id IS NULL;
 SELECT count(*) INTO missing_messages FROM public.messages m LEFT JOIN public.ld_legacy_links l ON l.source_table='messages' AND l.legacy_id=m.id WHERE l.legacy_id IS NULL;
 SELECT count(*) INTO restored_deleted FROM public.ld_message_records r JOIN public.messages m ON m.id=r.legacy_message_id WHERE m.status='deleted';
 SELECT count(*) INTO accidental_status FROM public.ld_message_records r JOIN public.messages m ON m.id=r.legacy_message_id
    WHERE (m.status='sent' AND r.status<>'sent') OR (m.status='ready' AND r.status<>'needs_review');
 IF p_count<>migrated_leads OR missing_leads<>0 THEN RAISE EXCEPTION 'Lead backfill incomplete: % vs %; missing %',p_count,migrated_leads,missing_leads; END IF;
 IF m_count<>migrated_messages OR missing_messages<>0 THEN RAISE EXCEPTION 'Message backfill incomplete: % vs %; missing links %',m_count,migrated_messages,missing_messages; END IF;
 IF restored_deleted<>0 THEN RAISE EXCEPTION 'Deleted messages were restored: %',restored_deleted; END IF;
 IF accidental_status<>0 THEN RAISE EXCEPTION 'Legacy send statuses changed: %',accidental_status; END IF;
 IF tombstones<>(SELECT count(*) FROM public.messages WHERE status='deleted') THEN RAISE EXCEPTION 'Missing tombstones for deleted records'; END IF;
 IF (SELECT count(*) FROM public.ld_service_workspaces) < (SELECT count(*) FROM public.teams)*6 THEN RAISE EXCEPTION 'Missing service workspaces'; END IF;
END $audit$;
