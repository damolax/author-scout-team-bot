"""Phase 6 guarded Gmail delivery engine — OFF until a separate audited release.

No automatic send is started by importing, connecting Gmail, saving a flow,
approving a queue item, or deploying staging. This module is inert unless a
future production worker explicitly invokes it, with all release gates present.

Safety policy: idempotent DB claims, final suppression check, per-team and
per-sender budgets, daytime windows, recipient suppression, verified alias,
no automatic retries of uncertain HTTP results.
"""
from __future__ import annotations
import asyncio
import base64
import os
from datetime import datetime,timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo
from uuid import UUID

import httpx
from sqlalchemy import text

from letterdesk_gmail_api import sender_crypto,BASIC_SCOPES

GMAIL_TOKEN_URL="https://oauth2.googleapis.com/token"
GMAIL_SEND_URL="https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
MAX_TEAM_SENDS_PER_DAY=100
MAX_REPLIES_UNPROCESSED=0  # Fail closed until Phase 7 proves reply/suppression synchronization.

def delivery_release_ready():
    """Independent three-key release gate; explicitly denied in isolated staging."""
    return (
        os.getenv("LETTERDESK_STAGING_ISOLATED","false").lower() not in ("true","1","yes")
        and os.getenv("LETTERDESK_GMAIL_SEND_ENABLED","false").lower() in ("true","1","yes")
        and os.getenv("LETTERDESK_REPLY_SAFETY_READY","false").lower() in ("true","1","yes")
        and os.getenv("LETTERDESK_DELIVERY_OPERATOR_APPROVED","false").lower() in ("true","1","yes")
    )

def sanitize_email_message(sender,recipient,subject,body):
    """Strict header sanitization and unchanged plain-text content."""
    if any("\n" in str(v) or "\r" in str(v) for v in (sender,recipient,subject)):
        raise ValueError("Mail headers must not contain line breaks")
    if not sender or not recipient or not subject or not isinstance(body,str) or not body.strip():
        raise ValueError("Incomplete email draft")
    if len(str(subject))>400 or len(body)>50_000:
        raise ValueError("Mail draft exceeds safe bounds")
    m=EmailMessage()
    m["From"]=sender
    m["To"]=recipient
    m["Subject"]=subject
    m.set_content(body)
    return base64.urlsafe_b64encode(m.as_bytes()).decode().rstrip("=")

async def gmail_send_one(encrypted_refresh, sender,recipient,subject,body):
    """At most one Gmail submission. Callers NEVER auto-retry network ambiguity."""
    if not delivery_release_ready():
        raise RuntimeError("Gmail delivery is disabled until all production release gates pass")
    token_refresh=sender_crypto().decrypt(encrypted_refresh.encode()).decode()
    client_id=os.getenv("GOOGLE_CLIENT_ID") or ""
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET") or ""
    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth server credentials are missing")
    raw=sanitize_email_message(sender,recipient,subject,body)
    async with httpx.AsyncClient(timeout=28,trust_env=True) as client:
        token=await client.post(GMAIL_TOKEN_URL,data={
            "client_id":client_id,"client_secret":client_secret,
            "refresh_token":token_refresh,"grant_type":"refresh_token"})
        if token.status_code!=200:raise RuntimeError("Google refresh token is invalid or has been revoked")
        access=token.json().get("access_token") or ""
        if not access:raise RuntimeError("Google did not return an access token")
        sent=await client.post(GMAIL_SEND_URL,headers={"Authorization":"Bearer "+access},
                               json={"raw":raw})
        if sent.status_code!=200:
            raise RuntimeError("Gmail rejected the message: HTTP "+str(sent.status_code))
        mid=sent.json().get("id") or ""
        if not mid:raise RuntimeError("Gmail response lacked message ID: delivery uncertain")
        return str(mid)

def _hold(db,row,reason):
    db.execute(text("""UPDATE public.ld_campaign_queue SET status='held',failure_code=:reason,
                updated_at=now() WHERE id=:id AND status='approved'"""),
               {"reason":reason,"id":row["id"]})

def claim_next(engine):
    if not delivery_release_ready():return None
    # Select and claim no more than one message per worker pass.
    with engine.begin() as db:
        candidates=db.execute(text("""SELECT q.id,q.message_record_id,q.sender_identity_id,
             q.recipient_email,q.permission_basis,q.permission_evidence,
             c.id AS campaign_id,c.max_daily,c.min_interval_seconds,
             c.send_window_start,c.send_window_end,c.timezone_name,
             w.team_id,s.email AS sender_email,s.enabled AS sender_enabled,
             s.verification_status AS verified,
             conn.status AS connection_status,conn.refresh_token_encrypted,
             conn.scopes,m.subject,m.body,m.status AS message_status,
             convo.status AS conversation_status,convo.id AS conversation_id,
             l.id AS lead_id,l.email AS lead_email
             FROM public.ld_campaign_queue q
             JOIN public.ld_campaigns c ON c.id=q.campaign_id
             JOIN public.ld_service_workspaces w ON w.id=c.workspace_id
             JOIN public.ld_gmail_sender_identities s ON s.id=q.sender_identity_id
             JOIN public.ld_gmail_connections conn ON conn.id=s.connection_id
             JOIN public.ld_message_records m ON m.id=q.message_record_id
             JOIN public.ld_conversations convo ON convo.id=m.conversation_id
             JOIN public.ld_opportunities o ON o.id=convo.opportunity_id AND o.workspace_id=w.id
             JOIN public.ld_leads l ON l.id=o.lead_id AND l.team_id=w.team_id
             WHERE q.status='approved' AND c.status='active'
               AND (q.scheduled_at IS NULL OR q.scheduled_at<=now())
             ORDER BY q.scheduled_at NULLS FIRST,q.created_at ASC
             LIMIT 10 FOR UPDATE OF q SKIP LOCKED""")).mappings().all()
        for r in candidates:
            row=dict(r)
            if (not row["sender_enabled"] or row["verified"]!="verified"
                or row["connection_status"]!="connected"
                or "https://www.googleapis.com/auth/gmail.send" not in (row["scopes"] or [])):
                _hold(db,row,"sender_not_verified")
                continue
            if (row["message_status"]!="needs_review" or row["conversation_status"] in
                    ("lost","won","stopped","qualified") or not row["body"]):
                _hold(db,row,"message_or_conversation_not_sendable")
                continue
            if (row["lead_email"] and row["lead_email"].lower()!=row["recipient_email"].lower()):
                _hold(db,row,"recipient_changed")
                continue
            if db.execute(text("""SELECT 1 FROM public.ld_suppressions
                WHERE team_id=:team AND normalized_email=:email LIMIT 1"""),{
                   "team":row["team_id"],"email":row["recipient_email"]}).scalar_one_or_none():
                _hold(db,row,"recipient_suppressed")
                continue
            try:
                here=datetime.now(ZoneInfo(row["timezone_name"]))
            except Exception:
                _hold(db,row,"invalid_timezone")
                continue
            if not row["send_window_start"]<=here.hour<row["send_window_end"] or here.weekday()>=5:
                continue
            health=db.execute(text("""SELECT last_sent_at,sent_today,sent_day,paused_until
                FROM public.ld_campaign_sender_health WHERE sender_identity_id=:id FOR UPDATE"""),
                {"id":row["sender_identity_id"]}).mappings().first()
            if health:
                if health["paused_until"] and health["paused_until"]>datetime.now(timezone.utc):continue
                if health["last_sent_at"] and (datetime.now(timezone.utc)-health["last_sent_at"]).total_seconds()<row["min_interval_seconds"]:continue
                if health["sent_day"]==here.date() and health["sent_today"]>=min(30,row["max_daily"]):continue
            total=db.execute(text("""SELECT count(*) FROM public.ld_campaign_queue q
                JOIN public.ld_campaigns c ON q.campaign_id=c.id
                JOIN public.ld_service_workspaces w ON w.id=c.workspace_id
                WHERE w.team_id=:team AND (
                    (q.status='sent' AND q.sent_at>=CURRENT_DATE) OR
                    (q.status IN ('sending','uncertain') AND q.claimed_at>=CURRENT_DATE))
                    """),{
                    "team":row["team_id"]}).scalar_one()
            if total>=MAX_TEAM_SENDS_PER_DAY:continue
            # Mark irreversible claim before network request. Never claim 'sending'
            # again after worker crash; stale claims require manual reconciliation.
            db.execute(text("""UPDATE public.ld_campaign_queue
                SET status='sending',claimed_at=now(),updated_at=now()
                WHERE id=:id AND status='approved'"""),{"id":row["id"]})
            # Reserve today's capacity and cooldown before attempting delivery,
            # so parallel workers cannot bypass sender limits.
            db.execute(text("""INSERT INTO public.ld_campaign_sender_health
                (sender_identity_id,last_sent_at,sent_today,sent_day)
                VALUES(:sender,now(),1,CURRENT_DATE)
                ON CONFLICT(sender_identity_id) DO UPDATE SET
                  last_sent_at=now(),
                  sent_today=CASE WHEN public.ld_campaign_sender_health.sent_day=CURRENT_DATE
                    THEN public.ld_campaign_sender_health.sent_today+1 ELSE 1 END,
                  sent_day=CURRENT_DATE"""),{"sender":row["sender_identity_id"]})
            return row
    return None

async def deliver_one(engine):
    if not delivery_release_ready():return {"status":"disabled"}
    row=await asyncio.to_thread(claim_next,engine)
    if not row:return {"status":"idle"}
    mid=None;failure=None
    try:
        mid=await gmail_send_one(row["refresh_token_encrypted"],row["sender_email"],
                                 row["recipient_email"],row["subject"],row["body"])
    except (httpx.RequestError,httpx.TimeoutException):
        failure="network_ambiguous"
    except Exception:
        failure="provider_error_requires_review"
    with engine.begin() as db:
        if not mid:
            # Failed or uncertain attempt can never be auto-requeued.
            db.execute(text("""UPDATE public.ld_campaign_queue
                SET status='uncertain',failure_code=:error,updated_at=now()
                WHERE id=:id AND status='sending'"""),{"id":row["id"],"error":failure or "unknown"})
            db.execute(text("""UPDATE public.ld_campaigns
                SET status='paused',updated_at=now() WHERE id=:id AND status='active'"""),{
                    "id":row["campaign_id"]})
            return {"status":"uncertain"}
        db.execute(text("""UPDATE public.ld_campaign_queue
            SET status='sent',provider_message_id=:mid,sent_at=now(),updated_at=now()
            WHERE id=:id AND status='sending'"""),{"mid":mid,"id":row["id"]})
        db.execute(text("""UPDATE public.ld_message_records
             SET status='sent',sender_email=:sender,provider_message_id=:mid
             WHERE id=:message AND status='needs_review'"""),{
                 "sender":row["sender_email"],"mid":mid,"message":row["message_record_id"]})
        db.execute(text("""UPDATE public.ld_conversations
            SET status='awaiting_reply',message_count=message_count+1,updated_at=now()
            WHERE id=:id AND status NOT IN ('stopped','lost')"""),{
                "id":row["conversation_id"]})
    return {"status":"sent"}

def quarantine_stale_attempts(engine):
    with engine.begin() as db:
        affected=db.execute(text("""UPDATE public.ld_campaign_queue
            SET status='uncertain',failure_code='worker_interrupted',
                updated_at=now() WHERE status='sending'
            RETURNING campaign_id""")).scalars().all()
        if affected:
            db.execute(text("""UPDATE public.ld_campaigns
               SET status='paused',updated_at=now() WHERE id=ANY(:campaigns)"""),{
                   "campaigns":list(affected)})
    return len(affected)
