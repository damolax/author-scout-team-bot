"""Explicit, audited per-field import conflict decisions; never changes sent history.

Only workspace-authenticated users can approve research field updates. Message
edits are permitted solely on pre-existing unsent drafts. No mass auto-merge.
"""
from __future__ import annotations
import os
import re
from uuid import UUID
from fastapi import APIRouter,HTTPException,Request
from sqlalchemy import text
from letterdesk_import_diff import norm_value

LEAD_FIELDS={"name","website","maps_url","country","city","source_url"}
DRAFT_FIELDS={"subject","first_message","first_message_english"}
DETAIL_KEY=re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,65}$")
def normalize_decision(payload):
    if not isinstance(payload,dict):raise HTTPException(400,"Invalid review decision")
    action=payload.get("decision")
    if action not in ("accepted","rejected"):raise HTTPException(400,"Choose accept or reject")
    field=payload.get("field") or ""
    if field not in LEAD_FIELDS|DRAFT_FIELDS|{"evidence_notes"} and not (field.startswith("service_details.") and DETAIL_KEY.fullmatch(field.split(".",1)[1])):
        raise HTTPException(400,"This field cannot be replaced through imports")
    old,new=payload.get("previous"),payload.get("incoming")
    if not isinstance(old,str) or not isinstance(new,str) or len(old)>16000 or len(new)>16000 or not new.strip():
        raise HTTPException(400,"Review must include the previous and new value")
    if norm_value(field,old)==norm_value(field,new):
        raise HTTPException(409,"No change to approve")
    sha=payload.get("source_sha256") or ""
    if not isinstance(sha,str) or not re.fullmatch(r"[a-f0-9]{64}",sha):
        raise HTTPException(400,"A valid uploaded-file fingerprint is required")
    row=payload.get("row")
    if type(row)!=int or not 1<=row<=50001:raise HTTPException(400,"Invalid import row")
    return field,action,old,new,sha,row

def install_field_review_api(app,engine,authenticate):
    router=APIRouter(prefix="/api/v2/letterdesk",tags=["Reviewed import differences"])
    @router.post("/services/{service}/prospects/{opportunity_id}/review-field")
    async def review_field(request:Request,service:str,opportunity_id:UUID):
        auth=authenticate(request)
        team=int(auth.get("team_id") or 0)
        account=int(auth.get("account_id") or 0)
        if team<1 or account<1:raise HTTPException(403,"Signed-in team account required")
        if os.getenv("LETTERDESK_IMPORT_WRITE_ENABLED","false").lower() not in ("1","yes","true"):
            raise HTTPException(403,"Import changes are disabled in protected staging")
        field,decision,old,new,sha,row=normalize_decision(await request.json())
        with engine.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(:team)"),{"team":team})
            found=db.execute(text("""SELECT l.id AS lead_id,l.name,l.website,l.maps_url,
                   l.country,l.city,l.source_url,
                   o.id AS opportunity_id,o.evidence_summary,o.service_details,
                   w.id AS workspace_id
                 FROM public.ld_opportunities o
                 JOIN public.ld_service_workspaces w ON w.id=o.workspace_id
                 JOIN public.ld_leads l ON l.id=o.lead_id AND l.team_id=w.team_id
                 WHERE o.id=:id AND w.team_id=:team AND w.service_key=:service
                   AND w.is_active=true FOR UPDATE OF l,o"""),{
                    "id":opportunity_id,"team":team,"service":service}).mappings().first()
            if not found:raise HTTPException(404,"Prospect not found in this workspace")
            current=None;message_id=None
            if field in LEAD_FIELDS:current=found[field]
            elif field=="evidence_notes":current=found["evidence_summary"]
            elif field.startswith("service_details."):
                detail_key=field.split(".",1)[1]
                current=(found["service_details"] or {}).get(detail_key)
            else:
                # Never rewrite a message associated with any sent/replied history.
                sent=db.execute(text("""SELECT 1 FROM public.ld_conversations c
                    JOIN public.ld_message_records m ON m.conversation_id=c.id
                    WHERE c.opportunity_id=:opp AND m.status IN ('sent','replied')
                    LIMIT 1"""),{"opp":opportunity_id}).scalar_one_or_none()
                if sent:raise HTTPException(409,"Previously contacted prospect: sent messages cannot be replaced")
                message=db.execute(text("""SELECT m.id,m.subject,m.body,m.body_english
                    FROM public.ld_message_records m
                    JOIN public.ld_conversations c ON c.id=m.conversation_id
                    WHERE c.opportunity_id=:opp AND m.status='needs_review'
                    ORDER BY m.created_at DESC LIMIT 1 FOR UPDATE OF m"""),{
                        "opp":opportunity_id}).mappings().first()
                if not message:raise HTTPException(409,"No editable unsent draft exists; save a new reviewed draft separately")
                message_id=message["id"]
                current=message[{"subject":"subject","first_message":"body",
                                 "first_message_english":"body_english"}[field]]
            if norm_value(field,current)!=norm_value(field,old):
                raise HTTPException(409,"This field changed after the upload preview. Refresh comparison first.")
            if decision=="accepted":
                if field in LEAD_FIELDS:
                    if field in ("website","maps_url","source_url") and not new.startswith(("https://","http://")):
                        raise HTTPException(400,"Research links must use HTTP or HTTPS")
                    # Use known enum of identifier names, never user-provided SQL fragments.
                    db.execute(text("UPDATE public.ld_leads SET "+field+"=:value,updated_at=now() WHERE id=:id"),{
                        "id":found["lead_id"],"value":new})
                elif field=="evidence_notes":
                    db.execute(text("""UPDATE public.ld_opportunities
                        SET evidence_summary=:value,updated_at=now()
                        WHERE id=:id"""),{"id":opportunity_id,"value":new})
                elif field.startswith("service_details."):
                    db.execute(text("""UPDATE public.ld_opportunities
                       SET service_details=jsonb_set(COALESCE(service_details,'{}'::jsonb),
                          ARRAY[:key]::text[],to_jsonb(CAST(:value AS text)),true),
                          updated_at=now() WHERE id=:id"""),{
                        "id":opportunity_id,"key":detail_key,"value":new})
                else:
                    column={"subject":"subject","first_message":"body",
                            "first_message_english":"body_english"}[field]
                    db.execute(text("UPDATE public.ld_message_records SET "+column+"=:value WHERE id=:id AND status='needs_review'"),{
                        "value":new,"id":message_id})
            db.execute(text("""INSERT INTO public.ld_prospect_field_audit
                (team_id,workspace_id,lead_id,opportunity_id,reviewer_account_id,
                 field_name,previous_value,accepted_value,source_file_sha256,file_row_number,decision)
                VALUES (:team,:ws,:lead,:opp,:account,:field,:old,:new,:sha,:row,:decision)"""),{
                "team":team,"ws":found["workspace_id"],"lead":found["lead_id"],
                "opp":opportunity_id,"account":account,"field":field,
                "old":old,"new":new,"sha":sha,"row":row,"decision":decision})
        return {"ok":True,"decision":decision,"field":field,"messages_sent":0,
                "note":"Decision audited. Existing sent and suppression history was preserved."}
    app.include_router(router)
