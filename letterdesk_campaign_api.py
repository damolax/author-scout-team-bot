"""Letter Desk Phase 6 campaign preparation and sender assignment.

The API intentionally does not expose any outbound-send endpoint.
Draft and queue operations are isolated to one team AND one service workspace.
Only Google-verified identities belonging to an active connection are eligible.
Suppression, consent/evidence, historical delivery and message review are required.
"""
from __future__ import annotations

import os
import re
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

SERVICE_KEYS=("author","automation","website-design","digital-planner","shopify","google-maps")
EMAIL_PATTERN=re.compile(r"^[^\s@<>;,]{1,80}@[^\s@<>;,]+\.[A-Za-z]{2,24}$")
PERMISSION_BASIS=("explicit_opt_in","existing_customer","documented_legitimate_interest")

def safe_email(value):
    address=str(value or "").lower().strip()
    if not EMAIL_PATTERN.fullmatch(address) or len(address)>254:
        raise HTTPException(400,"Recipient address is invalid")
    return address

def validate_delivery_policy(recipient,permission_basis,evidence,authenticated_email=None):
    address=safe_email(recipient)
    if permission_basis not in PERMISSION_BASIS:
        raise HTTPException(400,"Select a legitimate documented contact basis")
    clean=str(evidence or "").strip()
    if len(clean)<18 or len(clean)>1800:
        raise HTTPException(400,"Document why contacting this recipient is appropriate (18–1800 characters)")
    if not any(x in clean.lower() for x in ("consent","requested","customer","previous","existing","business","relevant","permission","relationship","opt")):
        # Evidence content isn't proof, but require a clear legal/biz context for review.
        raise HTTPException(400,"Explain the recipient relationship or relevance in permission evidence")
    return address,clean

def install_campaign_api(app:FastAPI,engine,authenticate):
    router=APIRouter(prefix="/api/v2/letterdesk",tags=["Campaign preparation"])

    def auth_workspace(request,service):
        ctx=authenticate(request)
        team=int(ctx.get("team_id") or 0)
        account=int(ctx.get("account_id") or 0)
        if team<1 or account<1:raise HTTPException(403,"Valid signed-in workspace required")
        if service not in SERVICE_KEYS:raise HTTPException(404,"Unknown service")
        with engine.connect() as db:
            ws=db.execute(text("""SELECT id::text FROM public.ld_service_workspaces
               WHERE team_id=:team AND service_key=:service AND is_active=true"""),
               {"team":team,"service":service}).scalar_one_or_none()
        if not ws:raise HTTPException(404,"Service workspace unavailable")
        return team,account,ws

    def writes_on():
        return os.getenv("LETTERDESK_CAMPAIGN_WRITE_ENABLED","false").lower() in ("true","1","yes")

    def allow_writes():
        if not writes_on():raise HTTPException(403,"Campaign changes are disabled in protected staging")

    def identity(db,identity_id,team,owner=None):
        conditions=" AND c.web_account_id=:owner" if owner is not None else ""
        p={"id":identity_id,"team":team}
        if owner is not None:p["owner"]=owner
        value=db.execute(text("""SELECT s.id::text AS id,s.email,s.enabled,
           s.verification_status,c.id::text AS connection_id,c.status AS connection_status,
           c.web_account_id
           FROM public.ld_gmail_sender_identities s
           JOIN public.ld_gmail_connections c ON c.id=s.connection_id
           WHERE s.id=:id AND c.team_id=:team """+conditions),p).mappings().first()
        return value

    @router.get("/services/{service}/senders")
    def senders(request:Request,service:str):
        team,account,ws=auth_workspace(request,service)
        with engine.connect() as db:
            rows=db.execute(text("""SELECT s.id::text AS id,s.email,s.enabled,
                s.verification_status,c.primary_email AS google_account,c.web_account_id,
                EXISTS(SELECT 1 FROM public.ld_campaigns camp
                       WHERE camp.sender_identity_id=s.id AND camp.workspace_id=CAST(:ws AS uuid))
                  AS previously_used
                FROM public.ld_gmail_sender_identities s
                JOIN public.ld_gmail_connections c ON c.id=s.connection_id
                WHERE c.team_id=:team AND c.status='connected'
                ORDER BY s.verification_status='verified' DESC,s.email LIMIT 350"""),
                {"ws":ws,"team":team}).mappings().all()
        return {"ok":True,"senders":[{**dict(r),"owner_is_you":int(r["web_account_id"])==account} for r in rows],
                "writes_enabled":writes_on()}

    @router.post("/services/{service}/senders/{identity_id}/enable")
    async def enable_sender(request:Request,service:str,identity_id:UUID):
        team,account,ws=auth_workspace(request,service)
        allow_writes()
        body=await request.json()
        status=bool(body.get("enabled")) if isinstance(body,dict) else False
        with engine.begin() as db:
            row=identity(db,identity_id,team,account)
            if not row:raise HTTPException(404,"You do not own this Gmail identity")
            if status and (row["verification_status"]!="verified" or row["connection_status"]!="connected"):
                raise HTTPException(400,"Only Google-verified active sender identities can be enabled")
            db.execute(text("""UPDATE public.ld_gmail_sender_identities
               SET enabled=:enable,updated_at=now() WHERE id=:id"""),{"enable":status,"id":identity_id})
        return {"ok":True,"enabled":status}

    @router.get("/services/{service}/campaigns")
    def list_campaigns(request:Request,service:str):
        team,account,ws=auth_workspace(request,service)
        with engine.connect() as db:
            rows=db.execute(text("""SELECT c.id::text,c.name,c.status,
                c.sender_identity_id::text AS sender_identity_id,
                s.email AS sender_email,c.max_daily,c.min_interval_seconds,
                c.send_window_start,c.send_window_end,c.timezone_name,c.created_at::text,c.owner_web_account_id,
                COUNT(q.id) AS queue_total,
                COUNT(q.id) FILTER(WHERE q.status='approved') AS queue_approved,
                COUNT(q.id) FILTER(WHERE q.status='sent') AS sent_total
                FROM public.ld_campaigns c
                LEFT JOIN public.ld_gmail_sender_identities s ON s.id=c.sender_identity_id
                LEFT JOIN public.ld_campaign_queue q ON q.campaign_id=c.id
                WHERE c.workspace_id=CAST(:ws AS uuid)
                GROUP BY c.id,s.email ORDER BY c.created_at DESC LIMIT 100"""),
                {"ws":ws}).mappings().all()
        return {"ok":True,"campaigns":[dict(r) for r in rows],
                "writes_enabled":writes_on(),
                "sending_enabled":False} # Controlled release requires Gmail verification and reply sync.

    @router.post("/services/{service}/campaigns")
    async def create_campaign(request:Request,service:str):
        team,account,ws=auth_workspace(request,service)
        allow_writes()
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(400,"Invalid campaign payload")
        name=" ".join(str(body.get("name") or "").split())[:100]
        if not name:raise HTTPException(400,"Enter a campaign name")
        try:sender_id=UUID(str(body.get("sender_identity_id")))
        except Exception:raise HTTPException(400,"Choose an authorized sender identity")
        daily=body.get("max_daily",10)
        if type(daily)!=int or not 1<=daily<=30:raise HTTPException(400,"Daily limit must be 1–30")
        interval=body.get("min_interval_seconds",180)
        if type(interval)!=int or not 120<=interval<=86400:
            raise HTTPException(400,"Minimum interval must be at least two minutes")
        start,end=body.get("send_window_start",9),body.get("send_window_end",17)
        if type(start)!=int or type(end)!=int or not 0<=start<end<=24:
            raise HTTPException(400,"Choose a valid local sending window")
        tz=str(body.get("timezone_name") or "UTC")
        try:ZoneInfo(tz)
        except (ZoneInfoNotFoundError,ValueError):raise HTTPException(400,"Unknown timezone")
        try:
            with engine.begin() as db:
                sender=identity(db,sender_id,team,account)
                if not sender or not sender["enabled"] or sender["verification_status"]!="verified" or sender["connection_status"]!="connected":
                    raise HTTPException(400,"Only enabled Google-verified Gmail identities can be assigned")
                row=db.execute(text("""INSERT INTO public.ld_campaigns
                   (workspace_id,name,status,sender_identity_id,max_daily,min_interval_seconds,
                   send_window_start,send_window_end,timezone_name,owner_web_account_id)
                   VALUES(CAST(:ws AS uuid),:name,'draft',:sender,:daily,:interval,:start,:end,:tz,:owner)
                   RETURNING id::text"""),{
                       "ws":ws,"name":name,"sender":sender_id,"daily":daily,"interval":interval,
                       "start":start,"end":end,"tz":tz,"owner":account}).scalar_one()
        except IntegrityError:raise HTTPException(409,"Campaign name already exists in this service")
        return {"ok":True,"id":row,"status":"draft",
                "note":"Draft campaign created. No messages can be sent by creating a campaign."}

    @router.get("/services/{service}/campaigns/{campaign_id}/queue")
    def list_queue(request:Request,service:str,campaign_id:UUID):
        team,account,ws=auth_workspace(request,service)
        with engine.connect() as db:
            valid=db.execute(text("""SELECT 1 FROM public.ld_campaigns
                  WHERE id=:campaign AND workspace_id=CAST(:ws AS uuid)"""),{
                    "campaign":campaign_id,"ws":ws}).scalar_one_or_none()
            if not valid:raise HTTPException(404,"Campaign not found")
            rows=db.execute(text("""SELECT q.id::text,q.message_record_id::text,q.recipient_email,
                 q.permission_basis,q.status,q.scheduled_at::text,q.approved_at::text,
                 q.sent_at::text,q.failure_code
                 FROM public.ld_campaign_queue q WHERE q.campaign_id=:id
                 ORDER BY q.created_at DESC LIMIT 200"""),{"id":campaign_id}).mappings().all()
        return {"ok":True,"queue":[dict(r) for r in rows]}

    @router.post("/services/{service}/campaigns/{campaign_id}/queue")
    async def stage_message(request:Request,service:str,campaign_id:UUID):
        team,account,ws=auth_workspace(request,service)
        allow_writes()
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(400,"Invalid queue entry")
        try:mid=UUID(str(body.get("message_record_id")))
        except Exception:raise HTTPException(400,"Choose a valid reviewed draft message")
        address,evidence=validate_delivery_policy(body.get("recipient_email"),body.get("permission_basis"),
                                                   body.get("permission_evidence"))
        with engine.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(:team)"),{"team":team})
            campaign=db.execute(text("""SELECT c.id,c.sender_identity_id,c.status
                 FROM public.ld_campaigns c WHERE c.id=:id AND c.workspace_id=CAST(:ws AS uuid)
                 AND c.status='draft' AND c.owner_web_account_id=:owner FOR UPDATE"""),{"id":campaign_id,"ws":ws,"owner":account}).mappings().first()
            if not campaign:raise HTTPException(404,"Draft campaign not found")
            sender=identity(db,campaign["sender_identity_id"],team)
            if not sender or not sender["enabled"] or sender["verification_status"]!="verified" or sender["connection_status"]!="connected":
                raise HTTPException(403,"Campaign sender is no longer verified or enabled")
            source=db.execute(text("""SELECT m.id,m.recipient_email,m.status,m.body,
                   l.id AS lead_id,l.email AS lead_email,c.status AS conversation_status
                 FROM public.ld_message_records m
                 JOIN public.ld_conversations c ON c.id=m.conversation_id
                 JOIN public.ld_opportunities o ON o.id=c.opportunity_id
                 JOIN public.ld_leads l ON l.id=o.lead_id AND l.team_id=:team
                 WHERE m.id=:mid AND o.workspace_id=CAST(:ws AS uuid)
                 FOR UPDATE OF m"""),{"mid":mid,"ws":ws,"team":team}).mappings().first()
            if not source or source["status"]!="needs_review" or not source["body"]:
                raise HTTPException(400,"Only unsent, complete drafts in this service can be prepared")
            if source["conversation_status"] in ("stopped","lost","won","qualified"):
                raise HTTPException(400,"The recipient conversation is stopped or finalized")
            if not source["recipient_email"] or address!=source["recipient_email"].lower().strip():
                raise HTTPException(400,"Recipient does not match the original message draft")
            if source["lead_email"] and address!=source["lead_email"].lower().strip():
                raise HTTPException(400,"Recipient does not match the prospect's contact email")
            if db.execute(text("""SELECT 1 FROM public.ld_suppressions
                 WHERE team_id=:team AND normalized_email=:email LIMIT 1"""),{
                     "team":team,"email":address}).scalar_one_or_none():
                raise HTTPException(409,"This contact is suppressed")
            if db.execute(text("""SELECT 1 FROM public.ld_campaign_queue q
                 JOIN public.ld_campaigns camp ON camp.id=q.campaign_id
                 JOIN public.ld_service_workspaces w ON w.id=camp.workspace_id
                 WHERE w.team_id=:team AND q.recipient_email=:email
                 AND q.status IN ('pending_review','approved','sending','sent','uncertain')
                 LIMIT 1"""),{"team":team,"email":address}).scalar_one_or_none():
                raise HTTPException(409,"This team already has a queued or sent campaign message to this contact")
            # Fresh draft, not approved or automatically ready; consent/basis reviewed by user.
            qid=db.execute(text("""INSERT INTO public.ld_campaign_queue(
                 campaign_id,message_record_id,sender_identity_id,recipient_email,
                 permission_basis,permission_evidence,approval_account_id,status)
                 VALUES(:campaign,:mid,:sender,:email,:basis,:evidence,:account,'pending_review')
                 RETURNING id::text"""),{
                    "campaign":campaign_id,"mid":mid,"sender":sender["id"],
                    "email":address,"basis":body["permission_basis"],"evidence":evidence,
                    "account":account}).scalar_one()
        return {"ok":True,"queue_id":qid,"status":"pending_review",
                "note":"Added to approval queue only. No email was sent."}

    @router.post("/services/{service}/campaigns/{campaign_id}/queue/{queue_id}/approve")
    async def approve_queue(request:Request,service:str,campaign_id:UUID,queue_id:UUID):
        team,account,ws=auth_workspace(request,service)
        allow_writes()
        with engine.begin() as db:
            row=db.execute(text("""UPDATE public.ld_campaign_queue q SET status='approved',
                 approved_at=now(),updated_at=now() FROM public.ld_campaigns c
                 WHERE q.id=:qid AND q.campaign_id=c.id AND c.id=:cid
                   AND c.workspace_id=CAST(:ws AS uuid) AND c.status='draft'
                   AND c.owner_web_account_id=:account AND q.status='pending_review' AND q.approval_account_id=:account
                   AND NOT EXISTS (SELECT 1 FROM public.ld_suppressions s
                       JOIN public.ld_service_workspaces w ON w.team_id=s.team_id
                       WHERE w.id=c.workspace_id AND s.normalized_email=q.recipient_email)
                 RETURNING q.id::text"""),{"qid":queue_id,"cid":campaign_id,"ws":ws,
                   "account":account}).scalar_one_or_none()
            if not row:raise HTTPException(409,"Approval was not permitted. Check review status, owner and suppression.")
        return {"ok":True,"status":"approved","note":"Approved for a future controlled release. Sending is not active."}

    @router.post("/services/{service}/campaigns/{campaign_id}/pause")
    def pause(request:Request,service:str,campaign_id:UUID):
        team,account,ws=auth_workspace(request,service)
        allow_writes()
        with engine.begin() as db:
            changed=db.execute(text("""UPDATE public.ld_campaigns SET status='paused',updated_at=now()
                   WHERE id=:id AND workspace_id=CAST(:ws AS uuid)
                   AND status IN ('draft','active') AND owner_web_account_id=:account
                   RETURNING id"""),{"id":campaign_id,"ws":ws,"account":account}).scalar_one_or_none()
            if not changed:raise HTTPException(404,"Campaign not found or already stopped")
            db.execute(text("""UPDATE public.ld_campaign_queue SET status='held',updated_at=now()
                 WHERE campaign_id=:id AND status IN ('pending_review','approved')"""),{
                 "id":campaign_id})
        return {"ok":True,"status":"paused","note":"Queued items held; no automatic sending remains active."}

    app.include_router(router)
