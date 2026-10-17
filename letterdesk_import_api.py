"""Authenticated file import endpoints. Preview is read-only; confirm is gated."""
from __future__ import annotations
import hashlib
import os
import json
import csv
import io

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import text

from letterdesk_service_import import MAX_BYTES, SERVICES, parse_service_upload, import_headers
from letterdesk_import_plan import plan, file_token, verify_token, preview_row
from letterdesk_import_commit import save_confirmed_import
from letterdesk_import_undo import preview as preview_undo, execute as execute_undo, undo_enabled

def install_import_api(app:FastAPI,engine,authenticate):
    router=APIRouter(prefix="/api/v2/letterdesk",tags=["Letter Desk file imports"])
    def team_for(request,service):
        identity=authenticate(request)
        team=int(identity.get("team_id") or 0)
        if team<=0:raise HTTPException(403,"A linked team is required")
        if service not in SERVICES:raise HTTPException(404,"Invalid service")
        with engine.connect() as db:
            ok=db.execute(text("""SELECT 1 FROM public.ld_service_workspaces
                WHERE team_id=:team AND service_key=:service AND is_active=true"""),
                {"team":team,"service":service}).scalar_one_or_none()
        if not ok:raise HTTPException(404,"Service workspace not found")
        return team

    async def bounded_file(file):
        filename=(file.filename or "").replace("\\","/").split("/")[-1][:200]
        if not filename.lower().endswith((".xlsx",".xlsm",".csv")):
            raise HTTPException(400,"Upload an Excel workbook or CSV file")
        content=await file.read(MAX_BYTES+1)
        await file.close()
        if len(content)>MAX_BYTES:raise HTTPException(413,"8 MB upload limit exceeded")
        return content,filename

    def write_allowed():
        return os.getenv("LETTERDESK_IMPORT_WRITE_ENABLED","false").lower() in ("true","yes","1")

    @router.get("/services/{service}/imports/template.csv")
    def template(request:Request,service:str):
        team_for(request,service)
        out=io.StringIO(newline="")
        csv.writer(out).writerow(import_headers(service))
        return Response(("\ufeff"+out.getvalue()).encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition":f'attachment; filename="LetterDesk_{service}_template.csv"'})

    @router.get("/services/{service}/imports")
    def history(request:Request,service:str,limit:int=20):
        team=team_for(request,service)
        with engine.connect() as db:
            rows=db.execute(text("""SELECT b.id::text AS id,b.filename,b.status,b.rows_total,
               b.rows_imported,b.rows_skipped,b.preview_summary,b.created_at,b.finished_at
               FROM public.ld_import_batches b
               JOIN public.ld_service_workspaces w ON w.id=b.workspace_id
               WHERE w.team_id=:team AND w.service_key=:service
               ORDER BY b.created_at DESC LIMIT :lim"""),{
                  "team":team,"service":service,"lim":max(1,min(limit,40))
               }).mappings()
            items=[]
            for row in rows:
                obj=dict(row)
                for date in ("created_at","finished_at"):
                    if obj.get(date):obj[date]=obj[date].isoformat()
                items.append(obj)
        return {"ok":True,"imports":items,"write_enabled":write_allowed()}

    @router.post("/services/{service}/imports/preview")
    async def preview(request:Request,service:str,file:UploadFile=File(...)):
        team=team_for(request,service)
        data,filename=await bounded_file(file)
        try:
            parsed=parse_service_upload(data,filename,service)
        except ValueError as e:
            raise HTTPException(400,str(e))
        rows,summary=plan(engine,team,service,parsed)
        sha=hashlib.sha256(data).hexdigest()
        secret=os.getenv("LETTERDESK_IMPORT_SIGNING_SECRET") or os.getenv("APP_SECRET","")
        return {"ok":True,"filename":filename,"sheet":parsed["sheet"],"summary":summary,
                "columns":parsed["columns"],"branch_columns":parsed["branch_columns"],
                "sample":[preview_row(r) for r in rows[:25]],
                "preview_token":file_token(secret,team,service,sha,filename,len(rows)),
                "write_enabled":write_allowed(),
                "note":"Nothing has been imported or sent. Confirm only after reviewing the preview."}

    @router.post("/services/{service}/imports/confirm")
    async def confirm(request:Request,service:str,file:UploadFile=File(...),preview_token:str=Form(...)):
        team=team_for(request,service)
        if not write_allowed():raise HTTPException(403,"Import confirmation is disabled in staging")
        data,filename=await bounded_file(file)
        try:parsed=parse_service_upload(data,filename,service)
        except ValueError as e:raise HTTPException(400,str(e))
        rows,summary=plan(engine,team,service,parsed)
        sha=hashlib.sha256(data).hexdigest()
        secret=os.getenv("LETTERDESK_IMPORT_SIGNING_SECRET") or os.getenv("APP_SECRET","")
        verify_token(secret,preview_token,team,service,sha,filename,len(rows))
        if not rows:raise HTTPException(400,"No valid or excluded rows found")
        batch=save_confirmed_import(engine,team,service,filename,sha,parsed,rows,summary)
        return {"ok":True,"batch_id":batch,"summary":summary,
                "note":"Leads imported; all new messages remain unsent drafts requiring review."}

    @router.get("/services/{service}/imports/{batch_id}/undo-preview")
    def undo_preview(request:Request,service:str,batch_id:__import__("uuid").UUID):
        team=team_for(request,service)
        data=preview_undo(engine,team,service,batch_id)
        data["write_enabled"]=undo_enabled()
        return data

    @router.post("/services/{service}/imports/{batch_id}/undo")
    async def undo_import(request:Request,service:str,batch_id:__import__("uuid").UUID):
        team=team_for(request,service)
        if not undo_enabled():
            raise HTTPException(403,"Import undo is disabled in protected staging")
        identity=authenticate(request)
        account=int(identity.get("account_id") or 0)
        if account<1:raise HTTPException(403,"Signed-in account required")
        data=await request.json()
        if not isinstance(data,dict):
            raise HTTPException(400,"Invalid undo confirmation")
        return execute_undo(engine,team,service,batch_id,account,
            str(data.get("filename") or ""),str(data.get("confirmation_token") or ""))

    app.include_router(router)
