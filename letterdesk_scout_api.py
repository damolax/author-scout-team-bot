"""Letter Desk Phase 3 — authenticated service-specific discovery endpoints.

- GET queries and jobs work in read-only staging.
- POST job creation/execution explicitly requires LETTERDESK_SCOUT_WRITE_ENABLED=true.
- Delivers queued research records, never an email queue or send operation.
- Provider fetch failures are recorded; no invented emails or verified-need claims.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, FastAPI, HTTPException, Request
from sqlalchemy import text
from letterdesk_discovery import (
    SERVICE_DEFINITIONS, build_queries, search_public_web, inspect_website,
    normalized_public_url, website_identity, search_google_places,
)
from typing import Callable

SCOUT_JOB_LIMIT_PER_TEAM_PER_DAY = 8


def install_scouting_api(app: FastAPI, engine, authenticate_web_session: Callable):
    router=APIRouter(prefix="/api/v2/letterdesk",tags=["Letter Desk discovery"])
    def ctx(request):
        auth=authenticate_web_session(request)
        tid=int(auth.get("team_id") or 0)
        if tid<=0: raise HTTPException(status_code=403,detail="Linked workspace required")
        return tid

    def workspace(team_id,service):
        if service not in SERVICE_DEFINITIONS: raise HTTPException(status_code=404, detail="Service does not exist")
        with engine.connect() as conn:
            row=conn.execute(text("""SELECT id::text AS id,service_key FROM public.ld_service_workspaces
               WHERE team_id=:team AND service_key=:service AND is_active=true LIMIT 1"""),
               {"team":team_id,"service":service}).mappings().first()
        if row is None: raise HTTPException(status_code=404,detail="Workspace unavailable")
        return dict(row)

    def writer_enabled():
        if os.getenv("LETTERDESK_SCOUT_WRITE_ENABLED", "false").strip().lower() not in {"true","1","yes"}:
            raise HTTPException(status_code=403,detail="Scouting execution is not enabled on this preview")

    def clean_text(value,max_len=140):
        return re.sub(r"\s+"," ",str(value or "").replace("\x00"," ")).strip()[:max_len]

    def job_public(r):
        result=dict(r)
        for field in ("id","workspace_id"):
            if field in result: result[field]=str(result[field])
        for field in ("created_at","started_at","completed_at"):
            if isinstance(result.get(field),datetime): result[field]=result[field].isoformat()
        return result

    @router.get("/services/{service_key}/scout/plan")
    def scout_plan(request: Request,service_key: str,niche: str="",city: str="",country: str="", signals: str=""):
        team=ctx(request)
        workspace(team,service_key)
        clean_signals=[clean_text(s,45) for s in signals.split(",") if s.strip()][:4]
        definition=SERVICE_DEFINITIONS[service_key]
        return {
            "ok":True,"service_key":service_key,
            "queries":build_queries(service_key,niche,city,country,clean_signals),
            "observable_signals":definition["signals"],
            "notes":[
                "These are suggested search queries, not confirmed opportunities.",
                "Emails are only added when visible on an official public website.",
                "Scouting never automatically approves an outreach message.",
            ],
            "maps_provider": "google_places_new" if service_key=="google-maps" else "public_web",
            "can_run":os.getenv("LETTERDESK_SCOUT_WRITE_ENABLED","false").lower() in ("true","1","yes"),
        }

    @router.get("/services/{service_key}/scout/jobs")
    def scout_jobs(request: Request, service_key: str, limit: int=25):
        team=ctx(request)
        ws=workspace(team,service_key)
        with engine.connect() as db:
            rows=db.execute(text("""SELECT id,workspace_id,status,mode,niche,city,country,query_plan,
                max_queries,max_results,max_sites,queries_run,pages_scanned,leads_created,
                leads_linked,rejected_results,error,created_at,started_at,completed_at
                FROM public.ld_discovery_jobs WHERE workspace_id=CAST(:wid AS uuid)
                ORDER BY created_at DESC LIMIT :limit"""),{"wid":ws["id"],"limit":max(1,min(limit,40))}).mappings().all()
        return {"ok":True,"service_key":service_key,"jobs":[job_public(r) for r in rows]}

    @router.post("/services/{service_key}/scout/jobs")
    async def create_job(request: Request,service_key: str):
        team=ctx(request)
        writer_enabled()
        ws=workspace(team,service_key)
        body=await request.json()
        if not isinstance(body,dict): raise HTTPException(400,"Invalid job input")
        niche=clean_text(body.get("niche"),65)
        city=clean_text(body.get("city"),80)
        country=clean_text(body.get("country"),80)
        signals=[clean_text(v,45) for v in (body.get("signals") or [])[:4] if isinstance(v,str)] if isinstance(body.get("signals") or [],list) else []
        start_urls=[]
        for value in (body.get("start_urls") or [])[:4] if isinstance(body.get("start_urls") or [],list) else []:
            try:
                start_urls.append(normalized_public_url(value,resolve_dns=False))
            except ValueError: raise HTTPException(400,"Seed URLs must be public business websites")
        if not niche and not start_urls:
            raise HTTPException(400,"Enter a niche, business category, or public starting URL")
        if service_key=="google-maps" and not (city or country):
            raise HTTPException(400,"Google Maps searches require a city or country")
        mode="maps" if service_key=="google-maps" else "seed" if start_urls and not niche else "web"
        if mode=="maps" and not os.getenv("GOOGLE_PLACES_API_KEY",""):
            raise HTTPException(503,"Google Places API (New) is not configured; connect a key before running Maps scouting")
        plan=build_queries(service_key,niche,city,country,signals)
        # Per-team cap is checked under an advisory lock to avoid concurrent over-creation.
        with engine.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(:team)"),{"team":int(team)})
            n=db.execute(text("""SELECT COUNT(*) FROM public.ld_discovery_jobs j
                JOIN public.ld_service_workspaces w ON w.id=j.workspace_id
                WHERE w.team_id=:team AND j.created_at >= CURRENT_DATE"""),{"team":team}).scalar_one()
            if int(n)>=SCOUT_JOB_LIMIT_PER_TEAM_PER_DAY: raise HTTPException(429,"Daily discovery-job limit reached")
            n=db.execute(text("""SELECT COUNT(*) FROM public.ld_discovery_jobs j
                JOIN public.ld_service_workspaces w ON w.id=j.workspace_id
                WHERE w.team_id=:team AND j.status IN ('running','queued')"""),{"team":team}).scalar_one()
            if int(n)>=3: raise HTTPException(429,"Finish or cancel existing scouting jobs before adding more")
            jid=db.execute(text("""INSERT INTO public.ld_discovery_jobs(
                workspace_id,requested_by,mode,niche,city,country,start_urls,extra_signals,
                query_plan,max_queries,max_results,max_sites
            ) VALUES (CAST(:ws AS uuid),:actor,:mode,:niche,:city,:country,CAST(:urls AS jsonb),
                     CAST(:signals AS jsonb),CAST(:plan AS jsonb),:max_queries,:max_results,:max_sites)
                RETURNING id::text"""),{
                "ws":ws["id"],"actor":str(request.headers.get("x-request-id") or "web")[:60],
                "mode":mode,"niche":niche,"city":city,"country":country,
                "urls":json.dumps(start_urls),"signals":json.dumps(signals),
                "plan":json.dumps(plan),"max_queries":max(0,min(int(body.get("max_queries") or 2),4)),
                "max_results":max(1,min(int(body.get("max_results") or 6),15)),
                "max_sites":max(1,min(int(body.get("max_sites") or 8),20)),
            }).scalar_one()
        return {"ok":True,"job_id":jid,"status":"queued","note":"Job has been queued for evidence discovery; no emails will be sent."}

    @router.get("/services/{service_key}/scout/jobs/{job_id}/results")
    def results(request: Request,service_key: str,job_id: uuid.UUID,limit: int=80):
        team=ctx(request)
        ws=workspace(team,service_key)
        with engine.connect() as db:
            result=db.execute(text("""SELECT r.id::text AS id,r.lead_id::text AS lead_id,
                    r.source_url,r.name,r.email,r.evidence_text,r.email_source_url,r.evidence_type,r.status,r.reason,
                    r.collected_at
                    FROM public.ld_discovery_results r
                    WHERE r.workspace_id=CAST(:w AS uuid) AND r.job_id=:job
                    ORDER BY r.collected_at DESC LIMIT :lim"""),{"w":ws["id"],"job":job_id,"lim":max(1,min(int(limit),100))}).mappings().all()
        return {"ok":True,"results":[job_public(row) for row in result]}

    @router.post("/services/{service_key}/scout/jobs/{job_id}/run")
    def run_job(request: Request,service_key: str,job_id: uuid.UUID):
        team=ctx(request)
        writer_enabled()
        ws=workspace(team,service_key)
        # Claim once via conditional UPDATE; another request cannot process the same job.
        with engine.begin() as db:
            job=db.execute(text("""UPDATE public.ld_discovery_jobs
                SET status='running',started_at=now()
                WHERE id=:id AND workspace_id=CAST(:w AS uuid) AND status='queued'
                RETURNING *"""),{"id":job_id,"w":ws["id"]}).mappings().first()
        if not job: raise HTTPException(409,"Job not queued, or it belongs to another workspace")
        try:
            report=_execute_job(engine,dict(job),ws["id"],team,service_key)
            with engine.begin() as db:
                db.execute(text("""UPDATE public.ld_discovery_jobs
                    SET status='completed',completed_at=now(),queries_run=:queries,pages_scanned=:pages,
                        leads_created=:created,leads_linked=:linked,rejected_results=:rejected,
                        notes=CAST(:notes AS jsonb) WHERE id=:id"""),{**report,"id":job_id,"notes":json.dumps(report["notes"][:20])})
            return {"ok":True,"status":"completed","job_id":str(job_id),**report}
        except Exception as e:
            # No raw URLs, page text, credentials or exception details in client responses.
            with engine.begin() as db:
                db.execute(text("""UPDATE public.ld_discovery_jobs SET status='failed',completed_at=now(),
                    error=:err WHERE id=:id"""),{"id":job_id,"err":type(e).__name__+": scout could not complete"})
            raise HTTPException(502,"This scouting job could not complete. Please review its status and try a new job.")

    app.include_router(router)


def _execute_job(engine,job: dict,workspace_id: str,team_id: int,service_key: str) -> dict:
    q=list(job["query_plan"] or [])[:int(job["max_queries"])]
    notes=[]
    targets=[]
    if job["mode"]=="maps":
        key=os.getenv("GOOGLE_PLACES_API_KEY","")
        query=" ".join(x for x in (job["niche"],job["city"],job["country"]) if x)
        listings=search_google_places(query,key,max_results=min(10,int(job["max_results"])))
        targets=[{"url":x["website"] or x["maps_url"],"title":x["name"],
                  "maps_listing":x,"search_query":query} for x in listings if x["website"] or x["maps_url"]]
        q=[query]
    else:
        targets,search_errors=search_public_web(q,max_results=int(job["max_results"])) if q else ([],[])
        notes.extend(search_errors)
    for url in job.get("start_urls") or []:
        targets.insert(0,{"url":url,"title":"","search_query":"user_supplied_seed"})
    visited=set()
    counts={"queries":len(q),"pages":0,"created":0,"linked":0,"rejected":0,"notes":notes}
    for item in targets:
        if counts["pages"] >= int(job["max_sites"]):break
        listing=item.get("maps_listing") or {}
        site=listing.get("website") or item.get("url") or ""
        try:
            normalized=normalized_public_url(site,resolve_dns=False)
            urlhost=urlparse(normalized).hostname
        except ValueError:
            # Listing without website can still be saved as a lead with its Place ID.
            if listing.get("place_id"):
                normalized=listing.get("maps_url") or "https://maps.google.com/"
                urlhost=""
            else:
                counts["rejected"]+=1
                continue
        identity = listing.get("place_id") if listing else urlhost
        if identity in visited:continue
        visited.add(identity)
        counts["pages"]+=1
        try:
            page=inspect_website(site,max_pages=3) if urlhost else {
                "name":listing.get("name") or "Local Business",
                "website":"","email_candidates":[],"evidence":[],"pages":[]
            }
        except (ValueError,httpx.RequestError) as e:
            # A bad site is a research result, not a verified contact.
            counts["rejected"]+=1
            counts["notes"].append("Blocked or unreachable site: "+type(e).__name__)
            continue
        name=(listing.get("name") or page.get("name") or item.get("title") or "").strip()[:120]
        email_candidate=(page.get("email_candidates") or [{}])[0]
        email=email_candidate.get("email") or ""
        source=email_candidate.get("source_url") or page.get("website") or listing.get("maps_url") or normalized
        has_fetched=any(p.get("status")=="fetched" for p in page.get("pages",[]))
        if not has_fetched and not listing.get("place_id"):
            counts["rejected"]+=1
            continue
        if not name:
            name=urlhost or "Uncategorized local business"
        dedupe=("maps:"+listing["place_id"]) if listing.get("place_id") else website_identity(page["website"],email,name,service_key)
        details={
            "discovered_via":"scout_search","search_query":item.get("search_query") or "",
            "search_snippet":item.get("snippet") or "",
            "email_candidates":page.get("email_candidates") or [],
            "source_pages":page.get("pages") or [],
            "observations":page.get("evidence") or [],
            "place_id":listing.get("place_id") or "",
            "maps_url":listing.get("maps_url") or "",
            "address":listing.get("address") or "",
            "category":listing.get("category") or "",
        }
        with engine.begin() as db:
            row=db.execute(text("""INSERT INTO public.ld_leads(
                team_id,dedupe_key,name,kind,email,website,maps_url,city,country,source_url,
                contact_verification,details
            ) VALUES (:team,:key,:name,:kind,:email,:website,:maps,:city,:country,:source,
                'publicly_observed_unverified',CAST(:details AS jsonb))
              ON CONFLICT(team_id,dedupe_key) DO NOTHING RETURNING id"""),{
                "team":team_id,"key":dedupe,"name":name,"kind":"person" if service_key=="author" else "business",
                "email":email or None,"website":page.get("website") or None,"maps":listing.get("maps_url") or None,
                "city":job["city"] or None,"country":job["country"] or None,
                "source":source,"details":json.dumps(details),
            }).scalar_one_or_none()
            created=row is not None
            if not row:
                row=db.execute(text("""SELECT id FROM public.ld_leads
                    WHERE team_id=:team AND dedupe_key=:key LIMIT 1"""),{"team":team_id,"key":dedupe}).scalar_one()
            opp=db.execute(text("""INSERT INTO public.ld_opportunities(workspace_id,lead_id,status,
                    evidence_summary,service_details)
                VALUES(CAST(:ws AS uuid),:lead,'research_needed',:summary,CAST(:detail AS jsonb))
                ON CONFLICT(workspace_id,lead_id) DO NOTHING RETURNING id"""),{
                    "ws":workspace_id,"lead":row,
                    "summary":"Official public site observed; contact and service fit require review",
                    "detail":json.dumps({"scouting_job":str(job["id"]),"service_key":service_key})
                }).scalar_one_or_none()
            if not opp:
                opp=db.execute(text("""SELECT id FROM public.ld_opportunities
                    WHERE workspace_id=CAST(:ws AS uuid) AND lead_id=:lead LIMIT 1"""),{
                    "ws":workspace_id,"lead":row}).scalar_one()
            evidence_url=source
            db.execute(text("""INSERT INTO public.ld_evidence(
                lead_id,opportunity_id,source_url,observation,confidence)
                VALUES (:lead,:opp,:url,:observation,'unconfirmed')"""),{
                "lead":row,"opp":opp,"url":evidence_url,
                "observation":f"Source reviewed in job {job['id']}; public contact candidate found={bool(email)}"
            })
            db.execute(text("""INSERT INTO public.ld_discovery_results(job_id,workspace_id,lead_id,
                source_url,normalized_url,name,email,evidence_text,email_source_url,evidence_type,status,reason)
                VALUES (:job,CAST(:ws AS uuid),:lead,:src,:url,:name,:email,:evidence,:email_src,
                    :method,:status,:reason)
                ON CONFLICT(job_id,normalized_url) DO NOTHING"""),{
                    "job":job["id"],"ws":workspace_id,"lead":row,"src":source,"url":normalized,
                    "name":name,"email":email or None,
                    "evidence":(page.get("evidence") or [{}])[0].get("excerpt","")[:500],
                    "email_src":email_candidate.get("source_url") or None,
                    "method":email_candidate.get("method") or "public_page",
                    "status":"lead_created" if created else "existing_lead",
                    "reason":"Published contact candidate; delivery not verified" if email else "No public email found",
                })
        counts["created" if created else "linked"]+=1
    return counts
