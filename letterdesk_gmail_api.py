"""Letter Desk Phase 6: OAuth Gmail connections and Google-verified sender identities.

Does NOT send email. Uses Gmail send scope for primary address, and optionally
the *restricted* gmail.settings.basic scope for verified Send as aliases.
OAuth is disabled unless explicitly configured for the isolated staging host.
Refresh tokens are encrypted at rest using a separate Fernet encryption key.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import text

AUTH_URL="https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL="https://oauth2.googleapis.com/token"
USERINFO_URL="https://openidconnect.googleapis.com/v1/userinfo"
SEND_AS_URL="https://gmail.googleapis.com/gmail/v1/users/me/settings/sendAs"
BASIC_SCOPES=("openid","email","https://www.googleapis.com/auth/gmail.send")
ALIAS_SCOPE="https://www.googleapis.com/auth/gmail.settings.basic"
EMAIL_RE=re.compile(r"^[^@\s<>;,]{1,80}@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}$")
ALLOWED_REDIRECT_HOSTS=(".onrender.com",)
MAX_CONNECTIONS_PER_TEAM=120

def enabled():
    return os.getenv("LETTERDESK_GMAIL_OAUTH_ENABLED","false").strip().lower() in ("true","1","yes")

def sender_crypto():
    key=os.getenv("TOKEN_ENCRYPTION_KEY") or ""
    try:return Fernet(key.encode())
    except Exception:raise HTTPException(503,"A valid server-side token encryption key is required")

def google_config():
    cid=os.getenv("GOOGLE_CLIENT_ID") or ""
    secret=os.getenv("GOOGLE_CLIENT_SECRET") or ""
    redirect=os.getenv("LETTERDESK_GMAIL_REDIRECT_URI") or ""
    frontend=(os.getenv("LETTERDESK_STAGING_FRONTEND_ORIGIN") or "").rstrip("/")
    from urllib.parse import urlparse
    uri=urlparse(redirect)
    if not (cid and secret and uri.scheme=="https" and uri.path=="/api/v2/letterdesk/gmail/callback"
            and uri.hostname and uri.hostname.endswith(ALLOWED_REDIRECT_HOSTS)):
        raise HTTPException(503,"Staging Gmail OAuth credentials/redirect URI are not configured correctly")
    if not frontend.startswith("https://") or not frontend.endswith(".onrender.com"):
        raise HTTPException(503,"Staging web redirect is not configured")
    return cid,secret,redirect,frontend

def hash_state(value):
    return hashlib.sha256(value.encode()).hexdigest()

def build_authorization_url(client_id,redirect,state,with_aliases=False):
    scopes=BASIC_SCOPES+((ALIAS_SCOPE,) if with_aliases else ())
    return AUTH_URL+"?"+urlencode({
        "client_id":client_id,
        "redirect_uri":redirect,
        "response_type":"code",
        "access_type":"offline",
        "prompt":"consent select_account",
        "scope":" ".join(scopes),
        "state":state,
        "include_granted_scopes":"true",
    })

def normalize_email(email):
    value=str(email or "").strip().lower()
    if not EMAIL_RE.fullmatch(value) or len(value)>254:
        raise ValueError("Enter a valid Gmail address")
    return value

def alias_candidates(primary_email,send_as_data,scope_present=False):
    primary=normalize_email(primary_email)
    candidates=[{"email":primary,"verified":True,"source":"google_primary","name":""}]
    if not scope_present or not isinstance(send_as_data,dict):return candidates
    seen={primary}
    for record in (send_as_data.get("sendAs") or [])[:200]:
        try:email=normalize_email(record.get("sendAsEmail"))
        except ValueError:continue
        if email in seen:continue
        seen.add(email)
        accepted=(record.get("verificationStatus")=="accepted")
        candidates.append({
            "email":email,"verified":bool(accepted),
            "source":"gmail_send_as","name":str(record.get("displayName") or "")[:100],
        })
    return candidates

async def exchange_code(code,cid,secret,redirect):
    async with httpx.AsyncClient(timeout=25.0,trust_env=True) as client:
        result=await client.post(TOKEN_URL,data={
            "code":code,"client_id":cid,"client_secret":secret,
            "redirect_uri":redirect,"grant_type":"authorization_code",
        })
        if result.status_code!=200:
            raise HTTPException(400,"Google rejected authorization. Please connect again.")
        return result.json()

async def fetch_google_profile(access_token):
    async with httpx.AsyncClient(timeout=20) as client:
        response=await client.get(USERINFO_URL,headers={"Authorization":f"Bearer {access_token}"})
        if response.status_code!=200:
            raise HTTPException(400,"Google account could not be verified")
        user=response.json()
        if not user.get("email_verified") or not user.get("sub"):
            raise HTTPException(400,"Google email address is not verified")
        try:user["email"]=normalize_email(user["email"])
        except (ValueError,KeyError):raise HTTPException(400,"Google returned an invalid Gmail address")
        return user

async def fetch_google_aliases(access_token):
    async with httpx.AsyncClient(timeout=20) as client:
        response=await client.get(SEND_AS_URL,headers={"Authorization":f"Bearer {access_token}"})
        if response.status_code!=200:
            raise HTTPException(502,"Google did not provide Send as verification. Please reconnect with the required permission.")
        return response.json()

def install_gmail_connection_api(app:FastAPI,engine,authenticate):
    router=APIRouter(prefix="/api/v2/letterdesk/gmail",tags=["Letter Desk Gmail connections"])

    def context(request):
        result=authenticate(request)
        team=int(result.get("team_id") or 0)
        account=int(result.get("account_id") or 0)
        if team<=0 or account<=0:raise HTTPException(403,"A linked web account is required")
        return team,account

    def ensure_enabled():
        if not enabled():raise HTTPException(403,"Gmail connections are disabled in this staging preview")

    @router.get("/connections")
    def list_connections(request:Request):
        team,account=context(request)
        with engine.connect() as db:
            rs=db.execute(text("""SELECT c.id::text AS id,c.primary_email,c.status,c.scopes,
                    c.created_at::text AS created_at,c.updated_at::text AS updated_at,
                    c.web_account_id,
                    (SELECT count(*) FROM public.ld_gmail_sender_identities s
                     WHERE s.connection_id=c.id AND s.verification_status='verified') AS verified_senders
                FROM public.ld_gmail_connections c WHERE c.team_id=:team
                ORDER BY c.updated_at DESC LIMIT 130"""),{"team":team}).mappings().all()
        return {"ok":True,"connections":[{
            "id":r["id"],"email":r["primary_email"],"status":r["status"],
            "alias_access":ALIAS_SCOPE in (r["scopes"] or []),
            "owner_is_you":int(r["web_account_id"])==account,
            "verified_senders":int(r["verified_senders"] or 0),
        } for r in rs],"oauth_enabled":enabled()}

    @router.post("/connect")
    async def connect(request:Request):
        team,account=context(request)
        ensure_enabled()
        cid,_,redirect,frontend=google_config()
        body=await request.json()
        aliases=bool(body.get("requestAliasVerification",False)) if isinstance(body,dict) else False
        nonce=secrets.token_urlsafe(32)
        with engine.begin() as db:
            count=db.execute(text("""SELECT count(*) FROM public.ld_gmail_connections
                WHERE team_id=:team AND status='connected'"""),{"team":team}).scalar_one()
            if count>=MAX_CONNECTIONS_PER_TEAM:raise HTTPException(429,"Gmail connection limit reached")
            db.execute(text("""INSERT INTO public.ld_gmail_oauth_states
                (team_id,web_account_id,nonce_sha256,requested_scope)
                VALUES(:team,:account,:hash,:scope)"""),{
                    "team":team,"account":account,"hash":hash_state(nonce),
                    "scope":"with_aliases" if aliases else "gmail_send_only"})
        return {"ok":True,"authorization_url":build_authorization_url(cid,redirect,nonce,aliases),
                "permissions":"gmail.send + email" + (" + gmail.settings.basic" if aliases else ""),
                "note":"Connecting a Gmail account does not approve or send any campaign."}

    @router.get("/callback")
    async def callback(request:Request,code:str="",state:str="",error:str=""):
        # OAuth callback is one-time, and has no web-session bearer token in URL.
        ensure_enabled()
        cid,secret,redirect,frontend=google_config()
        headers={"Referrer-Policy":"no-referrer","Cache-Control":"no-store"}
        def finish(result):
            return RedirectResponse(frontend+"/?tab=services&gmail_status="+result,
                                    status_code=303,headers=headers)
        if not state or len(state)>256:return finish("invalid_state")
        with engine.begin() as db:
            row=db.execute(text("""UPDATE public.ld_gmail_oauth_states
              SET used_at=now() WHERE nonce_sha256=:hash AND used_at IS NULL
              AND expires_at>now()
              RETURNING team_id,web_account_id,requested_scope"""),{
                "hash":hash_state(state)}).mappings().first()
        if not row:return finish("expired")
        if error or not code:return finish("cancelled")
        try:
            token=await exchange_code(code,cid,secret,redirect)
            granted=set(str(token.get("scope") or "").split())
            if not set(BASIC_SCOPES).issubset(granted):
                return finish("missing_scope")
            access=token.get("access_token") or ""
            if not access:return finish("provider_error")
            profile=await fetch_google_profile(access)
            alias_access=ALIAS_SCOPE in granted
            alias_data=await fetch_google_aliases(access) if alias_access else {}
            primary=profile["email"]
            candidates=alias_candidates(primary,alias_data,alias_access)
            token_refresh=token.get("refresh_token") or ""
            with engine.begin() as db:
                previous=db.execute(text("""SELECT id::text AS id,refresh_token_encrypted
                    FROM public.ld_gmail_connections
                    WHERE team_id=:team AND google_subject=:sub FOR UPDATE"""),{
                    "team":int(row["team_id"]),"sub":profile["sub"]}).mappings().first()
                encrypted=sender_crypto().encrypt(token_refresh.encode()).decode() if token_refresh else (
                     previous["refresh_token_encrypted"] if previous else "")
                if not encrypted:return finish("no_refresh")
                connection_id=db.execute(text("""INSERT INTO public.ld_gmail_connections
                   (team_id,web_account_id,google_subject,primary_email,refresh_token_encrypted,
                    scopes,status,verified_at)
                   VALUES(:team,:account,:sub,:email,:refresh,:scopes,'connected',now())
                   ON CONFLICT(team_id,google_subject) DO UPDATE SET
                       web_account_id=EXCLUDED.web_account_id,
                       primary_email=EXCLUDED.primary_email,
                       refresh_token_encrypted=EXCLUDED.refresh_token_encrypted,
                       scopes=EXCLUDED.scopes,status='connected',
                       verified_at=now(),updated_at=now()
                   RETURNING id::text"""),{
                    "team":int(row["team_id"]),"account":int(row["web_account_id"]),
                    "sub":profile["sub"],"email":primary,"refresh":encrypted,
                    "scopes":list(granted)}).scalar_one()
                for candidate in candidates:
                    db.execute(text("""INSERT INTO public.ld_gmail_sender_identities
                        (connection_id,email,display_name,verification_status,verification_source,enabled)
                        VALUES(CAST(:id AS uuid),:email,:name,:status,:source,false)
                        ON CONFLICT(connection_id,email) DO UPDATE SET
                        display_name=EXCLUDED.display_name,
                        verification_status=EXCLUDED.verification_status,
                        verification_source=EXCLUDED.verification_source,
                        updated_at=now(),
                        enabled=CASE WHEN EXCLUDED.verification_status='verified'
                          THEN public.ld_gmail_sender_identities.enabled ELSE false END"""),{
                        "id":connection_id,"email":candidate["email"],"name":candidate["name"],
                        "status":"verified" if candidate["verified"] else "pending",
                        "source":candidate["source"]})
            return finish("connected")
        except (httpx.RequestError,httpx.TimeoutException,HTTPException,InvalidToken,ValueError):
            return finish("provider_error")

    @router.get("/connections/{connection_id}/identities")
    def sender_identities(request:Request,connection_id:__import__("uuid").UUID):
        team,account=context(request)
        with engine.connect() as db:
            rs=db.execute(text("""SELECT s.id::text AS id,s.email,s.display_name,
                 s.verification_status,s.verification_source,s.enabled
                 FROM public.ld_gmail_sender_identities s
                 JOIN public.ld_gmail_connections c ON c.id=s.connection_id
                 WHERE c.team_id=:team AND c.id=:id AND c.status='connected'
                 ORDER BY s.verification_status='verified' DESC,s.email"""),{
                    "team":team,"id":connection_id}).mappings().all()
        return {"ok":True,"identities":[dict(r) for r in rs]}

    @router.post("/connections/{connection_id}/disconnect")
    def disconnect(request:Request,connection_id:__import__("uuid").UUID):
        team,account=context(request)
        ensure_enabled()
        with engine.begin() as db:
            row=db.execute(text("""UPDATE public.ld_gmail_connections
                 SET status='disconnected',refresh_token_encrypted='',updated_at=now()
                 WHERE id=:id AND team_id=:team AND web_account_id=:account
                 AND status='connected' RETURNING id"""),{
                     "id":connection_id,"team":team,"account":account}).scalar_one_or_none()
            if not row:raise HTTPException(404,"Connected Gmail account not found or not owned by you")
            db.execute(text("""UPDATE public.ld_gmail_sender_identities
                 SET enabled=false WHERE connection_id=:id"""),{"id":connection_id})
            db.execute(text("""UPDATE public.ld_campaigns SET status='paused',updated_at=now()
                 WHERE sender_identity_id IN (SELECT id FROM public.ld_gmail_sender_identities
                 WHERE connection_id=:id) AND status IN ('draft','active')"""),{"id":connection_id})
            db.execute(text("""UPDATE public.ld_campaign_queue SET status='held',updated_at=now(),
                 failure_code='sender_disconnected' WHERE sender_identity_id IN
                 (SELECT id FROM public.ld_gmail_sender_identities WHERE connection_id=:id)
                 AND status IN ('pending_review','approved')"""),{"id":connection_id})
        return {"ok":True,"status":"disconnected",
                "note":"Sender disconnected and its campaigns paused. Revoke access in your Google Account security settings if desired."}

    app.include_router(router)
