"""Pure import planning. No sends; preview changes no database state."""
from __future__ import annotations
import hashlib
import hmac
import os
import time
from urllib.parse import urlparse
from fastapi import HTTPException
from sqlalchemy import text
from letterdesk_import_diff import compare_record

def row_key(row,service):
    email=row["email"].lower()
    host=(urlparse(row["website"]).hostname or "").lower().removeprefix("www.")
    if service=="author":
        return "email:"+email if email else "author:"+row["name"].lower()+":"+row["country"].lower()+":"+host
    if host:return "site:"+host
    if email:return "email:"+email
    place=row.get("service_details",{}).get("place_id","")
    return "maps:"+place if place else "name:"+row["name"].lower()

def plan(engine,team,service,parsed):
    rows=parsed["rows"]+parsed["issues"]
    keys=list({row_key(r,service) for r in rows})
    emails=list({r["email"] for r in rows if r["email"]})
    existing={}
    suppressed=set()
    with engine.connect() as db:
        if keys or emails:
            found=db.execute(text("""SELECT l.dedupe_key,lower(l.email) AS email,
                      l.name,l.website,l.maps_url,l.country,l.city,l.source_url,l.details,
                      o.evidence_summary,o.service_details,
                      draft.subject,draft.body AS first_message,
                      draft.body_english AS first_message_english,
                      COALESCE(ir.branch_templates,'{}'::jsonb) AS branches
              FROM public.ld_leads l
              LEFT JOIN public.ld_opportunities o ON o.lead_id=l.id
               AND o.workspace_id IN (SELECT id FROM public.ld_service_workspaces
                    WHERE team_id=:team AND service_key=:service)
              LEFT JOIN LATERAL (
                SELECT m.subject,m.body,m.body_english
                FROM public.ld_message_records m
                JOIN public.ld_conversations c ON c.id=m.conversation_id
                WHERE c.opportunity_id=o.id AND m.status='needs_review'
                ORDER BY m.created_at DESC LIMIT 1
              ) draft ON true
              LEFT JOIN LATERAL (
                SELECT ir.branch_templates
                FROM public.ld_import_rows ir
                JOIN public.ld_import_batches ib ON ib.id=ir.batch_id
                WHERE ir.lead_id=l.id AND ib.source_service=:service
                ORDER BY ir.created_at DESC LIMIT 1
              ) ir ON true
              WHERE l.team_id=:team
              AND (l.dedupe_key=ANY(:keys) OR lower(l.email)=ANY(:emails))"""),
              {"team":team,"service":service,"keys":keys or ["--"],"emails":emails or ["--"]}).mappings()
            for item in found:
                data=dict(item)
                details=data.get("details") or {}
                stored=data.get("service_details") or (details.get("details") if isinstance(details,dict) else {}) or {}
                data["service_details"]={k:v for k,v in stored.items() if k!="_letterdesk_import_batch"}
                data["evidence_notes"]=data.get("evidence_summary") or ""
                data["branches"]={k:v for k,v in (data.get("branches") or {}).items() if not k.startswith("_")}
                existing["key:"+item["dedupe_key"]]=data
                if item["email"]:existing.setdefault("email:"+item["email"],data)
        if emails:
            suppressed={x for x in db.execute(text("""SELECT normalized_email
              FROM public.ld_suppressions WHERE team_id=:team
              AND normalized_email=ANY(:emails)"""),{"team":team,"emails":emails}).scalars()}
    output=[]
    for row in rows:
        obj=dict(row)
        key=row_key(row,service)
        status=row["disposition"]
        known=existing.get("key:"+key) or existing.get("email:"+row["email"])
        changes=None
        if row["email"] and row["email"] in suppressed:
            status="suppressed"
        elif status=="ready_for_import" and known:
            changes=compare_record(row,known)
            status="exact_duplicate" if changes["exact"] else "review_required"
            key=known["dedupe_key"]
        elif status=="ready_for_import":
            status="created"
        elif status=="historical_skip":
            status="skipped_duplicate"
        obj["identity_key"]=key
        obj["disposition"]=status
        obj["differences"]=changes["differences"] if changes else []
        obj["reason"]="; ".join(row["errors"]) if row["errors"] else (
          "Already suppressed" if row["email"] in suppressed and row["email"] else
          "Exact existing record; skipped automatically" if status=="exact_duplicate" else
          "Existing prospect has "+str(changes["new_fields"]+changes["changed_fields"])+" field changes; review before any replacement" if status=="review_required" else
          "Historical status not eligible for a new draft" if status=="skipped_duplicate" else "")
        obj.pop("errors",None)
        output.append(obj)
    summary={s:sum(x["disposition"]==s for x in output)
             for s in ("created","linked","suppressed","invalid","skipped_duplicate","exact_duplicate","review_required")}
    summary["rows_total"]=len(output)
    summary["first_message_drafts"]=sum(bool(x["first_message"]) and x["disposition"]=="created" and x["email"] for x in output)
    summary["branch_sets"]=sum(bool(x["branches"]) for x in output)
    return output,summary

def file_token(secret,team,service,sha,filename,rows,ts=None):
    if not isinstance(secret,str) or len(secret)<32:
        raise HTTPException(503,"Preview signing key unavailable")
    stamp=int(time.time()) if ts is None else ts
    value=f"{team}|{service}|{sha}|{filename}|{rows}|{stamp}"
    mac=hmac.new(secret.encode(),value.encode(),"sha256").hexdigest()
    return f"{stamp}.{mac}"

def verify_token(secret,token,team,service,sha,filename,rows):
    try:
        timestamp=int(token.split(".",1)[0])
        if timestamp>time.time()+60 or time.time()-timestamp>1200:raise ValueError()
        expected=file_token(secret,team,service,sha,filename,rows,timestamp)
    except (ValueError,IndexError):
        raise HTTPException(400,"Preview expired. Please preview again.")
    if not hmac.compare_digest(expected,token):
        raise HTTPException(400,"The file changed. Please preview it again.")

def preview_row(row):
    return {x:row.get(x) for x in ("row","name","email","website","source_url","disposition","reason","differences")} | {
       "first_message":bool(row.get("first_message")),"branches":list(row.get("branches",{}).keys())}
