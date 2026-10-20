"""Letter Desk 2.0 read-only six-service API.

Reuses the Author Scout web-session authenticator and SQLAlchemy engine.
Does not request Gmail scopes, create outreach jobs, or run any sends.
Deploy only after the ld_* Neon migration has been applied.
"""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, FastAPI, HTTPException, Request
from sqlalchemy import Engine, text
from letterdesk_language import language_recommendation

SERVICE_KEYS = (
    "author", "automation", "website-design",
    "digital-planner", "shopify", "google-maps"
)


def install_letterdesk_v2_routes(
    app: FastAPI,
    engine: Engine,
    authenticate_web_session: Callable[[Request], dict],
) -> None:
    router = APIRouter(prefix="/api/v2/letterdesk", tags=["Letter Desk 2"])

    def team_id_for(request: Request) -> int:
        context = authenticate_web_session(request)
        team_id = int(context.get("team_id") or 0)
        if team_id <= 0:
            raise HTTPException(status_code=403, detail="A linked team is required.")
        return team_id

    def rows(sql: str, **params) -> list[dict]:
        with engine.connect() as connection:
            result = connection.execute(text(sql), params)
            return [dict(row._mapping) for row in result]

    def first(sql: str, **params) -> dict:
        found = rows(sql, **params)
        return found[0] if found else {}

    @router.get("/services")
    def list_service_workspaces(request: Request):
        """Return only the authenticated team's service workspaces and real metrics."""
        team = team_id_for(request)
        services = rows(
            """
            SELECT w.service_key, w.display_name, CAST(w.id AS TEXT) AS workspace_id,
                   COUNT(DISTINCT o.id) AS prospect_count,
                   COUNT(DISTINCT r.id) FILTER (WHERE r.status='needs_review') AS draft_count,
                   COUNT(DISTINCT r.id) FILTER (WHERE r.status='sent') AS sent_count,
                   COUNT(DISTINCT c.id) FILTER (WHERE c.status='awaiting_reply') AS awaiting_reply_count
            FROM public.ld_service_workspaces w
            LEFT JOIN public.ld_opportunities o ON o.workspace_id=w.id
            LEFT JOIN public.ld_conversations c ON c.opportunity_id=o.id
            LEFT JOIN public.ld_message_records r ON r.conversation_id=c.id
            WHERE w.team_id=:team AND w.is_active=true
            GROUP BY w.service_key,w.display_name,w.id
            ORDER BY CASE w.service_key
                WHEN 'author' THEN 1 WHEN 'automation' THEN 2
                WHEN 'website-design' THEN 3 WHEN 'digital-planner' THEN 4
                WHEN 'shopify' THEN 5 WHEN 'google-maps' THEN 6 ELSE 7 END
            """,
            team=team,
        )
        for service in services:
            for column in ("prospect_count", "draft_count", "sent_count", "awaiting_reply_count"):
                service[column] = int(service[column] or 0)
        return {"ok": True, "services": services}

    @router.get("/services/{service_key}/leads")
    def service_leads(request: Request, service_key: str, search: str = "", limit: int = 50, offset: int = 0):
        """Paginated evidence-bearing prospects, isolated by service AND team."""
        team = team_id_for(request)
        if service_key not in SERVICE_KEYS:
            raise HTTPException(status_code=404, detail="Unknown service workspace")
        limit = min(100, max(1, int(limit)))
        offset = min(100_000, max(0, int(offset)))
        query = search.strip().lower()[:120]
        params = {
            "team": team, "service_key": service_key, "query": query,
            "search_pattern": "%" + query + "%", "limit": limit, "offset": offset
        }
        condition = """
            FROM public.ld_opportunities o
            JOIN public.ld_service_workspaces w ON w.id=o.workspace_id
            JOIN public.ld_leads l ON l.id=o.lead_id AND l.team_id=w.team_id
            WHERE w.team_id=:team AND w.service_key=:service_key AND w.is_active=true
              AND (:query='' OR LOWER(l.name) LIKE :search_pattern
                             OR LOWER(COALESCE(l.email,'')) LIKE :search_pattern
                             OR LOWER(COALESCE(l.website,'')) LIKE :search_pattern)
        """
        total = first("SELECT COUNT(*) AS count " + condition, **params).get("count", 0)
        leads = rows(
            """
            SELECT CAST(l.id AS TEXT) AS lead_id, CAST(o.id AS TEXT) AS opportunity_id,
                   l.name, l.kind, l.email, l.website, l.maps_url, l.country, l.city,
                   l.source_url, l.contact_verification, o.status, o.fit_score,
                   o.evidence_summary, CAST(o.created_at AS TEXT) AS created_at
            """ + condition +
            " ORDER BY o.created_at DESC, l.name ASC LIMIT :limit OFFSET :offset",
            **params,
        )
        return {
            "ok": True, "service_key": service_key,
            "leads": leads, "total": int(total or 0),
            "limit": limit, "offset": offset,
        }

    @router.get("/services/{service_key}/attention")
    def attention_queue(request:Request,service_key:str):
        team=team_id_for(request)
        if service_key not in SERVICE_KEYS:raise HTTPException(404,"Unknown service")
        params={"team":team,"service":service_key}
        context=""" FROM public.ld_service_workspaces w
                     WHERE w.team_id=:team AND w.service_key=:service
                       AND w.is_active=true"""
        replied=first("""SELECT COUNT(*) AS count FROM public.ld_reply_inbox r
           JOIN public.ld_service_workspaces w ON w.id=r.workspace_id
           WHERE w.team_id=:team AND w.service_key=:service
             AND r.status='pending_review'""",**params).get("count",0)
        drafts=first("""SELECT COUNT(*) AS count FROM public.ld_message_records m
           JOIN public.ld_conversations c ON c.id=m.conversation_id
           JOIN public.ld_opportunities o ON o.id=c.opportunity_id
           JOIN public.ld_service_workspaces w ON w.id=o.workspace_id
           WHERE w.team_id=:team AND w.service_key=:service AND m.status='needs_review'""",**params).get("count",0)
        missing=first("""SELECT COUNT(*) AS count FROM public.ld_opportunities o
           JOIN public.ld_service_workspaces w ON w.id=o.workspace_id
           WHERE w.team_id=:team AND w.service_key=:service
           AND COALESCE(TRIM(o.evidence_summary),'')=''
           AND NOT EXISTS(SELECT 1 FROM public.ld_evidence e WHERE e.opportunity_id=o.id)""",**params).get("count",0)
        conflicts=first("""SELECT COUNT(*) AS count FROM public.ld_import_rows ir
           JOIN public.ld_import_batches b ON b.id=ir.batch_id
           JOIN public.ld_service_workspaces w ON w.id=b.workspace_id
           WHERE w.team_id=:team AND w.service_key=:service
             AND ir.disposition='review_required'""",**params).get("count",0)
        return {"ok":True,"items":[
            {"code":"replies","label":"Replies awaiting a decision","count":int(replied or 0),"screen":"inbox"},
            {"code":"drafts","label":"Message drafts awaiting approval","count":int(drafts or 0),"screen":"campaigns"},
            {"code":"evidence","label":"Prospects needing source-backed research","count":int(missing or 0),"screen":"prospects"},
            {"code":"conflicts","label":"Uploaded records with differences to review","count":int(conflicts or 0),"screen":"imports"},
        ]}
    
    @router.get("/services/{service_key}/leads/{opportunity_id}")
    def prospect_profile(request: Request, service_key: str, opportunity_id: __import__("uuid").UUID):
        """Private, one-contact read model: evidence, messages and import history."""
        team=team_id_for(request)
        if service_key not in SERVICE_KEYS:
            raise HTTPException(404,"Unknown service")
        params={"team":team,"service":service_key,"id":opportunity_id}
        opp=first("""
            SELECT CAST(o.id AS TEXT) AS id,o.status,o.evidence_summary,
                   o.service_details,o.fit_score,
                   CAST(o.created_at AS TEXT) AS created_at,
                   CAST(l.id AS TEXT) AS lead_id,l.name,l.email,l.website,l.maps_url,
                   l.kind,l.country,l.city,l.source_url,l.contact_verification,l.details
            FROM public.ld_opportunities o
            JOIN public.ld_service_workspaces w ON w.id=o.workspace_id
            JOIN public.ld_leads l ON l.id=o.lead_id AND l.team_id=w.team_id
            WHERE o.id=:id AND w.team_id=:team AND w.service_key=:service
                AND w.is_active=true""",**params)
        if not opp:raise HTTPException(404,"Prospect not found in your service")
        lead={x:opp[x] for x in ("lead_id","name","email","website","maps_url","kind",
                                 "country","city","source_url","contact_verification","details")}
        evidence=rows("""
            SELECT CAST(e.id AS TEXT) AS id,e.observation,e.source_url,e.confidence,
                   CAST(e.collected_at AS TEXT) AS collected_at
            FROM public.ld_evidence e WHERE e.opportunity_id=:id
               OR (e.lead_id=CAST(:lead_id AS uuid) AND e.opportunity_id IS NULL)
            ORDER BY e.collected_at DESC LIMIT 100
        """,id=opportunity_id,lead_id=opp["lead_id"])
        messages=rows("""
            SELECT CAST(m.id AS TEXT) AS id,m.subject,m.body,m.body_english,
                   m.status,m.sender_email,m.recipient_email,
                   CAST(m.created_at AS TEXT) AS created_at,
                   CAST(m.sent_at_original AS TEXT) AS sent_at
            FROM public.ld_message_records m
            JOIN public.ld_conversations c ON c.id=m.conversation_id
            WHERE c.opportunity_id=:id ORDER BY m.created_at DESC LIMIT 100
        """,id=opportunity_id)
        imports=rows("""
            SELECT CAST(ir.id AS TEXT) AS id,ir.row_number,ir.disposition,ir.reason,
                   b.filename,CAST(ir.created_at AS TEXT) AS created_at
            FROM public.ld_import_rows ir
            JOIN public.ld_import_batches b ON b.id=ir.batch_id
            JOIN public.ld_service_workspaces w ON w.id=b.workspace_id
            WHERE ir.opportunity_id=:id AND w.team_id=:team AND w.service_key=:service
            ORDER BY ir.created_at DESC LIMIT 100
        """,**params)
        stored=(opp.get("service_details") or {})
        nested=(lead.get("details") or {})
        if isinstance(nested,dict):
            nested=nested.get("details") or {}
        else:nested={}
        language=language_recommendation(lead.get("country"),
            stored.get("preferred_language") or nested.get("preferred_language") or "",
            stored.get("evidence_language") or nested.get("evidence_language") or "")
        suppressed=bool(first("""SELECT 1 AS blocked FROM public.ld_suppressions
            WHERE team_id=:team AND normalized_email=lower(:email) LIMIT 1""",
            team=team,email=opp.get("email") or "").get("blocked"))
        return {"ok":True,"lead":lead,"opportunity":{
            "id":opp["id"],"status":opp["status"],"evidence_summary":opp["evidence_summary"],
            "service_details":opp["service_details"],"fit_score":opp["fit_score"]},
            "suppressed":suppressed,"language":language,"evidence":evidence,"messages":messages,"imports":imports}

    app.include_router(router)
