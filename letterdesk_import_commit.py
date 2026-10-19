"""Atomic and idempotent Neon import of previously reviewed file rows.

New messages always have needs_review status. No external sending or OAuth.
Only user-confirmed requests may invoke save_confirmed_import().
"""
from __future__ import annotations
import json

from fastapi import HTTPException
from sqlalchemy import text

def save_confirmed_import(engine,team,service,filename,sha,parsed,rows,summary):
    good=[r for r in rows if r["disposition"] in ("created","linked")]
    packed=[{
        "row":int(r["row"]),"key":r["identity_key"],"name":r["name"],
        "email":r["email"] or None,"website":r["website"] or None,
        "maps_url":r["maps_url"] or None,"country":r["country"] or None,"city":r["city"] or None,
        "source_url":r["source_url"] or None,"evidence":r["evidence_notes"][:1500],
        "details":r["service_details"],"subject":r["subject"],"body":r["first_message"],
        "english":r["first_message_english"],"disposition":r["disposition"],
    } for r in good]
    # Preserve authored messages even when the lead has no email yet or
    # already exists; they remain passive templates, not sending instructions.
    meta=[{"row":int(r["row"]),"key":r["identity_key"],"disposition":r["disposition"],
          "reason":r["reason"][:1000],
          "branches":{
              **r["branches"],
              **({"Message01":r["first_message"]} if r["first_message"] and "Message01" not in r["branches"] else {}),
              **({"_draft_subject":r["subject"]} if r["subject"] else {}),
              **({"_draft_english":r["first_message_english"]} if r["first_message_english"] else {}),
          },
          "message":bool(r["first_message"])} for r in rows]
    with engine.begin() as db:
        # Prevent simultaneous imports for one team from racing against dedupe.
        db.execute(text("SELECT pg_advisory_xact_lock(:team)"),{"team":int(team)})
        workspace=db.execute(text("""SELECT id FROM public.ld_service_workspaces
             WHERE team_id=:team AND service_key=:service AND is_active=true"""),
             {"team":team,"service":service}).scalar_one_or_none()
        if not workspace:raise HTTPException(404,"Workspace not found")
        existing=db.execute(text("""SELECT id::text FROM public.ld_import_batches
           WHERE owner_team_id=:team AND source_service=:service AND file_sha256=:sha
           AND status='completed' AND rolled_back_at IS NULL"""),
           {"team":team,"service":service,"sha":sha}).scalar_one_or_none()
        if existing:raise HTTPException(409,"This file was already imported into this service.")

        batch=db.execute(text("""INSERT INTO public.ld_import_batches
          (workspace_id,filename,source_format,status,rows_total,rows_imported,rows_skipped,
           column_map,issues,file_sha256,source_service,owner_team_id,preview_summary,finished_at)
          VALUES (:ws,:filename,:format,'completed',:total,:accepted,:skipped,
           CAST(:columns AS jsonb),CAST(:issues AS jsonb),:sha,:service,:team,
           CAST(:summary AS jsonb),now()) RETURNING id::text"""),{
           "ws":workspace,"filename":filename[:200],"format":filename.rsplit(".",1)[-1].lower(),
           "total":summary["rows_total"],"accepted":summary["created"]+summary["linked"],
           "skipped":summary["suppressed"]+summary["invalid"]+summary["skipped_duplicate"],
           "columns":json.dumps({"columns":parsed["columns"],"branches":parsed["branch_columns"]}),
           "issues":json.dumps([{"row":r["row"],"reason":r["reason"]} for r in rows
                         if r["disposition"]=="invalid"][:150]),
           "sha":sha,"team":team,"service":service,"summary":json.dumps(summary)
        }).scalar_one()

        # One PostgreSQL bulk INSERT per entity, not one request per contact.
        db.execute(text("""WITH src AS (
            SELECT * FROM jsonb_to_recordset(CAST(:input AS jsonb)) AS x(
             row int,key text,name text,email text,website text,maps_url text,
             country text,city text,source_url text,evidence text,details jsonb,
             subject text,body text,english text,disposition text)
          )
          INSERT INTO public.ld_leads
          (team_id,dedupe_key,name,kind,email,website,maps_url,country,city,source_url,
           contact_verification,details)
          SELECT :team,key,name,:kind,email,website,maps_url,country,city,source_url,
             'imported_unverified',jsonb_build_object('import_batch',:batch,'service',:service,'details',details)
          FROM src WHERE disposition='created'
          ON CONFLICT(team_id,dedupe_key) DO NOTHING"""),{
          "input":json.dumps(packed),"team":team,"kind":"person" if service=="author" else "business",
          "batch":batch,"service":service
        })

        db.execute(text("""WITH src AS (
           SELECT * FROM jsonb_to_recordset(CAST(:input AS jsonb)) AS x(
             key text,evidence text,details jsonb)
         )
         INSERT INTO public.ld_opportunities(workspace_id,lead_id,status,evidence_summary,service_details)
         SELECT :ws,l.id,'research_needed',NULLIF(src.evidence,''),
              COALESCE(src.details,'{}'::jsonb) ||
                jsonb_build_object('_letterdesk_import_batch',:batch)
         FROM src JOIN public.ld_leads l ON l.team_id=:team AND l.dedupe_key=src.key
         ON CONFLICT(workspace_id,lead_id) DO NOTHING"""),{
          "input":json.dumps(packed),"ws":workspace,"team":team,"batch":batch
        })

        # Existing conversations are never overridden or marked unsent again.
        # An initial message is created ONLY for a newly created contact, and
        # ONLY when it has a known recipient email and no previous conversation.
        db.execute(text("""WITH src AS (
          SELECT * FROM jsonb_to_recordset(CAST(:input AS jsonb))
             AS x(key text,email text,body text,disposition text)
        )
        INSERT INTO public.ld_conversations(opportunity_id,status,message_count)
        SELECT o.id,'draft',0
        FROM src JOIN public.ld_leads l ON l.team_id=:team AND l.dedupe_key=src.key
        JOIN public.ld_opportunities o ON o.workspace_id=:ws AND o.lead_id=l.id
        WHERE src.disposition='created' AND src.email IS NOT NULL
          AND COALESCE(src.body,'')<>'' AND NOT EXISTS(
            SELECT 1 FROM public.ld_conversations prior WHERE prior.opportunity_id=o.id)"""),
            {"input":json.dumps(packed),"ws":workspace,"team":team,"batch":batch})

        db.execute(text("""WITH src AS (
          SELECT * FROM jsonb_to_recordset(CAST(:input AS jsonb))
             AS x(key text,email text,subject text,body text,english text,disposition text)
        )
        INSERT INTO public.ld_message_records(conversation_id,recipient_email,subject,
                  body,body_english,status,raw_metadata)
        SELECT c.id,src.email,src.subject,src.body,src.english,'needs_review',
          jsonb_build_object('import_batch',:batch,'source','file_import')
        FROM src JOIN public.ld_leads l ON l.team_id=:team AND l.dedupe_key=src.key
        JOIN public.ld_opportunities o ON o.workspace_id=:ws AND o.lead_id=l.id
        JOIN public.ld_conversations c ON c.opportunity_id=o.id
        WHERE src.disposition='created' AND src.email IS NOT NULL
          AND COALESCE(src.body,'')<>'' AND NOT EXISTS(
            SELECT 1 FROM public.ld_message_records prior WHERE prior.conversation_id=c.id)"""),
            {"input":json.dumps(packed),"batch":batch,"ws":workspace,"team":team})

        db.execute(text("""WITH src AS (
            SELECT * FROM jsonb_to_recordset(CAST(:meta AS jsonb))
            AS x(row int,key text,disposition text,reason text,branches jsonb,message boolean)
          )
          INSERT INTO public.ld_import_rows(batch_id,row_number,service_key,
            disposition,identity_key,lead_id,opportunity_id,had_first_message,branch_templates,reason)
          SELECT CAST(:batch AS uuid),src.row,:service,src.disposition,src.key,l.id,o.id,
                 src.message,COALESCE(src.branches,'{}'::jsonb),NULLIF(src.reason,'')
          FROM src LEFT JOIN public.ld_leads l ON l.team_id=:team AND l.dedupe_key=src.key
          LEFT JOIN public.ld_opportunities o ON o.workspace_id=:ws AND o.lead_id=l.id
          ON CONFLICT(batch_id,row_number) DO NOTHING"""),{
             "meta":json.dumps(meta),"batch":batch,"service":service,"ws":workspace,"team":team
        })
        # File explicitly marked opt-out contacts become globally suppressed.
        suppression=sorted(set(r["email"] for r in rows
                    if r["disposition"]=="suppressed" and r["do_not_contact"] and r["email"]))
        if suppression:
            db.execute(text("""INSERT INTO public.ld_suppressions(team_id,normalized_email,reason,source)
             SELECT :team,value,'manual','file import '||:batch
             FROM jsonb_array_elements_text(CAST(:emails AS jsonb)) AS value
             ON CONFLICT(team_id,normalized_email) DO NOTHING"""),{
                "team":team,"batch":batch,"emails":json.dumps(suppression)
            })
        # All rows and resulting drafts are committed or rolled back together.
        return batch
