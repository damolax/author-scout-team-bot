"""Phase 8 conservative, reversible import rollback with immutable audit.

Rollback is a user-confirmed, atomic transaction. It only deletes untouched
draft-only objects provably created by the selected batch. It preserves all
opt-outs, externally referenced leads, other-service opportunities, sent/replied
messages, edited conversations, and shared contacts. No mail is ever sent.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import time
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

UNDO_TTL=15*60

def undo_enabled():
    return os.getenv("LETTERDESK_IMPORT_UNDO_ENABLED","false").lower() in ("true","1","yes")

def secret():
    val=os.getenv("LETTERDESK_IMPORT_SIGNING_SECRET") or os.getenv("APP_SECRET") or ""
    if len(val)<32:raise HTTPException(503,"Import signing key is not configured")
    return val.encode()

def token_for(team,service,batch,signature,ts=None):
    when=int(time.time()) if ts is None else int(ts)
    input_value=f"import-undo:{team}:{service}:{batch}:{signature}:{when}".encode()
    mac=hmac.new(secret(),input_value,"sha256").hexdigest()
    return f"{when}.{mac}"

def verify_token(token,team,service,batch,signature):
    try:
        when_s,digest=token.split(".",1)
        when=int(when_s)
        if when>time.time()+60 or time.time()-when>UNDO_TTL:
            raise ValueError()
    except (ValueError,AttributeError):
        raise HTTPException(400,"Undo review expired. Open the preview again.")
    if not hmac.compare_digest(token,token_for(team,service,batch,signature,when)):
        raise HTTPException(409,"Import changed since preview. Review before confirming.")

def get_batch(db,team,service,batch_id,locked=False):
    sql="""SELECT b.id,b.filename,b.status,b.file_sha256,b.rows_total,
        b.rows_imported,b.owner_team_id,b.rolled_back_at
      FROM public.ld_import_batches b
      JOIN public.ld_service_workspaces w ON w.id=b.workspace_id
      WHERE b.id=:id AND w.team_id=:team AND w.service_key=:service
        AND b.owner_team_id=:team AND b.source_service=:service"""
    if locked:sql+=" FOR UPDATE OF b"
    row=db.execute(text(sql),{"id":batch_id,"team":team,"service":service}).mappings().first()
    if not row:raise HTTPException(404,"This import does not belong to this service")
    return row

def inspect(db,batch):
    bid=str(batch["id"])
    messages=db.execute(text("""SELECT m.id::text AS id,m.status,CAST(m.conversation_id AS TEXT) AS conversation_id
        FROM public.ld_message_records m
        WHERE m.raw_metadata->>'import_batch'=:batch
        ORDER BY m.created_at"""),{"batch":bid}).mappings().all()
    mids=[str(m["id"]) for m in messages]
    cids=list({str(m["conversation_id"]) for m in messages})
    queued=int(db.execute(text("""SELECT count(*) FROM public.ld_campaign_queue
        WHERE message_record_id=ANY(CAST(:ids AS uuid[]))"""),{"ids":mids}).scalar_one()) if mids else 0
    replies=int(db.execute(text("""SELECT count(*) FROM public.ld_reply_inbox
        WHERE conversation_id=ANY(CAST(:ids AS uuid[]))"""),{"ids":cids}).scalar_one()) if cids else 0
    unsafe_status=sum(m["status"]!="needs_review" for m in messages)
    conversations=db.execute(text("""SELECT CAST(c.id AS TEXT) AS id,c.status,c.message_count,c.legacy_message_id
       FROM public.ld_conversations c
       WHERE c.id=ANY(CAST(:ids AS uuid[]))"""),{"ids":cids}).mappings().all() if cids else []
    changed=sum(c["status"]!="draft" or c["message_count"]!=0 or c["legacy_message_id"] is not None
                for c in conversations)
    # Only opportunities created by the *current* tagged batch are deletable.
    opportunities=[str(x) for x in db.execute(text("""SELECT CAST(o.id AS TEXT)
       FROM public.ld_opportunities o
       WHERE o.service_details->>'_letterdesk_import_batch'=:batch"""),
       {"batch":bid}).scalars().all()]
    leads=[str(x) for x in db.execute(text("""SELECT CAST(l.id AS TEXT)
       FROM public.ld_leads l WHERE l.details->>'import_batch'=:batch"""),
       {"batch":bid}).scalars().all()]
    # A linked lead or a legacy import record must never be deleted by rollback.
    return {"draft_messages":len(messages),"queued_messages":queued,
            "replied_conversations":replies,"changed_messages":unsafe_status,
            "changed_conversations":changed,
            "owned_opportunities":len(opportunities),"owned_leads":len(leads),
            "eligible":queued==0 and replies==0 and unsafe_status==0 and changed==0,
            "note":"Import-specific unsent drafts will be removed; genuinely shared contacts and all suppression records remain intact."}

def preview(engine,team,service,batch_id):
    with engine.connect() as db:
        batch=get_batch(db,team,service,batch_id)
        if batch["status"]!="completed" or batch["rolled_back_at"] is not None:
            raise HTTPException(409,"Only a completed, not-yet-undone import can be reversed")
        summary=inspect(db,batch)
        fingerprint=hashlib.sha256(json.dumps(summary,sort_keys=True).encode()).hexdigest()
        return {"ok":True,"batch_id":str(batch["id"]),"filename":batch["filename"],
                "summary":summary,"confirmation_token":token_for(team,service,batch_id,fingerprint),
                "write_enabled":undo_enabled()}

def execute(engine,team,service,batch_id,account,expected_filename,confirmation_token):
    if not undo_enabled():raise HTTPException(403,"Import undo remains disabled in this preview")
    try:
      with engine.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(:team)"),{"team":int(team)})
        batch=get_batch(db,team,service,batch_id,locked=True)
        if batch["status"]!="completed" or batch["rolled_back_at"] is not None:
            raise HTTPException(409,"Import already reversed or not completed")
        if expected_filename!=batch["filename"]:
            raise HTTPException(400,"Type the exact filename shown in the preview")
        summary=inspect(db,batch)
        fingerprint=hashlib.sha256(json.dumps(summary,sort_keys=True).encode()).hexdigest()
        verify_token(confirmation_token,team,service,batch_id,fingerprint)
        if not summary["eligible"]:
            raise HTTPException(409,"Import now has sent/queued/replied/edited messages. Automatic reversal is unsafe; preserve records and request manual reconciliation.")
        params={"batch":str(batch_id)}
        # Erase batch-created unsent message drafts; never delete sent or
        # externally queued messages. Relational constraints abort on races.
        db.execute(text("""UPDATE public.ld_import_rows
             SET message_record_id=NULL
             WHERE batch_id=CAST(:batch AS uuid)"""),params)
        removed_messages=db.execute(text("""DELETE FROM public.ld_message_records
             WHERE raw_metadata->>'import_batch'=:batch AND status='needs_review'
             RETURNING id"""),params).scalars().all()
        # A message's conversation could have other manually written drafts;
        # only remove if no messages or replies, and it remains untouched.
        db.execute(text("""DELETE FROM public.ld_conversations c
            WHERE c.status='draft' AND c.message_count=0 AND c.legacy_message_id IS NULL
              AND NOT EXISTS(SELECT 1 FROM public.ld_message_records m WHERE m.conversation_id=c.id)
              AND NOT EXISTS(SELECT 1 FROM public.ld_reply_inbox r WHERE r.conversation_id=c.id)
              AND EXISTS(SELECT 1 FROM public.ld_opportunities o
                 WHERE o.id=c.opportunity_id AND o.service_details->>'_letterdesk_import_batch'=:batch)"""),params)

        db.execute(text("""UPDATE public.ld_import_rows ir
          SET opportunity_id=NULL
          WHERE ir.batch_id=CAST(:batch AS uuid) AND ir.opportunity_id IN (
            SELECT o.id FROM public.ld_opportunities o
            WHERE o.service_details->>'_letterdesk_import_batch'=:batch
              AND NOT EXISTS(SELECT 1 FROM public.ld_conversations c WHERE c.opportunity_id=o.id)
              AND NOT EXISTS(SELECT 1 FROM public.ld_evidence e WHERE e.opportunity_id=o.id)
              AND NOT EXISTS(SELECT 1 FROM public.ld_discovery_results d WHERE d.opportunity_id=o.id)
          )"""),params)
        removed_ops=db.execute(text("""DELETE FROM public.ld_opportunities o
          WHERE o.service_details->>'_letterdesk_import_batch'=:batch
          AND NOT EXISTS(SELECT 1 FROM public.ld_conversations c WHERE c.opportunity_id=o.id)
          AND NOT EXISTS(SELECT 1 FROM public.ld_evidence e WHERE e.opportunity_id=o.id)
          AND NOT EXISTS(SELECT 1 FROM public.ld_discovery_results d WHERE d.opportunity_id=o.id)
          AND NOT EXISTS(SELECT 1 FROM public.ld_import_rows ir WHERE ir.opportunity_id=o.id)
          RETURNING id"""),params).scalars().all()

        db.execute(text("""UPDATE public.ld_import_rows ir
           SET lead_id=NULL
           WHERE ir.batch_id=CAST(:batch AS uuid) AND ir.lead_id IN (
             SELECT l.id FROM public.ld_leads l
             WHERE l.details->>'import_batch'=:batch
              AND NOT EXISTS(SELECT 1 FROM public.ld_opportunities o WHERE o.lead_id=l.id)
              AND NOT EXISTS(SELECT 1 FROM public.ld_evidence e WHERE e.lead_id=l.id)
              AND NOT EXISTS(SELECT 1 FROM public.ld_discovery_results d WHERE d.lead_id=l.id)
          )"""),params)
        removed_leads=db.execute(text("""DELETE FROM public.ld_leads l
           WHERE l.details->>'import_batch'=:batch
             AND NOT EXISTS(SELECT 1 FROM public.ld_opportunities o WHERE o.lead_id=l.id)
             AND NOT EXISTS(SELECT 1 FROM public.ld_evidence e WHERE e.lead_id=l.id)
             AND NOT EXISTS(SELECT 1 FROM public.ld_discovery_results d WHERE d.lead_id=l.id)
             AND NOT EXISTS(SELECT 1 FROM public.ld_import_rows ir WHERE ir.lead_id=l.id)
           RETURNING id"""),params).scalars().all()
        # Audit rows remain, but free-text messages/branch contents are redacted.
        db.execute(text("""UPDATE public.ld_import_rows
            SET branch_templates='{}'::jsonb,
                reason=LEFT(COALESCE(reason,'')||' [Import undone]',800)
            WHERE batch_id=CAST(:batch AS uuid)"""),params)
        result={"removed_drafts":len(removed_messages),
                "removed_opportunities":len(removed_ops),
                "removed_leads":len(removed_leads),
                "retained_shared_or_researched_leads":summary["owned_leads"]-len(removed_leads),
                "suppression_records_preserved":True}
        db.execute(text("""UPDATE public.ld_import_batches
          SET status='rolled_back',rolled_back_at=now(),undo_account_id=:account,
              undo_summary=CAST(:summary AS jsonb)
          WHERE id=CAST(:batch AS uuid)"""),{
             "account":account,"batch":str(batch_id),"summary":json.dumps(result)})
        return {"ok":True,"batch_id":str(batch_id),"summary":result,
                "note":"Only unused imported drafts/leads were removed. Opt-outs, shared records and audit retained."}
    except IntegrityError:
        raise HTTPException(409,"Other records now reference the import. No changes were made; review the dependencies.")
