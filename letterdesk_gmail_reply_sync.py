"""Phase 7 opt-in Gmail thread monitoring for already-sent Letter Desk campaigns.

Minimal access: Gmail readonly scope. Only GET known outbound thread IDs,
never enumerate the user's mailbox or read unrelated threads. Does not send.
Disabled unless LETTERDESK_GMAIL_READ_ENABLED + LETTERDESK_REPLY_WRITE_ENABLED.
"""
from __future__ import annotations
import asyncio
import base64
import os
import re
from datetime import datetime,timezone
from uuid import UUID
from urllib.parse import quote

import httpx
from sqlalchemy import text
from letterdesk_gmail_api import READ_SCOPE,TOKEN_URL,sender_crypto
from letterdesk_reply_rules import canonical_address
from letterdesk_reply_store import ingest_reply

THREAD_RE=re.compile(r"^[A-Za-z0-9_-]{5,90}$")
PROVIDER_ID_RE=re.compile(r"^[A-Za-z0-9_-]{5,90}$")
MAX_THREAD_CHECKS=12
MAX_THREAD_MESSAGES=80
MAX_RECEIVED_BODY=12000
GOOGLE_API="https://gmail.googleapis.com/gmail/v1/users/me/threads/"

def read_enabled():
    return (os.getenv("LETTERDESK_GMAIL_READ_ENABLED","false").lower() in ("true","1","yes")
       and os.getenv("LETTERDESK_REPLY_WRITE_ENABLED","false").lower() in ("true","1","yes"))

def gmail_headers(message):
    header_list=(message.get("payload") or {}).get("headers") or []
    return {str(x.get("name") or "").lower():str(x.get("value") or "") for x in header_list[:100]}

def _decode_urlsafe(value):
    try:
        raw=str(value or "")
        if len(raw)>100000:return ""
        return base64.urlsafe_b64decode(raw+"="*((-len(raw))%4)).decode("utf-8","replace")[:MAX_RECEIVED_BODY]
    except Exception:return ""

def message_plain_text(message):
    payload=message.get("payload") or {}
    stack=[(payload,0)]
    while stack:
        current,depth=stack.pop()
        if depth>7:continue
        mime=current.get("mimeType") or ""
        if mime=="text/plain" and (current.get("body") or {}).get("data"):
            return _decode_urlsafe(current["body"]["data"])
        # Do not open attachments, HTML, non-text MIME types, or external URLs.
        for part in reversed((current.get("parts") or [])[:20]):
            if part.get("filename") or (part.get("body") or {}).get("attachmentId"):
                continue
            stack.append((part,depth+1))
    return ""

def matching_inbound_messages(thread,recipient_email,sender_account,original_message_id,sent_at):
    """Matches FROM=recipient and sent thread ID and time; no subject/name-only joins."""
    recipient=canonical_address(recipient_email)
    sender=canonical_address(sender_account)
    if not recipient or not sender or not isinstance(thread,dict):return []
    output=[]
    for m in (thread.get("messages") or [])[:MAX_THREAD_MESSAGES]:
        mid=str(m.get("id") or "")
        if not PROVIDER_ID_RE.fullmatch(mid) or mid==original_message_id:continue
        headers=gmail_headers(m)
        frm=canonical_address(headers.get("from"))
        to_values=(headers.get("to") or "")+" "+(headers.get("delivered-to") or "")
        if frm!=recipient:continue
        # Avoid unrelated messages in thread; allow BCC/reply routing when Gmail
        # metadata omitted explicit To only for a single exact source contact.
        to_addresses=[canonical_address(x) for x in re.split(r"[,;]",to_values)]
        if sender not in to_addresses:
            continue
        if not str(m.get("internalDate") or "").isdigit():continue
        date=datetime.fromtimestamp(int(m["internalDate"])/1000,timezone.utc)
        if sent_at and date<=sent_at:continue
        plain=message_plain_text(m)
        if not plain.strip():continue
        output.append({"provider_message_id":mid,"sender":frm,"received_at":date,
                       "body":plain,"thread_id":thread.get("id")})
    return sorted(output,key=lambda v:v["received_at"])

async def token_for_connection(encrypted_refresh):
    refresh=sender_crypto().decrypt(encrypted_refresh.encode()).decode()
    cid=os.getenv("GOOGLE_CLIENT_ID") or ""
    secret=os.getenv("GOOGLE_CLIENT_SECRET") or ""
    if not cid or not secret:raise RuntimeError("oauth_client_not_configured")
    async with httpx.AsyncClient(timeout=20) as client:
        response=await client.post(TOKEN_URL,data={
            "client_id":cid,"client_secret":secret,
            "refresh_token":refresh,"grant_type":"refresh_token"})
        if response.status_code!=200:raise RuntimeError("google_refresh_failed")
        token=str(response.json().get("access_token") or "")
        if not token:raise RuntimeError("access_token_missing")
        return token

async def fetch_authorized_thread(token,thread_id):
    if not THREAD_RE.fullmatch(thread_id):raise ValueError("invalid_thread_id")
    url=GOOGLE_API+quote(thread_id,safe="")
    async with httpx.AsyncClient(timeout=25) as client:
        result=await client.get(url,params={"format":"full"},headers={"Authorization":"Bearer "+token})
        if result.status_code!=200:raise RuntimeError("gmail_thread_http_"+str(result.status_code))
        thread=result.json()
        if thread.get("id")!=thread_id:raise RuntimeError("provider_thread_identity_mismatch")
        return thread

def eligible_connections(engine,limit=5):
    with engine.connect() as db:
        rows=db.execute(text("""SELECT c.id,c.team_id,c.primary_email,c.refresh_token_encrypted,
             c.scopes FROM public.ld_gmail_connections c
             WHERE c.status='connected' AND
             EXISTS(SELECT 1 FROM public.ld_gmail_sender_identities s
                 JOIN public.ld_campaigns cam ON cam.sender_identity_id=s.id
                 WHERE s.connection_id=c.id AND cam.status IN ('draft','active'))
             AND c.scopes @> ARRAY['https://www.googleapis.com/auth/gmail.readonly']::text[]
             ORDER BY c.updated_at ASC LIMIT :limit"""),{"limit":limit}).mappings().all()
    return [dict(r) for r in rows]

def next_threads(engine,connection_id,limit=MAX_THREAD_CHECKS):
    with engine.connect() as db:
        rows=db.execute(text("""SELECT q.id AS queue_id,q.provider_thread_id,
           q.provider_message_id,q.sent_at,q.recipient_email,s.email AS sender_email,
           c.id AS conversation_id,w.id AS workspace_id,w.team_id
         FROM public.ld_campaign_queue q
         JOIN public.ld_gmail_sender_identities s ON s.id=q.sender_identity_id
         JOIN public.ld_campaigns cam ON cam.id=q.campaign_id
         JOIN public.ld_service_workspaces w ON w.id=cam.workspace_id
         JOIN public.ld_message_records m ON m.id=q.message_record_id
         JOIN public.ld_conversations c ON c.id=m.conversation_id
         LEFT JOIN public.ld_gmail_thread_watch tw ON tw.queue_id=q.id
         WHERE s.connection_id=:conn AND q.status='sent'
           AND q.provider_thread_id IS NOT NULL
           AND c.status NOT IN ('stopped','lost','won')
         ORDER BY tw.last_checked_at ASC NULLS FIRST,q.sent_at DESC
         LIMIT :lim"""),{"conn":connection_id,"lim":limit}).mappings().all()
    return [dict(x) for x in rows]

def record_sync(engine,connection_id,status,checked,ingested,error=None):
    with engine.begin() as db:
        db.execute(text("""INSERT INTO public.ld_gmail_reply_sync
          (connection_id,last_checked_at,last_success_at,last_error_code,
           scanned_threads,fetched_replies,status)
          VALUES(:conn,now(),CASE WHEN :status='healthy' THEN now() ELSE NULL END,
                 :error,:checked,:ingested,:status)
          ON CONFLICT(connection_id) DO UPDATE SET
             last_checked_at=now(),
             last_success_at=CASE WHEN EXCLUDED.status='healthy'
                THEN now() ELSE public.ld_gmail_reply_sync.last_success_at END,
             last_error_code=EXCLUDED.last_error_code,
             scanned_threads=public.ld_gmail_reply_sync.scanned_threads+EXCLUDED.scanned_threads,
             fetched_replies=public.ld_gmail_reply_sync.fetched_replies+EXCLUDED.fetched_replies,
             status=EXCLUDED.status,updated_at=now()"""),{
                 "conn":connection_id,"status":status,"checked":checked,
                 "ingested":ingested,"error":error})

def mark_thread_checked(engine,queue_id,code=None):
    with engine.begin() as db:
        db.execute(text("""INSERT INTO public.ld_gmail_thread_watch(queue_id,last_checked_at,last_error_code)
            VALUES(:qid,now(),:code)
            ON CONFLICT(queue_id) DO UPDATE SET last_checked_at=now(),
                last_error_code=EXCLUDED.last_error_code,updated_at=now()"""),{
                "qid":queue_id,"code":code})

async def run_connection_sync(engine,connection):
    if not read_enabled():return {"status":"disabled"}
    if READ_SCOPE not in (connection.get("scopes") or []):
        await asyncio.to_thread(record_sync,engine,connection["id"],"scope_missing",0,0,"gmail_readonly_missing")
        return {"status":"scope_missing"}
    try:
        token=await token_for_connection(connection["refresh_token_encrypted"])
    except Exception:
        await asyncio.to_thread(record_sync,engine,connection["id"],"error",0,0,"token_refresh_failed")
        return {"status":"error"}
    count=0;received=0;failures=0
    for row in await asyncio.to_thread(next_threads,engine,connection["id"]):
        if not read_enabled():break
        try:
            thread=await fetch_authorized_thread(token,row["provider_thread_id"])
            if thread.get("id")!=row["provider_thread_id"]:raise ValueError("thread_mismatch")
            matches=matching_inbound_messages(thread,row["recipient_email"],row["sender_email"],
                                               row["provider_message_id"],row["sent_at"])
            for m in matches:
                try:
                    result=await asyncio.to_thread(ingest_reply,engine,row["team_id"],str(row["workspace_id"]),
                       row["conversation_id"],m["sender"],m["body"],source="gmail_thread",
                       provider_message_id=m["provider_message_id"],
                       gmail_connection_id=connection["id"],campaign_queue_id=row["queue_id"],
                       received_at=m["received_at"])
                    if result.get("created"):received+=1
                except Exception as exc:
                    # Stopped conversation / duplicate is safe; never resume outreach.
                    failures+=1
            await asyncio.to_thread(mark_thread_checked,engine,row["queue_id"],None)
        except Exception as exc:
            failures+=1
            await asyncio.to_thread(mark_thread_checked,engine,row["queue_id"],type(exc).__name__[:50])
        count+=1
    status="healthy" if failures==0 else "error"
    await asyncio.to_thread(record_sync,engine,connection["id"],status,count,received,
                            "thread_read_or_ingest_failed" if failures else None)
    return {"status":status,"threads_checked":count,"replies_created":received,"errors":failures}

async def gmail_reply_worker(engine,poll_seconds=600):
    """Opt-in read-only thread checks. Never auto-sends any message."""
    while read_enabled():
        try:
            for conn in await asyncio.to_thread(eligible_connections,engine):
                if not read_enabled():break
                await run_connection_sync(engine,conn)
        except asyncio.CancelledError:raise
        except Exception as exc:
            print("LETTERDESK_REPLY_SYNC_ERROR="+type(exc).__name__)
        await asyncio.sleep(max(300,int(poll_seconds)))

