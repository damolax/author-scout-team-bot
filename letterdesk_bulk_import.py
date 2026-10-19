"""Resumable Letter Desk large-file import jobs.

Encrypted chunked storage survives Render restarts. No unauthenticated data access,
no thread message sending, no unaudited insert. 500-row Neon transactions re-use
the existing service mapper, suppression planner, review-only message writer.
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import math
import os
import time
import uuid
from datetime import datetime,timezone
from sqlalchemy import text
from fastapi import HTTPException
from letterdesk_service_import import iter_service_chunks,MAX_BYTES,MAX_ROWS
from letterdesk_import_plan import plan
from letterdesk_import_commit import save_confirmed_import
from letterdesk_gmail_api import sender_crypto

PART_BYTES=1024*1024
MAX_PARTS=64
ROWS_PER_TX=500
PREVIEW_TTL=3600

def staging_enabled():
    return os.getenv("LETTERDESK_BULK_UPLOAD_ENABLED","false").lower() in ("1","true","yes")

def writes_enabled():
    return os.getenv("LETTERDESK_IMPORT_WRITE_ENABLED","false").lower() in ("1","true","yes")

def signing_key():
    key=os.getenv("LETTERDESK_IMPORT_SIGNING_SECRET") or os.getenv("APP_SECRET") or ""
    if len(key)<32:raise HTTPException(503,"Upload signing key is unavailable")
    return key.encode()

def checksum_token(team,service,job_id,sha,summary,timestamp=None):
    stamp=int(time.time()) if timestamp is None else int(timestamp)
    digest=hashlib.sha256(json.dumps(summary,sort_keys=True).encode()).hexdigest()
    payload=f"bulk:{team}:{service}:{job_id}:{sha}:{digest}:{stamp}".encode()
    sig=hmac.new(signing_key(),payload,hashlib.sha256).hexdigest()
    return f"{stamp}.{sig}"

def verify_checksum(token,team,service,job,sha,summary):
    try:
        ts,sig=token.split(".",1);ts=int(ts)
        if ts>time.time()+60 or time.time()-ts>PREVIEW_TTL:raise ValueError()
    except (ValueError,AttributeError):
        raise HTTPException(400,"Approval expired. Review the upload again.")
    if not hmac.compare_digest(token,checksum_token(team,service,job,sha,summary,ts)):
        raise HTTPException(409,"Upload or preview changed. Review the file again.")

def get_job(db,job_id,team,workspace):
    result=db.execute(text("""SELECT j.* FROM public.ld_bulk_upload_jobs j
          WHERE j.id=:job AND j.team_id=:team AND j.workspace_id=CAST(:ws AS uuid)"""),
          {"job":job_id,"team":team,"ws":workspace}).mappings().first()
    if not result:raise HTTPException(404,"Upload job does not belong to this service")
    return dict(result)

def begin_job(engine,team,workspace,account,filename,size,sha):
    if not staging_enabled():raise HTTPException(403,"Large-file uploads are not enabled on this preview")
    if not filename.lower().endswith((".xlsx",".xlsm",".csv")):
        raise HTTPException(400,"Choose CSV or XLSX/XLSM")
    if not 1<=size<=MAX_BYTES:raise HTTPException(413,"Maximum file size is 64 MB")
    if len(filename)>190 or not filename or "/" in filename or "\\" in filename:
        raise HTTPException(400,"Invalid file name")
    if len(sha)!=64 or any(c not in "0123456789abcdef" for c in sha):
        raise HTTPException(400,"File fingerprint must be a lowercase SHA-256")
    count=math.ceil(size/PART_BYTES)
    if count>MAX_PARTS:raise HTTPException(413,"Too many chunks")
    with engine.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(:team)"),{"team":int(team)})
        old=db.execute(text("""SELECT id::text,status FROM public.ld_bulk_upload_jobs
            WHERE workspace_id=CAST(:ws AS uuid) AND team_id=:team AND sha256=:sha"""),
            {"team":team,"ws":workspace,"sha":sha}).mappings().first()
        if old:
            if old["status"] in ("completed","processing","queued"):
                raise HTTPException(409,"This file is already imported or being processed in this service")
            return {"id":old["id"],"chunk_bytes":PART_BYTES,"parts":count,
                    "status":old["status"],"already_exists":True}
        jid=db.execute(text("""INSERT INTO public.ld_bulk_upload_jobs
            (workspace_id,team_id,owner_account_id,filename,bytes_total,part_size,
             part_count,sha256,status)
            VALUES(CAST(:ws AS uuid),:team,:account,:filename,:bytes,:part_size,
                   :part_count,:sha,'uploading') RETURNING id::text"""),
           {"ws":workspace,"team":team,"account":account,"filename":filename,
            "bytes":size,"part_size":PART_BYTES,"part_count":count,"sha":sha}).scalar_one()
    return {"id":jid,"chunk_bytes":PART_BYTES,"parts":count,"status":"uploading"}

def store_part(engine,job_id,team,workspace,account,index,data):
    if not staging_enabled():raise HTTPException(403,"Bulk uploads are disabled")
    if not isinstance(data,bytes) or len(data)>PART_BYTES or not data:
        raise HTTPException(413,"Chunk must contain between 1 byte and 1 MB")
    if type(index)!=int or index<0 or index>=MAX_PARTS:
        raise HTTPException(400,"Invalid chunk index")
    sha=hashlib.sha256(data).hexdigest()
    encrypted=sender_crypto().encrypt(data)
    with engine.begin() as db:
        job=get_job(db,job_id,team,workspace)
        if job["status"]!="uploading" or job["owner_account_id"]!=account:
            raise HTTPException(409,"Upload cannot be modified")
        expected=(PART_BYTES if index<job["part_count"]-1
                  else job["bytes_total"]-PART_BYTES*(job["part_count"]-1))
        if index>=job["part_count"] or len(data)!=expected:
            raise HTTPException(400,"Chunk size/index does not match file manifest")
        previous=db.execute(text("""SELECT sha256 FROM public.ld_bulk_upload_parts
             WHERE job_id=:job AND part_number=:idx"""),{"job":job_id,"idx":index}).scalar_one_or_none()
        if previous is not None:
            if previous!=sha:raise HTTPException(409,"Chunk changed after upload; start a new file")
            return {"ok":True,"duplicate":True,"index":index}
        db.execute(text("""INSERT INTO public.ld_bulk_upload_parts
             (job_id,part_number,size_bytes,sha256,encrypted_bytes)
             VALUES(:job,:idx,:size,:sha,:body)"""),
             {"job":job_id,"idx":index,"size":len(data),"sha":sha,"body":encrypted})
    return {"ok":True,"index":index}

def load_bytes(db,job):
    parts=db.execute(text("""SELECT part_number,size_bytes,sha256,encrypted_bytes
          FROM public.ld_bulk_upload_parts WHERE job_id=:job ORDER BY part_number"""),
          {"job":job["id"]}).mappings().all()
    if len(parts)!=job["part_count"]:
        raise ValueError("Upload is incomplete. Resume missing chunks.")
    result=bytearray()
    crypt=sender_crypto()
    for i,part in enumerate(parts):
        if part["part_number"]!=i:raise ValueError("Upload has a missing chunk")
        chunk=crypt.decrypt(bytes(part["encrypted_bytes"]))
        if len(chunk)!=part["size_bytes"] or hashlib.sha256(chunk).hexdigest()!=part["sha256"]:
            raise ValueError("Upload chunk integrity check failed")
        result.extend(chunk)
    if len(result)!=job["bytes_total"] or hashlib.sha256(result).hexdigest()!=job["sha256"]:
        raise ValueError("Full upload fingerprint does not match file")
    return bytes(result)

def finish_staging(engine,job_id,team,workspace,account):
    if not staging_enabled():raise HTTPException(403,"Bulk uploads disabled")
    with engine.begin() as db:
        job=get_job(db,job_id,team,workspace)
        if job["owner_account_id"]!=account:raise HTTPException(403,"Only upload owner may complete it")
        if job["status"] in ("ready","previewing"):return {"status":job["status"]}
        if job["status"]!="uploading":raise HTTPException(409,"Upload is no longer modifiable")
        # Verify every chunk + SHA before queuing an asynchronous preview.
        load_bytes(db,job)
        db.execute(text("""UPDATE public.ld_bulk_upload_jobs SET status='previewing',
              lease_expires_at=NULL,updated_at=now() WHERE id=:job"""),{"job":job_id})
    return {"status":"previewing","message":"Preview is being checked in background"}

def progress_payload(job):
    return {"id":str(job["id"]),"status":job["status"],
      "filename":job["filename"],"bytes_total":job["bytes_total"],
      "parts":job["part_count"],"processed_parts":job["processed_parts"],
      "processed_rows":job["processed_rows"],"rows_total":job["rows_total"],
      "accepted_rows":job["accepted_rows"],"skipped_rows":job["skipped_rows"],
      "preview_summary":job["preview_summary"],"preview_sample":job["preview_sample"],
      "preview_sheet":job["preview_sheet"],"preview_columns":job["preview_columns"],
      "last_error":job["last_error"],
      "write_enabled":writes_enabled()}

def confirm_job(engine,job_id,team,workspace,account,confirmation):
    if not writes_enabled():raise HTTPException(403,"Bulk import database writes are disabled")
    with engine.begin() as db:
        job=get_job(db,job_id,team,workspace)
        if job["owner_account_id"]!=account:raise HTTPException(403,"Only upload owner can confirm import")
        if job["status"]!="ready":raise HTTPException(409,"Review must finish before import")
        summary=job["preview_summary"]
        verify_checksum(confirmation,team,job["workspace_id"],job["id"],job["sha256"],summary)
        db.execute(text("""UPDATE public.ld_bulk_upload_jobs SET status='queued',
              updated_at=now(),processed_parts=0,processed_rows=0,
              accepted_rows=0,skipped_rows=0,last_error=NULL
              WHERE id=:job AND status='ready'"""),{"job":job_id})
    return {"status":"queued","message":"Import accepted. Database worker will process up to 500 contacts per transaction."}

def claim_job(engine):
    with engine.begin() as db:
        row=db.execute(text("""SELECT id,status FROM public.ld_bulk_upload_jobs
           WHERE status IN ('previewing','queued')
             OR (status='processing' AND lease_expires_at<now())
           ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED""")).mappings().first()
        if not row:return None
        status="previewing" if row["status"]=="previewing" else "processing"
        job=db.execute(text("""UPDATE public.ld_bulk_upload_jobs
           SET status=:status,lease_expires_at=now()+interval '60 minutes',
             started_at=COALESCE(started_at,now()),updated_at=now()
           WHERE id=:id RETURNING *"""),{"id":row["id"],"status":status}).mappings().one()
        return dict(job)

def preview_worker(engine,job):
    with engine.connect() as db:
        raw=load_bytes(db,job)
    summary={s:0 for s in ("created","linked","suppressed","invalid","skipped_duplicate","rows_total","first_message_drafts","branch_sets")}
    sample=[];index=0;first=None
    for partial in iter_service_chunks(raw,job["filename"],job["workspace_id"] if False else job["_service"],ROWS_PER_TX):
        if not first:first=partial
        rows,stats=plan(engine,job["team_id"],job["_service"],partial)
        for key in summary:summary[key]+=stats.get(key,0)
        for row in rows[:max(0,25-len(sample))]:
            from letterdesk_import_plan import preview_row
            sample.append(preview_row(row))
        index+=1
        with engine.begin() as db:
            db.execute(text("""UPDATE public.ld_bulk_upload_jobs SET
                processed_parts=:parts,processed_rows=:rows,
                lease_expires_at=now()+interval '60 minutes',updated_at=now()
                WHERE id=:job"""),{"job":job["id"],"parts":index,"rows":summary["rows_total"]})
    if not first or summary["rows_total"]==0:
        raise ValueError("No nonempty prospect rows found")
    with engine.begin() as db:
        db.execute(text("""UPDATE public.ld_bulk_upload_jobs SET
          status='ready',preview_summary=CAST(:summary AS jsonb),
          preview_sample=CAST(:sample AS jsonb),preview_sheet=:sheet,
          preview_columns=CAST(:columns AS jsonb),rows_total=:total,
          processed_rows=0,processed_parts=0,lease_expires_at=NULL,
          updated_at=now() WHERE id=:job"""),
          {"summary":json.dumps(summary),"sample":json.dumps(sample),
          "sheet":first["sheet"],"columns":json.dumps(first["columns"]),
          "total":summary["rows_total"],"job":job["id"]})

def commit_worker(engine,job):
    with engine.connect() as db:
        raw=load_bytes(db,job)
    for index,partial in enumerate(iter_service_chunks(raw,job["filename"],job["_service"],ROWS_PER_TX)):
        if index < job["processed_parts"]:continue
        sha=hashlib.sha256(f"{job['sha256']}:{index}".encode()).hexdigest()
        with engine.connect() as db:
            existing=db.execute(text("""SELECT rows_imported,rows_skipped,rows_total
              FROM public.ld_import_batches WHERE owner_team_id=:team
              AND source_service=:service AND file_sha256=:sha AND status='completed'
              AND rolled_back_at IS NULL"""),
              {"team":job["team_id"],"service":job["_service"],"sha":sha}).mappings().first()
        if existing:
            stats={"created":existing["rows_imported"],"linked":0,
                    "suppressed":0,"invalid":0,"skipped_duplicate":existing["rows_skipped"],
                    "rows_total":existing["rows_total"]}
        else:
            rows,stats=plan(engine,job["team_id"],job["_service"],partial)
            name=job["filename"].rsplit(".",1)
            partname=f"{name[0][:130]}__bulk_{str(job['id'])[:8]}_{index+1:04d}.{name[1]}"
            save_confirmed_import(engine,job["team_id"],job["_service"],partname,sha,partial,rows,stats)
        with engine.begin() as db:
            db.execute(text("""UPDATE public.ld_bulk_upload_jobs
                  SET processed_parts=:parts,processed_rows=processed_rows+:rows,
                    accepted_rows=accepted_rows+:accepted,
                    skipped_rows=skipped_rows+:skipped,
                    lease_expires_at=now()+interval '60 minutes',
                    updated_at=now()
                  WHERE id=:job AND processed_parts=:previous"""),{
              "job":job["id"],"parts":index+1,"previous":index,"rows":stats["rows_total"],
              "accepted":stats["created"]+stats["linked"],
              "skipped":stats["suppressed"]+stats["invalid"]+stats["skipped_duplicate"]})
    with engine.begin() as db:
        db.execute(text("""UPDATE public.ld_bulk_upload_jobs SET status='completed',
           finished_at=now(),lease_expires_at=NULL,updated_at=now()
           WHERE id=:job AND status='processing'"""),{"job":job["id"]})
        # Remove temporary copies of research & email text after import. Imported
        # rows retain their own evidence and review drafts as intended.
        db.execute(text("DELETE FROM public.ld_bulk_upload_parts WHERE job_id=:job"),{"job":job["id"]})

def job_once(engine):
    if not staging_enabled():return {"status":"disabled"}
    job=claim_job(engine)
    if not job:return {"status":"idle"}
    try:
        with engine.connect() as db:
            service=db.execute(text("""SELECT service_key FROM public.ld_service_workspaces
               WHERE id=:ws AND team_id=:team"""),{"ws":job["workspace_id"],"team":job["team_id"]}).scalar_one()
        job["_service"]=service
        if job["status"]=="previewing":preview_worker(engine,job)
        elif writes_enabled():commit_worker(engine,job)
        else:
            with engine.begin() as db:
                db.execute(text("""UPDATE public.ld_bulk_upload_jobs SET status='queued',
                    lease_expires_at=NULL,updated_at=now() WHERE id=:id"""),{"id":job["id"]})
        return {"status":job["status"],"id":str(job["id"])}
    except Exception as error:
        with engine.begin() as db:
            db.execute(text("""UPDATE public.ld_bulk_upload_jobs SET status='failed',
                 lease_expires_at=NULL,last_error=:error,updated_at=now()
                 WHERE id=:id"""),{"id":job["id"],"error":type(error).__name__[:80]})
        return {"status":"failed","error":type(error).__name__}

async def job_loop(engine,interval=5):
    while staging_enabled():
        try:
            # File parsing and PostgreSQL chunk writes can take several seconds;
            # offload to a thread so login and status APIs remain responsive.
            result=await asyncio.to_thread(job_once,engine)
            if result["status"]!="idle":continue
        except asyncio.CancelledError:raise
        except Exception as error:
            print("LETTERDESK_BULK_WORKER_ERROR="+type(error).__name__)
        await asyncio.sleep(max(3,interval))
