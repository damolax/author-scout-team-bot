"""Phase 7 authenticated reply inbox, manual triage and reviewed branching UI API."""
from __future__ import annotations
import os
import secrets
from uuid import UUID
from fastapi import APIRouter,FastAPI,HTTPException,Request
from sqlalchemy import text

from letterdesk_reply_rules import classify_reply,safe_draft,fallback_flow,OUTCOMES
from letterdesk_reply_store import (
    require_write,ingest_reply,review_reply,assign_flow,reveal_body,conversation_flow,
    get_conversation
)

SERVICES={"author","automation","website-design","digital-planner","shopify","google-maps"}

def install_reply_api(app:FastAPI,engine,authenticate):
    router=APIRouter(prefix="/api/v2/letterdesk",tags=["Reply review"])

    def scope(request,service):
        auth=authenticate(request)
        team=int(auth.get("team_id") or 0)
        account=int(auth.get("account_id") or 0)
        if team<1 or account<1:raise HTTPException(403,"Sign-in required")
        if service not in SERVICES:raise HTTPException(404,"Unknown service")
        with engine.connect() as db:
            ws=db.execute(text("""SELECT CAST(id AS TEXT) FROM public.ld_service_workspaces
                 WHERE team_id=:team AND service_key=:service AND is_active=true"""),{
                    "team":team,"service":service}).scalar_one_or_none()
        if not ws:raise HTTPException(404,"Service workspace unavailable")
        return team,account,ws

    @router.get("/services/{service}/replies")
    def list_replies(request:Request,service:str,limit:int=80,filter:str="all"):
        team,account,ws=scope(request,service)
        if filter not in ("all","pending_review","stopped","reviewed"):
            raise HTTPException(400,"Unknown status filter")
        with engine.connect() as db:
            rows=db.execute(text("""SELECT CAST(r.id AS TEXT) AS id,
                  CAST(r.conversation_id AS TEXT) AS conversation_id,
                  r.source,r.sender_email,r.body_encrypted,
                  r.received_at,r.suggested_outcome,r.outcome_confidence,
                  r.final_outcome,r.status,r.flow_message_code,r.proposed_next_code,
                  r.proposed_draft_encrypted,
                  l.name AS prospect_name,fd.name AS design_name,
                  s.service_key
                  FROM public.ld_reply_inbox r
                  JOIN public.ld_conversations c ON c.id=r.conversation_id
                  JOIN public.ld_opportunities o ON o.id=c.opportunity_id
                  JOIN public.ld_leads l ON l.id=o.lead_id AND l.team_id=:team
                  JOIN public.ld_service_workspaces s ON s.id=o.workspace_id
                  LEFT JOIN public.ld_conversation_flow_bindings b ON b.conversation_id=c.id
                  LEFT JOIN public.ld_flow_designs fd ON fd.id=b.flow_design_id
                  WHERE r.team_id=:team AND r.workspace_id=CAST(:ws AS uuid)
                  AND (:filter='all' OR r.status=:filter)
                  ORDER BY r.received_at DESC LIMIT :lim"""),{
                "team":team,"ws":ws,"filter":filter,"lim":max(1,min(limit,150))}).mappings().all()
        replies=[]
        for r in rows:
            item=dict(r)
            item["body"]=reveal_body(item.pop("body_encrypted"))
            encoded=item.pop("proposed_draft_encrypted")
            if encoded:
                import json
                try:item["proposed_draft"]=json.loads(reveal_body(encoded))
                except Exception:item["proposed_draft"]=None
            else:item["proposed_draft"]=None
            item["received_at"]=r["received_at"].isoformat() if r["received_at"] else None
            replies.append(item)
        return {"ok":True,"replies":replies,
                "write_enabled":os.getenv("LETTERDESK_REPLY_WRITE_ENABLED","false").lower() in ("true","1","yes"),
                "gmail_read_enabled":os.getenv("LETTERDESK_GMAIL_READ_ENABLED","false").lower() in ("true","1","yes")}

    @router.get("/services/{service}/replies/conversations")
    def conversations(request:Request,service:str,limit:int=130):
        team,account,ws=scope(request,service)
        with engine.connect() as db:
            rows=db.execute(text("""SELECT CAST(c.id AS TEXT) AS id,c.status,
                     l.name AS name,l.email AS email,
                     c.message_count,CAST(b.flow_design_id AS TEXT) AS flow_design_id,
                     COALESCE(b.current_code,'Message01') AS current_code
                  FROM public.ld_conversations c
                  JOIN public.ld_opportunities o ON o.id=c.opportunity_id
                  JOIN public.ld_leads l ON l.id=o.lead_id AND l.team_id=:team
                  LEFT JOIN public.ld_conversation_flow_bindings b ON b.conversation_id=c.id
                  WHERE o.workspace_id=CAST(:ws AS uuid)
                  AND EXISTS (SELECT 1 FROM public.ld_message_records m
                      WHERE m.conversation_id=c.id
                        AND m.status IN ('sent','replied'))
                  ORDER BY c.updated_at DESC LIMIT :lim"""),{
                     "ws":ws,"team":team,"lim":max(1,min(limit,250))}).mappings().all()
        return {"ok":True,"conversations":[dict(x) for x in rows]}

    @router.get("/services/{service}/replies/sync-health")
    def sync_health(request:Request,service:str):
        team,account,ws=scope(request,service)
        with engine.connect() as db:
            rows=db.execute(text("""SELECT c.primary_email,
                     c.status AS connection_status,
                     (c.scopes @> ARRAY['https://www.googleapis.com/auth/gmail.readonly']::text[]) AS has_read_permission,
                     coalesce(s.status,'not_started') AS status,
                     s.last_checked_at,s.last_success_at,s.last_error_code,
                     coalesce(s.scanned_threads,0) AS scanned_threads,
                     coalesce(s.fetched_replies,0) AS fetched_replies
                  FROM public.ld_gmail_connections c
                  LEFT JOIN public.ld_gmail_reply_sync s ON s.connection_id=c.id
                  WHERE c.team_id=:team AND EXISTS (
                    SELECT 1 FROM public.ld_gmail_sender_identities si
                    JOIN public.ld_campaigns cam ON cam.sender_identity_id=si.id
                    WHERE si.connection_id=c.id AND cam.workspace_id=CAST(:ws AS uuid))
                  ORDER BY c.updated_at DESC LIMIT 100"""),{
                   "team":team,"ws":ws}).mappings().all()
        result=[]
        for r in rows:
            item=dict(r)
            for key in ("last_checked_at","last_success_at"):
                item[key]=r[key].isoformat() if r[key] else None
            result.append(item)
        return {"ok":True,"connections":result,"read_active":os.getenv("LETTERDESK_GMAIL_READ_ENABLED","false").lower() in ("true","1","yes")}

    @router.post("/services/{service}/replies/classify")
    async def preview_classification(request:Request,service:str):
        team,account,ws=scope(request,service)
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(400,"Invalid reply preview")
        value=body.get("text")
        if not isinstance(value,str) or not value.strip() or len(value)>12000:
            raise HTTPException(400,"Provide 1–12,000 characters to preview")
        assessment=classify_reply(value)
        return {"ok":True,"suggestion":assessment,
                "note":"Read-only suggestion; no contact is changed. A human must verify the context."}

    @router.post("/services/{service}/replies/manual")
    async def record_manual(request:Request,service:str):
        team,account,ws=scope(request,service)
        require_write()
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(400,"Invalid reply")
        try:conversation=UUID(str(body.get("conversation_id") or ""))
        except Exception:raise HTTPException(400,"Choose a valid conversation")
        # Stable client key is required to avoid accidental duplicate submissions.
        manual_key=str(body.get("idempotency_key") or "")
        if len(manual_key)<20 or len(manual_key)>90 or not all(x.isalnum() or x in "-_" for x in manual_key):
            raise HTTPException(400,"Invalid idempotency key")
        return {"ok":True,**ingest_reply(engine,team,ws,conversation,
                    body.get("sender_email") or "",body.get("text") or "",
                    manual_key=manual_key)}

    @router.post("/services/{service}/replies/{reply_id}/review")
    async def decide(request:Request,service:str,reply_id:UUID):
        team,account,ws=scope(request,service)
        require_write()
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(400,"Invalid review payload")
        outcome=str(body.get("outcome") or "")
        if outcome not in OUTCOMES:raise HTTPException(400,"Invalid classification")
        return review_reply(engine,team,ws,reply_id,account,outcome)

    @router.post("/services/{service}/replies/conversations/{conversation_id}/flow")
    async def set_flow(request:Request,service:str,conversation_id:UUID):
        team,account,ws=scope(request,service)
        require_write()
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(400,"Invalid flow assignment")
        raw=body.get("flow_id")
        try:flow_id=UUID(str(raw)) if raw else None
        except Exception:raise HTTPException(400,"Invalid flow design")
        return assign_flow(engine,team,ws,conversation_id,flow_id,account)

    app.include_router(router)
