"""Phase 7 persistent reply intake, safety holds, review and immutable flow binding."""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime,timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from letterdesk_gmail_api import sender_crypto
from letterdesk_reply_rules import classify_reply,safe_draft,fallback_flow,canonical_address,OUTCOMES
from letterdesk_flow_engine import validate_flow

MAX_REPLY_LENGTH=12000
TERMINAL={"opt_out","negative","bounce"}
SINGLE_REPLY_GLOBAL_STATUS=("approved","pending_review")

def require_write():
    if os.getenv("LETTERDESK_REPLY_WRITE_ENABLED","false").lower() not in ("true","1","yes"):
        raise HTTPException(403,"Reply changes are disabled in this protected preview")

def protect_body(body):
    if not isinstance(body,str) or not body.strip() or len(body)>MAX_REPLY_LENGTH:
        raise HTTPException(400,"Reply must contain 1–12,000 characters")
    return sender_crypto().encrypt(body.encode("utf-8")).decode()

def reveal_body(encrypted):
    try:return sender_crypto().decrypt(encrypted.encode()).decode("utf-8")
    except Exception:return "[Reply content unavailable: encryption key changed]"

def get_conversation(db,team,workspace,conversation_id,lock=False):
    return db.execute(text("""SELECT c.id,c.status,c.message_count,c.no_reply_followups,
        o.workspace_id,l.id AS lead_id,l.email AS lead_email,l.name AS lead_name,
        w.service_key
        FROM public.ld_conversations c
        JOIN public.ld_opportunities o ON o.id=c.opportunity_id
        JOIN public.ld_leads l ON l.id=o.lead_id
        JOIN public.ld_service_workspaces w ON w.id=o.workspace_id
        WHERE c.id=:id AND w.id=CAST(:ws AS uuid)
          AND w.team_id=:team AND l.team_id=:team """+(" FOR UPDATE OF c" if lock else "")),
        {"id":conversation_id,"ws":workspace,"team":team}).mappings().first()

def conversation_flow(db,row):
    binding=db.execute(text("""SELECT snapshot,current_code,flow_design_id
           FROM public.ld_conversation_flow_bindings
           WHERE conversation_id=:id"""),{"id":row["id"]}).mappings().first()
    if binding:
        doc=binding["snapshot"]
        if isinstance(doc,str):doc=json.loads(doc)
        return doc,binding["current_code"]
    return fallback_flow(row["service_key"]),"Message01"

def _recipient_proof(db,row,sender_email,queue_id=None):
    # Exact match against the conversation's address and record, no fuzzy joins.
    candidates=set()
    if row["lead_email"]:candidates.add(str(row["lead_email"]).lower().strip())
    sent=db.execute(text("""SELECT DISTINCT lower(recipient_email)
        FROM public.ld_message_records
        WHERE conversation_id=:conversation AND recipient_email IS NOT NULL"""),
        {"conversation":row["id"]}).scalars().all()
    candidates.update(str(s).strip().lower() for s in sent if s)
    if sender_email not in candidates:
        raise HTTPException(409,"Reply sender does not match the conversation contact")
    return True

def ingest_reply(engine,team,workspace,conversation_id,sender,body,
                 *,source="manual",provider_message_id=None,gmail_connection_id=None,
                 campaign_queue_id=None,received_at=None,manual_key=None,is_delivery_report=False):
    require_write()
    if source not in ("manual","gmail_thread"):raise HTTPException(400,"Unknown reply source")
    address=canonical_address(sender)
    if not address:raise HTTPException(400,"Valid sender email is required")
    encrypted=protect_body(body)
    when=received_at or datetime.now(timezone.utc)
    if not isinstance(when,datetime) or when.tzinfo is None:
        raise HTTPException(400,"A timezone-aware receive time is required")
    if when>datetime.now(timezone.utc).replace(microsecond=0):
        # Allow small provider clock drift rather than trusting arbitrary future timestamps.
        if (when-datetime.now(timezone.utc)).total_seconds()>300:
            raise HTTPException(400,"Future-dated reply cannot be imported")
    guess=classify_reply(body,sender,is_delivery_report=is_delivery_report)
    try:
      with engine.begin() as db:
        row=get_conversation(db,team,workspace,conversation_id,lock=True)
        if not row:raise HTTPException(404,"Conversation was not found in this service")
        _recipient_proof(db,row,address)
        if row["status"] in ("lost","stopped"):
            raise HTTPException(409,"Conversation was already stopped")
        if source=="gmail_thread":
            if not provider_message_id or not gmail_connection_id or not campaign_queue_id:
                raise HTTPException(400,"Gmail replies require verified provider message and queue link")
            verified=db.execute(text("""SELECT 1 FROM public.ld_campaign_queue q
                JOIN public.ld_campaigns cam ON cam.id=q.campaign_id
                JOIN public.ld_service_workspaces w ON w.id=cam.workspace_id
                JOIN public.ld_gmail_sender_identities s ON s.id=q.sender_identity_id
                JOIN public.ld_gmail_connections c ON c.id=s.connection_id
                JOIN public.ld_message_records m ON m.id=q.message_record_id
                WHERE q.id=:qid AND c.id=:conn AND w.id=CAST(:ws AS uuid)
                    AND w.team_id=:team AND m.conversation_id=:conversation
                    AND q.status='sent' AND q.provider_thread_id IS NOT NULL
                    AND lower(q.recipient_email)=:recipient"""),{
                    "qid":campaign_queue_id,"conn":gmail_connection_id,
                    "ws":workspace,"team":team,"conversation":conversation_id,
                    "recipient":address}).scalar_one_or_none()
            if not verified:raise HTTPException(403,"Gmail reply is not linked to an authorized sent thread")
        else:
            if not manual_key or len(manual_key)>90 or len(manual_key)<20:
                raise HTTPException(400,"Manual reply needs a stable unique idempotency key")
        doc,current_code=conversation_flow(db,row)
        proposal=safe_draft(doc,current_code,guess["outcome"],
                          row["message_count"],row["no_reply_followups"])
        # Auto-stop only high-confidence unsubscription/refusal. Other replies
        # require human review but block additional queued sends immediately.
        stop=guess["confidence"]=="high" and guess["outcome"] in TERMINAL
        result=db.execute(text("""INSERT INTO public.ld_reply_inbox
            (team_id,workspace_id,conversation_id,campaign_queue_id,gmail_connection_id,
             provider_message_id,source,manual_dedupe_key,sender_email,received_at,
             body_encrypted,suggested_outcome,outcome_confidence,status,
             flow_message_code,proposed_next_code,proposed_draft_encrypted)
             VALUES(:team,CAST(:ws AS uuid),:conversation,:qid,:conn,:provider,
                    :source,:manual,:sender,:received,:body,:outcome,:confidence,
                    :status,:current,:next,:draft)
             ON CONFLICT DO NOTHING RETURNING id::text"""),{
            "team":team,"ws":workspace,"conversation":conversation_id,
            "qid":campaign_queue_id,"conn":gmail_connection_id,
            "provider":provider_message_id,"source":source,"manual":manual_key,
            "sender":address,"received":when,"body":encrypted,
            "outcome":guess["outcome"],"confidence":guess["confidence"],
            "status":"stopped" if stop else "pending_review",
            "current":current_code,"next":proposal.get("nextCode"),
            "draft":sender_crypto().encrypt(json.dumps(proposal.get("draft")).encode()).decode()
                    if proposal.get("draft") else None}).scalar_one_or_none()
        if not result:
            return {"created":False,"reason":"duplicate","outcome":guess["outcome"]}
        db.execute(text("""UPDATE public.ld_campaign_queue q
             SET status='held',failure_code='reply_received',updated_at=now()
             FROM public.ld_campaigns cam
             JOIN public.ld_service_workspaces w ON w.id=cam.workspace_id
             WHERE q.campaign_id=cam.id AND w.team_id=:team
               AND lower(q.recipient_email)=:email
               AND q.status IN ('pending_review','approved')"""),
             {"team":team,"email":address})
        if stop:
            db.execute(text("""INSERT INTO public.ld_suppressions
                (team_id,normalized_email,reason,source)
                VALUES(:team,:email,:reason,'inbound_reply')
                ON CONFLICT(team_id,normalized_email) DO NOTHING"""),{
                "team":team,"email":address,"reason":guess["outcome"]})
        db.execute(text("""UPDATE public.ld_conversations
              SET status=:status,reply_classification=:outcome,
                  next_action_at=NULL,updated_at=now()
              WHERE id=:id"""),{
              "status":"stopped" if stop else "needs_review",
              "outcome":guess["outcome"],"id":conversation_id})
        db.execute(text("""UPDATE public.ld_message_records SET status='replied'
              WHERE conversation_id=:conversation AND status='sent'"""),
              {"conversation":conversation_id})
        return {"created":True,"reply_id":result,"outcome":guess["outcome"],
                "confidence":guess["confidence"],"status":"stopped" if stop else "pending_review",
                "reason":guess["reason"]}
    except IntegrityError:
        raise HTTPException(409,"Reply already exists or could not be stored")

def review_reply(engine,team,workspace,reply_id,reviewer,outcome,notes=""):
    require_write()
    if outcome not in OUTCOMES:raise HTTPException(400,"Select a supported response outcome")
    with engine.begin() as db:
        reply=db.execute(text("""SELECT r.*
             FROM public.ld_reply_inbox r
             WHERE r.id=:id AND r.team_id=:team
               AND r.workspace_id=CAST(:ws AS uuid) FOR UPDATE"""),
               {"id":reply_id,"team":team,"ws":workspace}).mappings().first()
        if not reply:raise HTTPException(404,"Reply does not belong to this workspace")
        if reply["status"]!="pending_review":
            raise HTTPException(409,"This reply has already been reviewed or stopped")
        conversation=get_conversation(db,team,workspace,reply["conversation_id"],lock=True)
        if not conversation:raise HTTPException(404,"Conversation missing")
        doc,current=conversation_flow(db,conversation)
        proposal=safe_draft(doc,reply["flow_message_code"] or current,outcome,
                            conversation["message_count"],conversation["no_reply_followups"])
        stop=outcome in TERMINAL
        if stop:
            db.execute(text("""INSERT INTO public.ld_suppressions
                 (team_id,normalized_email,reason,source)
                 VALUES(:team,:email,:reason,'reviewed_reply')
                 ON CONFLICT(team_id,normalized_email) DO NOTHING"""),{
                     "team":team,"email":reply["sender_email"],"reason":outcome})
        # A future reply from the same person must be manually reviewed before
        # any other phase activates a new message. Never un-suppress a contact.
        new_status="stopped" if stop else "needs_review"
        db.execute(text("""UPDATE public.ld_conversations
            SET status=:status,reply_classification=:outcome,next_action_at=NULL,
                updated_at=now() WHERE id=:id"""),{
            "status":new_status,"outcome":outcome,"id":reply["conversation_id"]})
        draft=proposal.get("draft")
        # Never enqueue or send a proposed branch; keep it encrypted within the
        # inbox record for the human to refine. No new ld_message_records here.
        db.execute(text("""UPDATE public.ld_reply_inbox
           SET final_outcome=:outcome,status=:status,reviewer_account_id=:account,
               reviewed_at=now(),updated_at=now(),
               proposed_next_code=:next,proposed_draft_encrypted=:draft
           WHERE id=:id"""),{
            "outcome":outcome,"status":"stopped" if stop else "reviewed",
            "account":reviewer,"next":proposal.get("nextCode"),
            "draft":sender_crypto().encrypt(json.dumps(draft).encode()).decode() if draft else None,
            "id":reply_id})
        return {"ok":True,"status":"stopped" if stop else "reviewed",
                "outcome":outcome,"action":proposal.get("action"),
                "suggested_next_code":proposal.get("nextCode"),
                "draft_for_human_review":draft,"messages_sent":0}

def assign_flow(engine,team,workspace,conversation_id,flow_id,account):
    require_write()
    with engine.begin() as db:
        row=get_conversation(db,team,workspace,conversation_id,lock=True)
        if not row:raise HTTPException(404,"Conversation missing")
        if row["status"] in ("stopped","lost"):raise HTTPException(409,"Cannot assign a stopped conversation")
        if db.execute(text("""SELECT 1 FROM public.ld_reply_inbox
            WHERE conversation_id=:conversation LIMIT 1"""),{
            "conversation":conversation_id}).scalar_one_or_none():
            raise HTTPException(409,"Conversation has recorded replies; cannot silently change its flow")
        if flow_id:
            flow=db.execute(text("""SELECT f.id,f.revision,f.document
                FROM public.ld_flow_designs f
                WHERE f.id=:flow AND f.workspace_id=CAST(:ws AS uuid)
                  AND f.status='draft'"""),{
                    "flow":flow_id,"ws":workspace}).mappings().first()
            if not flow:raise HTTPException(404,"Flow design missing")
            doc=flow["document"]
            if validate_flow(doc,row["service_key"]):raise HTTPException(400,"Flow design is invalid")
            revision=flow["revision"]
        else:
            doc=fallback_flow(row["service_key"]);revision=1
        db.execute(text("""INSERT INTO public.ld_conversation_flow_bindings(
            conversation_id,flow_design_id,flow_revision,service_key,snapshot,
            current_code,assigned_account_id)
            VALUES(:conversation,:flow,:revision,:service,CAST(:snapshot AS jsonb),
                   'Message01',:account)
            ON CONFLICT(conversation_id) DO UPDATE SET
             flow_design_id=EXCLUDED.flow_design_id,flow_revision=EXCLUDED.flow_revision,
             snapshot=EXCLUDED.snapshot,current_code='Message01',
             assigned_account_id=EXCLUDED.assigned_account_id,updated_at=now()"""),{
             "conversation":conversation_id,"flow":flow_id,"revision":revision,
             "service":row["service_key"],"snapshot":json.dumps(doc),"account":account})
        return {"ok":True,"flow_revision":revision,
                "flow_name":"Starter" if not flow_id else "Saved design",
                "note":"Snapshot assigned. No reply or email sent."}
