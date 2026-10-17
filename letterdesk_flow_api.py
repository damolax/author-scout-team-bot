"""Phase 5: isolated, authenticated visual conversation design API.

Supports reading, validation/simulation, draft creation, optimistic edits,
revision history, and soft archival. No publish or outbound messaging endpoints.
All writes disabled on preview unless LETTERDESK_FLOW_WRITE_ENABLED=true.
"""
from __future__ import annotations

import json
import os
from uuid import UUID
from typing import Callable

from fastapi import APIRouter, FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from letterdesk_flow_engine import SERVICE_MODES, starter_flow, validate_flow, simulate

MAX_DOCUMENT_BYTES=220_000

def install_flow_api(app:FastAPI, engine, authenticate_web_session:Callable):
    router=APIRouter(prefix="/api/v2/letterdesk",tags=["Conversation designer"])

    def workspace(request,service):
        auth=authenticate_web_session(request)
        team=int(auth.get("team_id") or 0)
        if team<=0:raise HTTPException(403,"A linked team is required")
        if service not in SERVICE_MODES:raise HTTPException(404,"Service not found")
        with engine.connect() as db:
            row=db.execute(text("""SELECT id::text AS workspace_id FROM public.ld_service_workspaces
                WHERE team_id=:team AND service_key=:service AND is_active=true"""),
                {"team":team,"service":service}).mappings().first()
        if not row:raise HTTPException(404,"Service workspace not found")
        return team,row["workspace_id"]

    def ensure_writable():
        if os.getenv("LETTERDESK_FLOW_WRITE_ENABLED","false").strip().lower() not in ("true","yes","1"):
            raise HTTPException(403,"Conversation template saving is disabled on this preview.")

    def validate_doc(doc,service):
        if not isinstance(doc,dict):raise HTTPException(400,"Template document must be an object")
        if len(json.dumps(doc,ensure_ascii=False))>MAX_DOCUMENT_BYTES:
            raise HTTPException(413,"Template is too large")
        problems=validate_flow(doc,service=service)
        if problems:raise HTTPException(422,{"errors":problems})
        return doc

    def parse_name(name):
        if not isinstance(name,str):raise HTTPException(400,"Template name is required")
        cleaned=" ".join(name.split())[:110]
        if not cleaned:raise HTTPException(400,"Template name is required")
        return cleaned

    @router.get("/services/{service}/flows/starter")
    def starter(request:Request,service:str):
        workspace(request,service)
        return {"ok":True,"document":starter_flow(service),
                "note":"Example only: evidence placeholders must be verified before use."}

    @router.get("/services/{service}/flows")
    def list_flows(request:Request,service:str):
        team,wid=workspace(request,service)
        with engine.connect() as db:
            data=db.execute(text("""SELECT id::text,name,status,revision,language,
                created_at::text,updated_at::text
                FROM public.ld_flow_designs WHERE workspace_id=CAST(:wid AS uuid)
                ORDER BY updated_at DESC LIMIT 100"""),{"wid":wid}).mappings().all()
        return {"ok":True,"flows":[dict(x) for x in data],
                "write_enabled":os.getenv("LETTERDESK_FLOW_WRITE_ENABLED","false").lower() in ("true","yes","1")}

    @router.get("/services/{service}/flows/{flow_id}")
    def get_flow(request:Request,service:str,flow_id:UUID):
        team,wid=workspace(request,service)
        with engine.connect() as db:
            row=db.execute(text("""SELECT id::text,name,status,revision,language,document,
                    created_at::text,updated_at::text FROM public.ld_flow_designs
                    WHERE id=:id AND workspace_id=CAST(:wid AS uuid)"""),
                    {"id":flow_id,"wid":wid}).mappings().first()
        if row is None:raise HTTPException(404,"Template not found in this service")
        return {"ok":True,"flow":dict(row)}

    @router.get("/services/{service}/flows/{flow_id}/revisions")
    def get_revisions(request:Request,service:str,flow_id:UUID):
        team,wid=workspace(request,service)
        with engine.connect() as db:
            found=db.execute(text("""SELECT 1 FROM public.ld_flow_designs
                WHERE id=:id AND workspace_id=CAST(:wid AS uuid)"""),
                {"id":flow_id,"wid":wid}).scalar_one_or_none()
            if not found:raise HTTPException(404,"Template not found")
            rows=db.execute(text("""SELECT revision,edit_note,created_at::text
                FROM public.ld_flow_design_revisions
                WHERE design_id=:id ORDER BY revision DESC LIMIT 50"""),
                {"id":flow_id}).mappings().all()
        return {"ok":True,"revisions":[dict(x) for x in rows]}

    @router.post("/services/{service}/flows/validate")
    async def validate(request:Request,service:str):
        workspace(request,service)
        doc=await request.json()
        if len(json.dumps(doc,ensure_ascii=False))>MAX_DOCUMENT_BYTES:
            raise HTTPException(413,"Template is too large")
        problems=validate_flow(doc,service)
        return {"ok":not problems,"errors":problems,
                "nodes":len(doc.get("nodes",[])) if isinstance(doc,dict) else 0,
                "edges":len(doc.get("edges",[])) if isinstance(doc,dict) else 0,
                "note":"Validation does not publish or schedule messages."}

    @router.post("/services/{service}/flows/simulate")
    async def simulate_branch(request:Request,service:str):
        workspace(request,service)
        req=await request.json()
        if not isinstance(req,dict):raise HTTPException(400,"Invalid simulation request")
        doc=req.get("document")
        validate_doc(doc,service)
        current=req.get("current")
        if current not in [n.get("code") for n in doc["nodes"]]:
            raise HTTPException(400,"Unknown simulation starting message")
        count=req.get("messageCount",0)
        follows=req.get("noReplyFollowups",0)
        if type(count)!=int or type(follows)!=int or not 0<=count<=100 or not 0<=follows<=100:
            raise HTTPException(400,"Invalid message or follow-up count")
        return {"ok":True,"result":simulate(doc,current,str(req.get("outcome") or ""),count,follows),
                "note":"Simulation only. No customer reply was read and no email was sent."}

    @router.post("/services/{service}/flows")
    async def create(request:Request,service:str):
        team,wid=workspace(request,service)
        ensure_writable()
        incoming=await request.json()
        if not isinstance(incoming,dict):raise HTTPException(400,"Invalid request")
        name=parse_name(incoming.get("name"))
        doc=validate_doc(incoming.get("document"),service)
        language=str(incoming.get("language") or "en").strip().lower()[:12]
        if not language or not all(ch.isalnum() or ch in "-_" for ch in language):
            raise HTTPException(400,"Invalid language")
        try:
            with engine.begin() as db:
                # Team-bound limit, no concurrent duplicate creation.
                db.execute(text("SELECT pg_advisory_xact_lock(:team)"),{"team":team})
                count=db.execute(text("""SELECT count(*) FROM public.ld_flow_designs
                    WHERE workspace_id=CAST(:wid AS uuid) AND status='draft'"""),{"wid":wid}).scalar_one()
                if count>=70:raise HTTPException(429,"Too many draft templates in this service")
                row=db.execute(text("""INSERT INTO public.ld_flow_designs
                  (workspace_id,name,language,status,revision,document)
                  VALUES(CAST(:wid AS uuid),:name,:language,'draft',1,CAST(:doc AS jsonb))
                  RETURNING id::text"""),
                  {"wid":wid,"name":name,"language":language,"doc":json.dumps(doc)}).scalar_one()
                db.execute(text("""INSERT INTO public.ld_flow_design_revisions
                  (design_id,revision,snapshot,edit_note)
                  VALUES(CAST(:id AS uuid),1,CAST(:doc AS jsonb),'Initial draft')"""),
                  {"id":row,"doc":json.dumps(doc)})
        except IntegrityError:
            raise HTTPException(409,"A conversation template already uses this name")
        return {"ok":True,"id":row,"revision":1,"status":"draft",
                "note":"Draft saved; publishing and automatic sending remain disabled."}

    @router.put("/services/{service}/flows/{flow_id}")
    async def update(request:Request,service:str,flow_id:UUID):
        team,wid=workspace(request,service)
        ensure_writable()
        incoming=await request.json()
        if not isinstance(incoming,dict):raise HTTPException(400,"Invalid request")
        expected=incoming.get("expectedRevision")
        if type(expected)!=int or expected<1:raise HTTPException(400,"Expected revision is required")
        name=parse_name(incoming.get("name"))
        doc=validate_doc(incoming.get("document"),service)
        try:
            with engine.begin() as db:
                result=db.execute(text("""UPDATE public.ld_flow_designs
                   SET name=:name,revision=revision+1,document=CAST(:doc AS jsonb),updated_at=now()
                   WHERE id=:id AND workspace_id=CAST(:wid AS uuid)
                     AND revision=:expected AND status='draft'
                   RETURNING revision"""),{
                     "name":name,"doc":json.dumps(doc),"id":flow_id,"wid":wid,"expected":expected
                }).scalar_one_or_none()
                if result is None:raise HTTPException(409,"Template changed in another tab, was archived, or is unavailable. Reload before saving.")
                db.execute(text("""INSERT INTO public.ld_flow_design_revisions
                    (design_id,revision,snapshot,edit_note)
                    VALUES(:id,:revision,CAST(:snapshot AS jsonb),:note)"""),{
                    "id":flow_id,"revision":result,"snapshot":json.dumps(doc),
                    "note":"Saved from conversation editor"})
        except IntegrityError:
            raise HTTPException(409,"Another template already uses that name")
        return {"ok":True,"id":str(flow_id),"revision":int(result),"status":"draft",
                "note":"New draft revision saved. No messages queued."}

    @router.post("/services/{service}/flows/{flow_id}/archive")
    def archive(request:Request,service:str,flow_id:UUID):
        team,wid=workspace(request,service)
        ensure_writable()
        with engine.begin() as db:
            updated=db.execute(text("""UPDATE public.ld_flow_designs
                SET status='archived',updated_at=now()
                WHERE id=:id AND workspace_id=CAST(:wid AS uuid) AND status='draft'
                RETURNING id::text"""),{"id":flow_id,"wid":wid}).scalar_one_or_none()
            if not updated:raise HTTPException(404,"Draft template not found")
        return {"ok":True,"archived":True,
                "note":"Archived without deleting revisions or changing any conversations."}

    app.include_router(router)
