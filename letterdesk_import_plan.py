"""Pure import planning. No sends; preview changes no database state."""
from __future__ import annotations
import hashlib
import hmac
import os
import time
from urllib.parse import urlparse
from fastapi import HTTPException
from sqlalchemy import text

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
            found=db.execute(text("""SELECT dedupe_key,lower(email) AS email
              FROM public.ld_leads WHERE team_id=:team
              AND (dedupe_key=ANY(:keys) OR lower(email)=ANY(:emails))"""),
              {"team":team,"keys":keys or ["--"],"emails":emails or ["--"]}).mappings()
            for item in found:
                existing["key:"+item["dedupe_key"]]=item["dedupe_key"]
                if item["email"]:existing.setdefault("email:"+item["email"],item["dedupe_key"])
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
        if row["email"] and row["email"] in suppressed:
            status="suppressed"
        elif status=="ready_for_import" and known:
            status="linked"
            key=known
        elif status=="ready_for_import":
            status="created"
        elif status=="historical_skip":
            status="skipped_duplicate"
        obj["identity_key"]=key
        obj["disposition"]=status
        obj["reason"]="; ".join(row["errors"]) if row["errors"] else (
          "Already suppressed" if row["email"] in suppressed and row["email"] else
          "Existing contact; no duplicate draft" if status=="linked" else
          "Historical status not eligible for a new draft" if status=="skipped_duplicate" else "")
        obj.pop("errors",None)
        output.append(obj)
    summary={s:sum(x["disposition"]==s for x in output)
             for s in ("created","linked","suppressed","invalid","skipped_duplicate")}
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
    return {x:row.get(x) for x in ("row","name","email","website","source_url","disposition","reason")} | {
       "first_message":bool(row.get("first_message")),"branches":list(row.get("branches",{}).keys())}
