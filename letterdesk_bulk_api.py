"""Team-authenticated persistent 50k chunk uploads and job polling (no Gmail calls)."""
from __future__ import annotations
import os
from uuid import UUID
from fastapi import APIRouter,FastAPI,HTTPException,Request
from sqlalchemy import text

from letterdesk_bulk_import import (
    staging_enabled,writes_enabled,begin_job,store_part,finish_staging,
    progress_payload,confirm_job,checksum_token,PART_BYTES
)

SERVICES=("author","automation","website-design","digital-planner","shopify","google-maps")

def install_bulk_import_api(app:FastAPI,engine,authenticate):
    router=APIRouter(prefix="/api/v2/letterdesk",tags=["50k large-file uploads"])
    def auth(request,service):
        identity=authenticate(request)
        team=int(identity.get("team_id") or 0)
        account=int(identity.get("account_id") or 0)
        if team<1 or account<1:raise HTTPException(403,"Linked team and signed-in account required")
        if service not in SERVICES:raise HTTPException(404,"Unknown service")
        with engine.connect() as db:
            ws=db.execute(text("""SELECT CAST(id AS TEXT)
              FROM public.ld_service_workspaces WHERE team_id=:team
              AND service_key=:service AND is_active=true"""),
              {"team":team,"service":service}).scalar_one_or_none()
        if not ws:raise HTTPException(404,"Service workspace not found")
        return team,account,ws

    def job_for(db,job,team,account,ws):
        row=db.execute(text("""SELECT * FROM public.ld_bulk_upload_jobs
             WHERE id=:job AND team_id=:team
             AND workspace_id=CAST(:ws AS uuid)
             AND owner_account_id=:owner"""),{
              "job":job,"team":team,"ws":ws,"owner":account}).mappings().first()
        if row is None:raise HTTPException(404,"Upload job not found for your account and service")
        return dict(row)

    @router.get("/services/{service}/bulk-uploads/capabilities")
    def capabilities(request:Request,service:str):
        auth(request,service)
        # Report readiness without returning any OAuth/encryption/signing key.
        from letterdesk_bulk_import import signing_key,PART_BYTES,MAX_BYTES
        from letterdesk_gmail_api import sender_crypto
        crypto_ready=True
        signature_ready=True
        try:sender_crypto()
        except Exception:crypto_ready=False
        try:signing_key()
        except Exception:signature_ready=False
        return {"ok":True,"enabled":staging_enabled(),
                "can_stage_files":staging_enabled() and crypto_ready and signature_ready,
                "can_import_contacts":writes_enabled(),
                "encryption_ready":crypto_ready,"signing_ready":signature_ready,
                "max_rows":50000,"max_bytes":MAX_BYTES,
                "chunk_bytes":PART_BYTES,
                "message_sending_enabled":False}

    @router.get("/services/{service}/bulk-uploads")
    def history(request:Request,service:str):
        team,account,ws=auth(request,service)
        with engine.connect() as db:
            rows=db.execute(text("""SELECT id,filename,bytes_total,status,processed_rows,
               rows_total,accepted_rows,skipped_rows,created_at
               FROM public.ld_bulk_upload_jobs
               WHERE workspace_id=CAST(:ws AS uuid) AND team_id=:team
                 AND owner_account_id=:account
               ORDER BY created_at DESC LIMIT 15"""),{
                "team":team,"account":account,"ws":ws}).mappings().all()
        return {"ok":True,"enabled":staging_enabled(),"jobs":[{
             **dict(x),"id":str(x["id"]),"created_at":x["created_at"].isoformat()
             } for x in rows]}

    @router.post("/services/{service}/bulk-uploads")
    async def create(request:Request,service:str):
        team,account,ws=auth(request,service)
        if not staging_enabled():raise HTTPException(403,"Large-file staging is disabled")
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(400,"Invalid file manifest")
        name=str(body.get("filename") or "")
        size=body.get("size")
        sha=body.get("sha256")
        if type(size)!=int or not isinstance(sha,str):
            raise HTTPException(400,"File size and SHA-256 fingerprint required")
        return {"ok":True,**begin_job(engine,team,ws,account,name,size,sha)}

    @router.get("/services/{service}/bulk-uploads/{job_id}")
    def status(request:Request,service:str,job_id:UUID):
        team,account,ws=auth(request,service)
        with engine.connect() as db:
            job=job_for(db,job_id,team,account,ws)
            uploaded=[r for r in db.execute(text("""SELECT part_number FROM public.ld_bulk_upload_parts
                 WHERE job_id=:job ORDER BY part_number"""),{"job":job_id}).scalars()]
        payload=progress_payload(job)
        payload["parts_received"]=len(uploaded)
        payload["uploaded_part_numbers"]=uploaded
        payload["max_rows"]=50000
        payload["max_bytes"]=67108864
        if job["status"]=="ready" and job["preview_summary"] is not None:
            payload["confirmation_token"]=checksum_token(team,ws,job["id"],job["sha256"],
                                                           job["preview_summary"])
        return {"ok":True,**payload}

    @router.post("/services/{service}/bulk-uploads/{job_id}/parts/{index}")
    async def put_chunk(request:Request,service:str,job_id:UUID,index:int):
        team,account,ws=auth(request,service)
        if not staging_enabled():raise HTTPException(403,"Large-file staging is disabled")
        if index<0 or index>=64:raise HTTPException(400,"Invalid part number")
        # Read the HTTP body incrementally. Do not trust Content-Length:
        # a chunked/malformed request must never allocate unbounded memory.
        raw=bytearray()
        async for block in request.stream():
            raw.extend(block)
            if len(raw)>PART_BYTES:
                raise HTTPException(413,"Chunk exceeds 1 MB")
        if not raw:
            raise HTTPException(400,"Empty upload chunk")
        return store_part(engine,job_id,team,ws,account,index,bytes(raw))

    @router.post("/services/{service}/bulk-uploads/{job_id}/finish")
    def finish(request:Request,service:str,job_id:UUID):
        team,account,ws=auth(request,service)
        return {"ok":True,**finish_staging(engine,job_id,team,ws,account)}

    @router.post("/services/{service}/bulk-uploads/{job_id}/confirm")
    async def confirm(request:Request,service:str,job_id:UUID):
        team,account,ws=auth(request,service)
        if not writes_enabled():raise HTTPException(403,"Importing contacts is disabled in staging")
        body=await request.json()
        if not isinstance(body,dict):raise HTTPException(400,"Invalid confirmation")
        return {"ok":True,**confirm_job(engine,job_id,team,ws,account,
                                        str(body.get("confirmation_token") or ""))}

    app.include_router(router)
