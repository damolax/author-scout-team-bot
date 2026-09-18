from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import bot_main as legacy
from sqlalchemy import text

app = legacy.app
app.version = "3.2"

# ---------------------------------------------------------------------------
# Author Scout v3 overlay
# - keeps all existing Author Scout features in bot_main.py
# - accelerates author discovery/research with bounded concurrency + cache
# - adds background LinkedIn Connection Intelligence
# - uses public web-search results only; it does not automate LinkedIn actions
# ---------------------------------------------------------------------------

CONN_READY_TARGET = int(os.getenv("CONNECTION_READY_TARGET", "100"))
CONN_BATCH_SIZE = int(os.getenv("CONNECTION_BATCH_SIZE", "25"))
CONN_INTERVAL = max(30, int(os.getenv("CONNECTION_RESEARCH_INTERVAL_SECONDS", "180")))
CONN_CONCURRENCY = max(1, min(16, int(os.getenv("CONNECTION_MAX_CONCURRENCY", "8"))))
CONN_MIN_SCORE = max(1, min(100, int(os.getenv("CONNECTION_MIN_SCORE", "65"))))
CONN_USERS_PER_CYCLE = max(1, int(os.getenv("CONNECTION_USERS_PER_CYCLE", "12")))
CONN_DISPLAY_COUNT = max(1, min(10, int(os.getenv("CONNECTION_DISPLAY_COUNT", "5"))))
CONN_GLOBAL_EXCLUSIVE = os.getenv("CONNECTION_GLOBAL_EXCLUSIVITY", "false").strip().lower() in {"1", "true", "yes", "on"}
CONN_DEFAULT_COUNTRIES = [x.strip() for x in os.getenv(
    "CONNECTION_DEFAULT_COUNTRIES",
    "United States,United Kingdom,Canada,Australia,Germany,France,United Arab Emirates"
).split(",") if x.strip()]
CONN_EXCLUDED_COUNTRIES = [x.strip() for x in os.getenv("CONNECTION_EXCLUDED_COUNTRIES", "Nigeria").split(",") if x.strip()]
AUTHOR_RESEARCH_CONCURRENCY = max(2, min(16, int(os.getenv("AUTHOR_RESEARCH_CONCURRENCY", "10"))))
RESEARCH_CACHE_HOURS = max(1, int(os.getenv("RESEARCH_CACHE_HOURS", "24")))
SEARCH_CACHE_HOURS = max(1, int(os.getenv("SEARCH_CACHE_HOURS", "6")))
SEARCH_PRIMARY_BACKEND = os.getenv("SEARCH_PRIMARY_BACKEND", "bing").strip() or "bing"
SEARCH_FALLBACK_BACKEND = os.getenv("SEARCH_FALLBACK_BACKEND", "duckduckgo").strip() or "duckduckgo"
HTTP_MAX_CONNECTIONS = max(10, int(os.getenv("HTTP_MAX_CONNECTIONS", "40")))
HTTP_KEEPALIVE_CONNECTIONS = max(5, int(os.getenv("HTTP_KEEPALIVE_CONNECTIONS", "20")))
SOURCE_INDEX_ENABLED = os.getenv("SOURCE_INDEX_ENABLED", "true").strip().lower() in {"1","true","yes","on"}
SOURCE_INDEX_INTERVAL = max(60, int(os.getenv("SOURCE_INDEX_INTERVAL_SECONDS", "300")))
SOURCE_INDEX_CONCURRENCY = max(2, min(16, int(os.getenv("SOURCE_INDEX_CONCURRENCY", "8"))))
SOURCE_INDEX_DEMANDS_PER_CYCLE = max(1, min(20, int(os.getenv("SOURCE_INDEX_DEMANDS_PER_CYCLE", "6"))))
SOURCE_INDEX_SOURCE_PAGES_PER_DEMAND = max(1, min(10, int(os.getenv("SOURCE_INDEX_SOURCE_PAGES_PER_DEMAND", "4"))))
SOURCE_INDEX_PREVERIFY_PER_CYCLE = max(1, min(50, int(os.getenv("SOURCE_INDEX_PREVERIFY_PER_CYCLE", "16"))))
SOURCE_INDEX_POOL_TARGET = max(50, int(os.getenv("SOURCE_INDEX_POOL_TARGET_PER_MARKET", "300")))
SOURCE_INDEX_DEFAULT_COUNTRIES = [x.strip() for x in os.getenv(
    "SOURCE_INDEX_DEFAULT_COUNTRIES",
    "United Kingdom,United States,Canada,Australia,France,Germany,Austria,United Arab Emirates,New Zealand,Spain,Iceland"
).split(",") if x.strip()]

_COUNTRY_ALIASES = {
    "usa": "United States", "us": "United States", "u.s.": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom",
    "uae": "United Arab Emirates", "ksa": "Saudi Arabia", "saudi": "Saudi Arabia",
}

_STOPWORDS = {
    "linkedin", "profile", "professional", "experience", "company", "services", "service",
    "the", "and", "with", "for", "from", "this", "that", "your", "you", "our", "are",
    "at", "in", "of", "to", "a", "an", "on", "by", "as", "or", "about", "www", "com",
    "http", "https", "view", "people", "connections", "connection",
}

_ROLE_TERMS = {
    "author", "writer", "publisher", "publishing", "editor", "literary", "agent", "books",
    "founder", "director", "head", "manager", "consultant", "strategist", "marketing",
    "publicist", "translator", "rights", "producer", "creator", "journalist", "executive",
    "ceo", "owner", "partner", "lead", "specialist"
}

_SENIORITY_TERMS = {"founder", "owner", "ceo", "chief", "director", "head", "partner", "lead", "manager"}


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _canon_linkedin(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    try:
        p = urlparse(url)
        host = p.netloc.lower().replace("www.", "")
        if host not in {"linkedin.com", "m.linkedin.com"} and not host.endswith(".linkedin.com"):
            return ""
        path = re.sub(r"/+", "/", p.path).rstrip("/")
        if not path.lower().startswith("/in/"):
            return ""
        return urlunparse(("https", "www.linkedin.com", path, "", "", ""))
    except Exception:
        return ""


def _profile_slug(url: str) -> str:
    try:
        return urlparse(url).path.strip("/").split("/")[-1].replace("-", " ")
    except Exception:
        return ""


def _tokens(text_value: str, limit: int = 10) -> list[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9&+.'’-]{2,}", (text_value or "").lower())
    seen = []
    for w in words:
        w = w.strip(".'’-+")
        if len(w) < 3 or w in _STOPWORDS or w.isdigit():
            continue
        if w not in seen:
            seen.append(w)
        if len(seen) >= limit:
            break
    return seen


def _prompt_text() -> str:
    p = Path(__file__).with_name("CONNECTION_FIT_PROMPT_V1.txt")
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return "Score professional fit, mutual value, relevance, geography confidence, and network diversity. Never infer nationality or ethnicity."


def init_connection_db() -> None:
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if legacy.DB.startswith("sqlite") else "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
    stmts = [
        f"""CREATE TABLE IF NOT EXISTS connection_preferences(
            telegram_user_id BIGINT PRIMARY KEY,
            team_id INTEGER NOT NULL,
            linkedin_profile_url TEXT NOT NULL,
            profile_context TEXT DEFAULT '',
            target_query TEXT DEFAULT '',
            target_countries TEXT DEFAULT '[]',
            excluded_countries TEXT DEFAULT '[]',
            min_score INTEGER NOT NULL DEFAULT 65,
            ready_target INTEGER NOT NULL DEFAULT 100,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_refill_at TEXT DEFAULT '',
            last_error TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS connection_profiles(
            id {pk},
            normalized_url TEXT NOT NULL UNIQUE,
            profile_url TEXT NOT NULL,
            name TEXT NOT NULL,
            headline TEXT DEFAULT '',
            company TEXT DEFAULT '',
            location TEXT DEFAULT '',
            country TEXT DEFAULT '',
            snippet TEXT DEFAULT '',
            source_query TEXT DEFAULT '',
            fit_score INTEGER NOT NULL DEFAULT 0,
            fit_reason TEXT DEFAULT '',
            fit_evidence TEXT DEFAULT '',
            discovered_at TEXT NOT NULL,
            last_verified_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS connection_assignments(
            id {pk},
            profile_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            assigned_user_id BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ready',
            assigned_at TEXT NOT NULL,
            viewed_at TEXT DEFAULT '',
            connected_at TEXT DEFAULT '',
            skipped_at TEXT DEFAULT '',
            archived_at TEXT DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(profile_id, team_id)
        )""",
        f"""CREATE TABLE IF NOT EXISTS connection_events(
            id {pk},
            profile_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            telegram_user_id BIGINT NOT NULL,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS connection_global_claims(
            profile_id INTEGER PRIMARY KEY,
            team_id INTEGER NOT NULL,
            telegram_user_id BIGINT NOT NULL,
            claimed_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS research_cache(
            cache_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS author_search_demands(
            demand_key TEXT PRIMARY KEY,
            country TEXT DEFAULT '',
            genre TEXT DEFAULT '',
            query_text TEXT DEFAULT '',
            name_filter TEXT DEFAULT '',
            language TEXT DEFAULT '',
            gender TEXT DEFAULT 'any',
            request_count INTEGER NOT NULL DEFAULT 0,
            desired_count INTEGER NOT NULL DEFAULT 10,
            last_requested_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS author_source_registry(
            id {pk},
            source_key TEXT NOT NULL UNIQUE,
            source_url TEXT NOT NULL,
            domain TEXT DEFAULT '',
            country TEXT DEFAULT '',
            source_type TEXT DEFAULT '',
            discovery_query TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            last_crawled_at TEXT DEFAULT '',
            next_crawl_at TEXT DEFAULT '',
            discovered_count INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS author_candidate_pool(
            id {pk},
            candidate_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            country TEXT DEFAULT '',
            genre TEXT DEFAULT '',
            discovery_url TEXT DEFAULT '',
            source_url TEXT DEFAULT '',
            source_domain TEXT DEFAULT '',
            source_type TEXT DEFAULT '',
            discovery_query TEXT DEFAULT '',
            snippet TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'discovered',
            times_selected INTEGER NOT NULL DEFAULT 0,
            verified_payload TEXT DEFAULT '{}',
            verification_status TEXT DEFAULT '',
            last_verified_at TEXT DEFAULT '',
            discovered_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_author_pool_country_status ON author_candidate_pool(country,status)",
        "CREATE INDEX IF NOT EXISTS idx_author_pool_status_seen ON author_candidate_pool(status,last_seen_at)",
        "CREATE INDEX IF NOT EXISTS idx_author_sources_country ON author_source_registry(country,status)",
    ]
    with legacy.engine.begin() as c:
        for s in stmts:
            c.execute(text(s))


def _cache_get(key: str):
    x = legacy.row("SELECT payload,expires_at FROM research_cache WHERE cache_key=:k", k=key)
    if not x:
        return None
    try:
        if x["expires_at"] <= legacy.iso():
            legacy.execq("DELETE FROM research_cache WHERE cache_key=:k", k=key)
            return None
        return json.loads(x["payload"])
    except Exception:
        return None


def _cache_put(key: str, payload: dict):
    exp = legacy.iso(legacy.now() + timedelta(hours=RESEARCH_CACHE_HOURS))
    t = legacy.iso()
    try:
        legacy.execq(
            """INSERT INTO research_cache(cache_key,payload,expires_at,updated_at)
               VALUES(:k,:p,:e,:t)
               ON CONFLICT(cache_key) DO UPDATE SET payload=:p,expires_at=:e,updated_at=:t""",
            k=key, p=json.dumps(payload, ensure_ascii=False), e=exp, t=t,
        )
    except Exception:
        legacy.execq("DELETE FROM research_cache WHERE cache_key=:k", k=key)
        legacy.execq("INSERT INTO research_cache(cache_key,payload,expires_at,updated_at) VALUES(:k,:p,:e,:t)", k=key, p=json.dumps(payload, ensure_ascii=False), e=exp, t=t)


# ---------------------------------------------------------------------------
# Shared fast I/O layer
# ---------------------------------------------------------------------------

_legacy_search = legacy.search
_legacy_fetch = legacy.fetch
_http_client = None

def _search_cache_key(q: str, n: int) -> str:
    compact = re.sub(r"\s+", " ", (q or "").strip().lower())
    return "search:" + str(n) + ":" + compact[:420]

def _search_cache_get(key: str):
    return _cache_get(key)

def _search_cache_put(key: str, payload):
    exp = legacy.iso(legacy.now() + timedelta(hours=SEARCH_CACHE_HOURS))
    t = legacy.iso()
    data = json.dumps({"results": payload}, ensure_ascii=False)
    try:
        legacy.execq(
            """INSERT INTO research_cache(cache_key,payload,expires_at,updated_at)
               VALUES(:k,:p,:e,:t)
               ON CONFLICT(cache_key) DO UPDATE SET payload=:p,expires_at=:e,updated_at=:t""",
            k=key, p=data, e=exp, t=t,
        )
    except Exception:
        pass

def _single_backend_search(q: str, n: int, backend: str):
    out, seen = [], set()
    timeout = max(4, min(8, int(legacy.TIMEOUT)))
    try:
        with legacy.DDGS(timeout=timeout) as d:
            results = d.text(q, max_results=n, safesearch="moderate", backend=backend)
            for x in results:
                u = x.get("href") or x.get("url", "")
                if not u or u in seen:
                    continue
                seen.add(u)
                out.append({"title": x.get("title", ""), "url": u, "snippet": x.get("body") or x.get("snippet", "")})
                if len(out) >= n:
                    break
    except Exception as e:
        print(f"FAST_SEARCH_BACKEND_ERROR backend={backend} {type(e).__name__}: {e}")
    return out

def _fast_search_sync(q: str, n: int = 10):
    key = _search_cache_key(q, n)
    cached = _search_cache_get(key)
    if cached and isinstance(cached, dict) and isinstance(cached.get("results"), list):
        return cached["results"][:n]
    started = time.monotonic()
    out = _single_backend_search(q, n, SEARCH_PRIMARY_BACKEND)
    # Fallback only when the primary route is empty/weak. Do not serially cycle four engines.
    floor = min(n, 4)
    if len(out) < floor and SEARCH_FALLBACK_BACKEND and SEARCH_FALLBACK_BACKEND != SEARCH_PRIMARY_BACKEND:
        extra = _single_backend_search(q, n, SEARCH_FALLBACK_BACKEND)
        seen = {x.get("url") for x in out}
        for x in extra:
            if x.get("url") not in seen:
                out.append(x); seen.add(x.get("url"))
            if len(out) >= n:
                break
    _search_cache_put(key, out)
    print(f"FAST_SEARCH_RESULT count={len(out)} seconds={time.monotonic()-started:.2f} query={q[:140]}")
    return out[:n]

async def fast_search(q: str, n: int = 10):
    return await asyncio.to_thread(_fast_search_sync, q, n)

async def fast_fetch(u: str):
    global _http_client
    try:
        if _http_client is None:
            _http_client = legacy.httpx.AsyncClient(
                timeout=legacy.TIMEOUT, headers=legacy.HEADERS, follow_redirects=True,
                limits=legacy.httpx.Limits(max_connections=HTTP_MAX_CONNECTIONS, max_keepalive_connections=HTTP_KEEPALIVE_CONNECTIONS),
            )
        r = await _http_client.get(u)
        if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
            return "", str(r.url)
        return r.text[:1000000], str(r.url)
    except Exception:
        return "", u

legacy.search = fast_search
legacy.fetch = fast_fetch


# ---------------------------------------------------------------------------
# Persistent source index + author candidate reservoir
# ---------------------------------------------------------------------------

def _norm_author_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

def _pool_key(name: str, country: str = "") -> str:
    return f"{_norm_author_name(name)}|{re.sub(r'[^a-z0-9]+','',(country or '').lower())}"

def _demand_key(spec: dict) -> str:
    parts = [spec.get("country",""), spec.get("genre",""), spec.get("query",""),
             spec.get("name",""), spec.get("language",""), spec.get("gender","any")]
    return "|".join(re.sub(r"\s+"," ",str(x or "").strip().lower()) for x in parts)[:700]

def _record_search_demand(spec: dict) -> None:
    key = _demand_key(spec)
    t = legacy.iso()
    country = _COUNTRY_ALIASES.get((spec.get("country") or "").strip().lower(), spec.get("country") or "")
    try:
        legacy.execq("""INSERT INTO author_search_demands(
            demand_key,country,genre,query_text,name_filter,language,gender,request_count,desired_count,last_requested_at,created_at,updated_at
        ) VALUES(:k,:c,:g,:q,:n,:l,:sex,1,:d,:t,:t,:t)
        ON CONFLICT(demand_key) DO UPDATE SET
            request_count=author_search_demands.request_count+1,
            desired_count=:d,last_requested_at=:t,updated_at=:t""",
            k=key,c=country,g=spec.get("genre",""),q=spec.get("query",""),n=spec.get("name",""),
            l=spec.get("language",""),sex=spec.get("gender","any"),d=max(1,int(spec.get("count") or 10)),t=t)
    except Exception as e:
        print(f"SOURCE_DEMAND_ERROR {type(e).__name__}: {e}")

def _source_type(title: str, snippet: str, url: str) -> str:
    s = f"{title} {snippet} {url}".lower()
    if "writers association" in s or "writers union" in s or "author association" in s:
        return "writers_association"
    if "literature centre" in s or "literature center" in s or "literary centre" in s or "literary center" in s:
        return "literature_center"
    if "literary agency" in s or "agency authors" in s:
        return "literary_agency"
    if "publisher" in s or "publishing house" in s:
        return "publisher"
    if "festival" in s or "book fair" in s:
        return "festival"
    if "directory" in s or "members" in s or "authors" in s or "writers" in s:
        return "directory"
    return "web_source"

def _looks_like_index_source(result: dict) -> bool:
    u=(result.get("url") or "").lower()
    s=f"{result.get('title','')} {result.get('snippet','')} {u}".lower()
    if any(x in legacy.host(u) for x in ["amazon.","goodreads.","wikipedia.","facebook.","instagram.","linkedin."]):
        return False
    return any(x in s for x in ["authors","writers","directory","members","literature","literary","publisher","agency","festival"])

def _register_source(result: dict, country: str, query: str) -> None:
    url=(result.get("url") or "").strip()
    if not url:return
    key=url.lower().rstrip("/")[:900]
    t=legacy.iso()
    try:
        legacy.execq("""INSERT INTO author_source_registry(
            source_key,source_url,domain,country,source_type,discovery_query,status,last_crawled_at,next_crawl_at,
            discovered_count,error_count,last_error,created_at,updated_at
        ) VALUES(:k,:u,:h,:c,:s,:q,'active','','',0,0,'',:t,:t)
        ON CONFLICT(source_key) DO UPDATE SET country=:c,source_type=:s,discovery_query=:q,status='active',updated_at=:t""",
            k=key,u=url,h=legacy.host(url),c=country,s=_source_type(result.get("title",""),result.get("snippet",""),url),q=query,t=t)
    except Exception:
        pass

def _upsert_pool_candidate(name: str, country: str, genre: str="", discovery_url: str="", source_url: str="",
                           source_type: str="", discovery_query: str="", snippet: str="") -> int:
    name=re.sub(r"\s+"," ",(name or "").strip(" -|:,.;"))
    if not name or len(name)<4 or len(name)>100 or not (2 <= len(name.split()) <= 6):
        return 0
    k=_pool_key(name,country)
    if not k.split("|")[0]:return 0
    t=legacy.iso()
    try:
        legacy.execq("""INSERT INTO author_candidate_pool(
            candidate_key,name,country,genre,discovery_url,source_url,source_domain,source_type,discovery_query,snippet,
            status,times_selected,verified_payload,verification_status,last_verified_at,discovered_at,last_seen_at,updated_at
        ) VALUES(:k,:n,:c,:g,:du,:su,:sd,:st,:q,:sn,'discovered',0,'{}','','',:t,:t,:t)
        ON CONFLICT(candidate_key) DO UPDATE SET
            discovery_url=CASE WHEN :du<>'' THEN :du ELSE author_candidate_pool.discovery_url END,
            source_url=CASE WHEN :su<>'' THEN :su ELSE author_candidate_pool.source_url END,
            source_domain=CASE WHEN :sd<>'' THEN :sd ELSE author_candidate_pool.source_domain END,
            source_type=CASE WHEN :st<>'' THEN :st ELSE author_candidate_pool.source_type END,
            discovery_query=CASE WHEN :q<>'' THEN :q ELSE author_candidate_pool.discovery_query END,
            snippet=CASE WHEN :sn<>'' THEN :sn ELSE author_candidate_pool.snippet END,
            genre=CASE WHEN author_candidate_pool.genre='' AND :g<>'' THEN :g ELSE author_candidate_pool.genre END,
            last_seen_at=:t,updated_at=:t""",
            k=k,n=name,c=country or "",g=genre or "",du=discovery_url or "",su=source_url or discovery_url or "",
            sd=legacy.host(source_url or discovery_url or ""),st=source_type or "",q=discovery_query or "",
            sn=(snippet or "")[:1200],t=t)
        r=legacy.row("SELECT id FROM author_candidate_pool WHERE candidate_key=:k",k=k)
        return int(r["id"]) if r else 0
    except Exception as e:
        print(f"POOL_UPSERT_ERROR {type(e).__name__}: {e}")
        return 0

def _pool_candidates(spec: dict, limit: int=100) -> list[dict]:
    country=_COUNTRY_ALIASES.get((spec.get("country") or "").strip().lower(),spec.get("country") or "")
    if country:
        rs=legacy.rows("""SELECT * FROM author_candidate_pool
            WHERE lower(country)=lower(:c) AND status IN ('verified','discovered')
            ORDER BY CASE WHEN status='verified' THEN 0 ELSE 1 END,times_selected ASC,last_seen_at DESC LIMIT :n""",
            c=country,n=max(limit*4,200))
    else:
        rs=legacy.rows("""SELECT * FROM author_candidate_pool
            WHERE status IN ('verified','discovered')
            ORDER BY CASE WHEN status='verified' THEN 0 ELSE 1 END,times_selected ASC,last_seen_at DESC LIMIT :n""",
            n=max(limit*4,300))
    name_filter=(spec.get("name") or "").lower().strip()
    genre=(spec.get("genre") or "").lower().strip()
    qtokens=[x for x in _tokens((spec.get("query") or "").lower(),8) if x not in {"author","authors","writer","writers","book","books"}]
    scored=[]
    for r in rs:
        if name_filter and name_filter not in (r.get("name") or "").lower():continue
        blob=" ".join([r.get("name") or "",r.get("genre") or "",r.get("snippet") or "",r.get("discovery_query") or "",r.get("source_type") or ""]).lower()
        overlap=sum(1 for x in qtokens if x in blob)
        if genre and genre not in blob and r.get("genre"):continue
        score=(100 if r.get("status")=="verified" else 0)+overlap*12
        scored.append((score,r))
    scored.sort(key=lambda x:(-x[0],int(x[1].get("times_selected") or 0)))
    return [r for _,r in scored[:limit]]

def _mark_pool_verified(pool_id: int, payload: dict, passed: bool) -> None:
    if not pool_id:return
    legacy.execq("""UPDATE author_candidate_pool SET status=:s,verified_payload=:p,
        verification_status=:v,last_verified_at=:t,updated_at=:t WHERE id=:i""",
        s="verified" if passed else "rejected",p=json.dumps(payload,ensure_ascii=False),
        v=payload.get("verification_status",""),t=legacy.iso(),i=pool_id)

def _extract_index_names(raw: str, page_url: str) -> list[tuple[str,str]]:
    if not raw:return []
    soup=legacy.BeautifulSoup(raw,"html.parser")
    out=[];seen=set()
    bad={"read more","learn more","contact us","about us","our authors","our writers","members","home","books","news",
         "privacy policy","terms of use","view profile","view all","more information","click here"}
    nodes=list(soup.find_all(["h2","h3","h4"]))
    nodes += [a for a in soup.find_all("a",href=True) if any(x in (a.get("href") or "").lower()
              for x in ["/author","/writer","/member","/people","/profile","/hofund","/contributor"])]
    for node in nodes[:500]:
        txt=re.sub(r"\s+"," ",node.get_text(" ",strip=True)).strip(" -|:,.;")
        if txt.lower() in bad or len(txt)<5 or len(txt)>80:continue
        words=txt.split()
        if not (2<=len(words)<=5):continue
        if sum(bool(re.search(r"[A-Za-zÀ-ÿ]",w)) for w in words)!=len(words):continue
        if sum(bool(re.match(r"^[A-ZÀ-Ý]",w)) for w in words)<max(1,len(words)-1):continue
        k=_norm_author_name(txt)
        if not k or k in seen:continue
        seen.add(k)
        href=legacy.urljoin(page_url,node.get("href","")) if getattr(node,"name","")=="a" else ""
        out.append((txt,href))
        if len(out)>=120:break
    return out

async def _index_source_page(source: dict, demand: dict) -> int:
    try:
        raw,final=await fast_fetch(source.get("source_url") or "")
        names=await asyncio.to_thread(_extract_index_names,raw,final)
        added=0
        for name,href in names:
            if _upsert_pool_candidate(name,demand.get("country") or "",demand.get("genre") or "",href or final,final,
                                      source.get("source_type") or "directory",demand.get("query_text") or "",""):
                added+=1
        legacy.execq("""UPDATE author_source_registry SET last_crawled_at=:t,next_crawl_at=:n,
            discovered_count=discovered_count+:a,last_error='',status='active',updated_at=:t WHERE id=:i""",
            t=legacy.iso(),n=legacy.iso(legacy.now()+timedelta(hours=12)),a=added,i=source["id"])
        return added
    except Exception as e:
        legacy.execq("""UPDATE author_source_registry SET error_count=error_count+1,last_error=:e,
            last_crawled_at=:t,next_crawl_at=:n,updated_at=:t WHERE id=:i""",
            e=f"{type(e).__name__}: {e}"[:500],t=legacy.iso(),n=legacy.iso(legacy.now()+timedelta(hours=2)),i=source["id"])
        return 0

async def _index_demand(demand: dict) -> dict:
    country=demand.get("country") or ""
    genre=demand.get("genre") or ""
    qtext=demand.get("query_text") or ""
    name_filter=demand.get("name_filter") or ""
    base=" ".join(x for x in [country,genre,qtext,name_filter] if x).strip() or "authors"
    routes=[f'{base} authors directory writers association',f'{base} literature center writers members',
            f'{base} literary agency publisher authors']
    sets=await asyncio.gather(*(fast_search(q,15) for q in routes),return_exceptions=True)
    direct=0
    for query,rs in zip(routes,sets):
        if isinstance(rs,Exception):continue
        for r in rs:
            n=legacy.cand(r.get("title",""),r.get("snippet",""))
            if n and _upsert_pool_candidate(n,country,genre,r.get("url") or "",r.get("url") or "","search_result",query,r.get("snippet") or ""):
                direct+=1
            if _looks_like_index_source(r):_register_source(r,country,query)
    sources=legacy.rows("""SELECT * FROM author_source_registry WHERE status='active'
        AND (:c='' OR lower(country)=lower(:c)) AND (next_crawl_at='' OR next_crawl_at<=:now)
        ORDER BY CASE WHEN last_crawled_at='' THEN 0 ELSE 1 END,last_crawled_at ASC LIMIT :n""",
        c=country,now=legacy.iso(),n=SOURCE_INDEX_SOURCE_PAGES_PER_DEMAND)
    crawled=0
    if sources:
        vals=await asyncio.gather(*(_index_source_page(s,demand) for s in sources),return_exceptions=True)
        crawled=sum(v for v in vals if isinstance(v,int))
    return {"direct":direct,"crawled":crawled}

async def _preverify_pool(demand: dict, limit: int=SOURCE_INDEX_PREVERIFY_PER_CYCLE) -> int:
    spec={"country":demand.get("country") or "","genre":demand.get("genre") or "",
          "query":demand.get("query_text") or "","name":demand.get("name_filter") or ""}
    pool=await asyncio.to_thread(_pool_candidates,spec,limit*3)
    existing=await asyncio.to_thread(legacy.rows,"SELECT name,country FROM prospects")
    existing_keys={_pool_key(r.get("name") or "",r.get("country") or "") for r in existing}
    candidates=[p for p in pool if p.get("status")=="discovered" and p.get("candidate_key") not in existing_keys][:limit]
    sem=asyncio.Semaphore(SOURCE_INDEX_CONCURRENCY)
    async def one(p):
        async with sem:
            d=await _contact_research(p["name"],p.get("country") or "",p.get("genre") or "",p.get("discovery_url") or "")
            passed=bool(d.get("website") and d.get("email"))
            if passed:d=await _enrich_activity(d)
            await asyncio.to_thread(_mark_pool_verified,int(p["id"]),d,passed)
            return int(passed)
    if not candidates:return 0
    results=await asyncio.gather(*(one(p) for p in candidates),return_exceptions=True)
    return sum(v for v in results if isinstance(v,int))

def _seed_default_demands() -> None:
    if legacy.row("SELECT demand_key FROM author_search_demands LIMIT 1"):return
    for country in SOURCE_INDEX_DEFAULT_COUNTRIES:
        _record_search_demand({"country":country,"genre":"","query":"authors","name":"","language":"","gender":"any","count":10})

async def source_index_worker():
    await asyncio.sleep(8)
    if not SOURCE_INDEX_ENABLED:
        print("SOURCE_INDEX_WORKER enabled=False")
        return
    await asyncio.to_thread(_seed_default_demands)
    while True:
        try:
            demands=legacy.rows("""SELECT * FROM author_search_demands
                ORDER BY last_requested_at DESC,request_count DESC LIMIT :n""",n=SOURCE_INDEX_DEMANDS_PER_CYCLE)
            for d in demands:
                try:
                    current=legacy.row("""SELECT COUNT(*) c FROM author_candidate_pool
                        WHERE status IN ('verified','discovered') AND (:c='' OR lower(country)=lower(:c))""",c=d.get("country") or "")
                    if int((current or {"c":0})["c"]) < SOURCE_INDEX_POOL_TARGET:
                        await _index_demand(d)
                    await _preverify_pool(d,SOURCE_INDEX_PREVERIFY_PER_CYCLE)
                except Exception as e:
                    print(f"SOURCE_INDEX_DEMAND_ERROR {type(e).__name__}: {e}")
            await asyncio.sleep(SOURCE_INDEX_INTERVAL)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"SOURCE_INDEX_WORKER_ERROR {type(e).__name__}: {e}")
            await asyncio.sleep(SOURCE_INDEX_INTERVAL)

async def show_index_status(chat: int):
    total=int((legacy.row("SELECT COUNT(*) c FROM author_candidate_pool") or {"c":0})["c"])
    verified=int((legacy.row("SELECT COUNT(*) c FROM author_candidate_pool WHERE status='verified'") or {"c":0})["c"])
    discovered=int((legacy.row("SELECT COUNT(*) c FROM author_candidate_pool WHERE status='discovered'") or {"c":0})["c"])
    rejected=int((legacy.row("SELECT COUNT(*) c FROM author_candidate_pool WHERE status='rejected'") or {"c":0})["c"])
    sources=int((legacy.row("SELECT COUNT(*) c FROM author_source_registry") or {"c":0})["c"])
    demands=int((legacy.row("SELECT COUNT(*) c FROM author_search_demands") or {"c":0})["c"])
    return await legacy.send(chat,
        f"<b>⚡ Author Source Index</b>\\nBackground indexing: <b>{'ON' if SOURCE_INDEX_ENABLED else 'OFF'}</b>\\n"
        f"Candidate reservoir: <b>{total}</b>\\nPre-verified ready identities: <b>{verified}</b>\\n"
        f"Awaiting verification: <b>{discovered}</b>\\nRejected by verification: <b>{rejected}</b>\\n"
        f"Indexed source pages: <b>{sources}</b>\\nActive search-demand patterns: <b>{demands}</b>")


# ---------------------------------------------------------------------------
# Faster author research
# ---------------------------------------------------------------------------

_legacy_research = legacy.research


async def _contact_research(name: str, country: str = "", genre: str = "", hint: str = ""):
    """Fast qualification pass: identity route + website + public contact only."""
    key = "contact:" + re.sub(r"[^a-z0-9]+", "", f"{name}|{country}|{genre}|{hint}".lower())[:220]
    cached = await asyncio.to_thread(_cache_get, key)
    if cached:
        return cached

    website = hint if hint and legacy.official(hint, name) else ""
    if not website:
        rs = await fast_search(f'"{name}" author official website', 6)
        website = next((r["url"] for r in rs if legacy.official(r["url"], name)), "")
        if not website:
            website = next((r["url"] for r in rs if r.get("url") and not any(x in legacy.host(r["url"]) for x in ["amazon.", "goodreads.", "wikipedia.", "facebook.", "instagram."])), "")

    bio = emailv = source = ""
    sources = []
    verified = "unverified"
    if website:
        raw, final = await fast_fetch(website)
        if final:
            sources.append(final)
        if raw:
            sdoc = legacy.BeautifulSoup(raw, "html.parser")
            bio = re.sub(r"\s+", " ", sdoc.get_text(" ")).strip()[:700]
            em = legacy.emails(raw)
            if em:
                emailv, source, verified = em[0], final, "verified_public"
            else:
                contact_urls = []
                for a in sdoc.find_all("a", href=True):
                    label = (a.get_text(" ") + " " + a["href"]).lower()
                    if any(k in label for k in ["contact", "about", "press", "media"]):
                        u = legacy.urljoin(final, a["href"])
                        if legacy.host(u) == legacy.host(final) and u not in contact_urls:
                            contact_urls.append(u)
                    if len(contact_urls) >= 3:
                        break
                if contact_urls:
                    pages = await asyncio.gather(*(fast_fetch(u) for u in contact_urls), return_exceptions=True)
                    for res in pages:
                        if isinstance(res, Exception):
                            continue
                        rr, ff = res
                        if ff:
                            sources.append(ff)
                        em = legacy.emails(rr)
                        if em:
                            emailv, source, verified = em[0], ff, "verified_public"
                            break
    result = {
        "name": name, "country": country, "genre": genre, "website": website,
        "email": emailv, "email_source_url": source, "verification_status": verified,
        "bio": bio, "books": "", "recent_activity": "",
        "source_urls": list(dict.fromkeys([x for x in sources if x])),
    }
    await asyncio.to_thread(_cache_put, key, result)
    return result

async def _enrich_activity(d: dict):
    name = d.get("name") or ""
    if not name:
        return d
    act = await fast_search(f'"{name}" author {legacy.YEAR} book OR event OR release OR interview', 3)
    if act:
        d["recent_activity"] = (act[0].get("title", "") + ": " + act[0].get("snippet", ""))[:700]
        if act[0].get("url"):
            d["source_urls"] = list(dict.fromkeys((d.get("source_urls") or []) + [act[0]["url"]]))
    return d

async def fast_research(name: str, country: str = "", genre: str = "", hint: str = ""):
    key = "author:" + re.sub(r"[^a-z0-9]+", "", f"{name}|{country}|{genre}|{hint}".lower())[:220]
    cached = await asyncio.to_thread(_cache_get, key)
    if cached:
        return cached
    d = await _contact_research(name, country, genre, hint)
    d = await _enrich_activity(d)
    await asyncio.to_thread(_cache_put, key, d)
    return d


async def fast_find_authors(spec, progress=None):
    count=int(spec["count"])
    country=spec.get("country","")
    genre=spec.get("genre","")
    gender=spec.get("gender","any")
    name_filter=spec.get("name","")
    language=spec.get("language","")
    year=spec.get("year","")
    free_query=spec.get("query","")
    require_email=spec.get("require_email",True)
    require_website=spec.get("require_website",True)
    country_term=_COUNTRY_ALIASES.get((country or "").strip().lower(),country)
    await asyncio.to_thread(_record_search_demand,spec)

    intent_parts=[]
    if name_filter:intent_parts.append(f'"{name_filter}"')
    if free_query:intent_parts.append(free_query)
    if country_term:intent_parts.append(country_term)
    if genre:intent_parts.append(genre)
    if language:intent_parts.append(language)
    if gender in {"male","female"}:intent_parts.append(gender)
    base=" ".join(dict.fromkeys([x.strip() for x in intent_parts if x.strip()])).strip() or "author"
    activity_year=year or str(legacy.YEAR)
    web_queries=[
        f'{base} author official website contact email',
        f'{base} writer novelist official site',
        f'{base} author {activity_year} release event'
    ]

    started=time.monotonic()
    existing_rows=await asyncio.to_thread(legacy.rows,"SELECT name,country FROM prospects")
    existing_keys={_pool_key(r.get("name") or "",r.get("country") or "") for r in existing_rows}
    existing_names={_norm_author_name(r.get("name") or "") for r in existing_rows}

    pool=await asyncio.to_thread(_pool_candidates,spec,max(count*10,80))
    pool=[p for p in pool if p.get("candidate_key") not in existing_keys and _norm_author_name(p.get("name") or "") not in existing_names]

    out=[];checked=0;with_email=0;with_website=0;raw_results=0;reservoir_hits=0
    accepted_names=set();queries_used=["NEON_AUTHOR_RESERVOIR"]
    if progress:
        ready=sum(1 for p in pool if p.get("status")=="verified")
        await progress(
            f"⚡ <b>Reservoir-first scout</b>\\n"
            f"Market: {legacy.esc(base)}\\n"
            f"Stored candidates available: <b>{len(pool)}</b>\\n"
            f"Already pre-verified: <b>{ready}</b>"
        )

    remaining=[]
    for p in pool:
        if len(out)>=count:break
        payload={}
        if p.get("status")=="verified" and p.get("verified_payload"):
            try:payload=json.loads(p["verified_payload"] or "{}")
            except Exception:payload={}
        if payload:
            checked+=1
            if payload.get("website"):with_website+=1
            if payload.get("email"):with_email+=1
            if require_website and not payload.get("website"):continue
            if require_email and not payload.get("email"):continue
            nk=_norm_author_name(payload.get("name") or p.get("name") or "")
            if not nk or nk in accepted_names:continue
            accepted_names.add(nk);out.append(payload);reservoir_hits+=1
            legacy.execq("UPDATE author_candidate_pool SET times_selected=times_selected+1,updated_at=:t WHERE id=:i",t=legacy.iso(),i=p["id"])
        else:
            remaining.append(p)

    if len(out)>=count:
        seconds=time.monotonic()-started
        return out[:count],{
            "raw_results":0,"candidates":len(pool),"checked":checked,"with_email":with_email,
            "with_website":with_website,"query":base,"queries":queries_used,
            "elapsed_seconds":round(seconds,2),"reservoir_hits":reservoir_hits,"web_searches":0
        }

    sem=asyncio.Semaphore(AUTHOR_RESEARCH_CONCURRENCY)
    async def verify_pool(p):
        async with sem:
            d=await _contact_research(p["name"],country_term or p.get("country") or "",genre or p.get("genre") or "",p.get("discovery_url") or "")
            passed=(not require_website or bool(d.get("website"))) and (not require_email or bool(d.get("email")))
            if passed:d=await _enrich_activity(d)
            await asyncio.to_thread(_mark_pool_verified,int(p["id"]),d,passed)
            return p,d,passed

    pool_tasks=[asyncio.create_task(verify_pool(p)) for p in remaining[:max(count*6,30)]]
    if pool_tasks:
        for fut in asyncio.as_completed(pool_tasks):
            try:p,d,passed=await fut
            except Exception:
                checked+=1;continue
            checked+=1
            if d.get("website"):with_website+=1
            if d.get("email"):with_email+=1
            if passed:
                nk=_norm_author_name(d.get("name") or "")
                if nk and nk not in accepted_names:
                    accepted_names.add(nk);out.append(d);reservoir_hits+=1
                    legacy.execq("UPDATE author_candidate_pool SET times_selected=times_selected+1,updated_at=:t WHERE id=:i",t=legacy.iso(),i=p["id"])
            if progress and (checked%5==0 or len(out)>=count):
                await progress(f"🔬 <b>Reservoir verification</b>\\nChecked: {checked}\\nAccepted: <b>{len(out)}</b> / {count}")
            if len(out)>=count:break
        if len(out)>=count:
            for task in pool_tasks:
                if not task.done():task.cancel()
        await asyncio.gather(*pool_tasks,return_exceptions=True)

    if len(out)>=count:
        seconds=time.monotonic()-started
        return out[:count],{
            "raw_results":0,"candidates":len(pool),"checked":checked,"with_email":with_email,
            "with_website":with_website,"query":base,"queries":queries_used,
            "elapsed_seconds":round(seconds,2),"reservoir_hits":reservoir_hits,"web_searches":0
        }

    if progress:
        await progress(f"🌐 <b>Reservoir needs {count-len(out)} more</b>\\nRunning fresh discovery while saving new identities back into Neon.")
    result_sets=await asyncio.gather(*(fast_search(q,max(12,count*2)) for q in web_queries),return_exceptions=True)
    queries_used.extend(web_queries)
    fresh=[]
    fresh_seen=set()
    for q,rs in zip(web_queries,result_sets):
        if isinstance(rs,Exception):continue
        raw_results+=len(rs)
        for r in rs:
            n=legacy.cand(r.get("title",""),r.get("snippet",""))
            if not n:continue
            if name_filter:
                wanted=[x.lower() for x in re.findall(r"[A-Za-zÀ-ÿ'’-]+",name_filter)]
                if wanted and not all(x in n.lower() for x in wanted):continue
            nk=_norm_author_name(n)
            if not nk or nk in accepted_names or nk in existing_names or nk in fresh_seen:continue
            pid=await asyncio.to_thread(_upsert_pool_candidate,n,country_term,genre,r.get("url") or "",r.get("url") or "",
                                        "search_result",q,r.get("snippet") or "")
            if not pid:continue
            fresh_seen.add(nk)
            fresh.append({"id":pid,"name":n,"country":country_term,"genre":genre,"discovery_url":r.get("url") or ""})

    fresh_tasks=[asyncio.create_task(verify_pool(p)) for p in fresh[:max(count*6,30)]]
    for fut in asyncio.as_completed(fresh_tasks):
        try:p,d,passed=await fut
        except Exception:
            checked+=1;continue
        checked+=1
        if d.get("website"):with_website+=1
        if d.get("email"):with_email+=1
        if passed:
            nk=_norm_author_name(d.get("name") or "")
            if nk and nk not in accepted_names:
                accepted_names.add(nk);out.append(d)
                legacy.execq("UPDATE author_candidate_pool SET times_selected=times_selected+1,updated_at=:t WHERE id=:i",t=legacy.iso(),i=p["id"])
        if progress and (checked%5==0 or len(out)>=count):
            await progress(f"🚀 <b>Fresh verification</b>\\nChecked: {checked}\\nAccepted: <b>{len(out)}</b> / {count}\\nNew identities stored: {len(fresh)}")
        if len(out)>=count:break
    if len(out)>=count:
        for task in fresh_tasks:
            if not task.done():task.cancel()
    await asyncio.gather(*fresh_tasks,return_exceptions=True)

    seconds=time.monotonic()-started
    print(f"RESERVOIR_FIND_DONE seconds={seconds:.2f} pool={len(pool)} raw={raw_results} fresh={len(fresh)} checked={checked} accepted={len(out)}")
    return out[:count],{
        "raw_results":raw_results,"candidates":len(pool)+len(fresh),"checked":checked,
        "with_email":with_email,"with_website":with_website,"query":base,"queries":queries_used,
        "elapsed_seconds":round(seconds,2),"reservoir_hits":reservoir_hits,
        "web_searches":len(web_queries) if raw_results else 0
    }


legacy.research = fast_research
legacy.find_authors = fast_find_authors


# ---------------------------------------------------------------------------
# LinkedIn Connection Intelligence
# ---------------------------------------------------------------------------

async def research_owner_profile(profile_url: str) -> str:
    slug = _profile_slug(profile_url)
    queries = [f'"{profile_url}"', f'site:linkedin.com/in "{slug}"']
    sets = await asyncio.gather(*(legacy.search(q, 5) for q in queries), return_exceptions=True)
    parts = []
    for rs in sets:
        if isinstance(rs, Exception):
            continue
        for r in rs:
            if "linkedin.com/in/" in (r.get("url") or ""):
                parts.append((r.get("title") or "") + " " + (r.get("snippet") or ""))
    context = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if not context:
        context = slug
    return context[:3500]


def _parse_connection_prefs(arg: str) -> dict:
    out = {}
    for m in re.finditer(r"(?i)\b(countries|exclude|min|target|query)\s*=\s*([^;]+)", arg or ""):
        k, v = m.group(1).lower(), m.group(2).strip()
        out[k] = v
    return out


def _fit_score(pref: dict, candidate: dict) -> tuple[int, str, str]:
    text_value = " ".join([
        candidate.get("name", ""), candidate.get("headline", ""), candidate.get("company", ""),
        candidate.get("location", ""), candidate.get("country", ""), candidate.get("snippet", ""),
    ]).lower()
    country = (candidate.get("country") or "").strip()
    excluded = {x.lower() for x in json.loads(pref.get("excluded_countries") or "[]")}
    if country.lower() in excluded:
        return 0, f"Excluded public location: {country}", "hard_exclusion=country"

    # Never infer nationality/ethnicity from a name, image, language, or wording.
    # Country is accepted only when supported by public professional-location evidence.
    if not country:
        return 0, "Public professional location could not be verified", "hard_exclusion=unverified_location"

    owner_context = (pref.get("profile_context") or "") + " " + (pref.get("target_query") or "")
    owner_tokens = set(_tokens(owner_context, 18))
    candidate_tokens = set(_tokens(text_value, 24))
    overlap = owner_tokens & candidate_tokens

    score = 20  # valid public LinkedIn profile + verified target geography
    if candidate.get("headline"):
        score += 10
    if candidate.get("snippet"):
        score += 5

    overlap_points = min(35, len(overlap) * 7)
    score += overlap_points
    role_hits = sorted(candidate_tokens & _ROLE_TERMS)
    if role_hits:
        score += min(20, len(role_hits) * 5)
    senior_hits = sorted(candidate_tokens & _SENIORITY_TERMS)
    if senior_hits:
        score += min(10, len(senior_hits) * 5)

    score = min(100, score)
    reasons = []
    if overlap:
        reasons.append("shared professional themes: " + ", ".join(sorted(list(overlap))[:5]))
    if role_hits:
        reasons.append("relevant role/sector signals: " + ", ".join(role_hits[:5]))
    if senior_hits:
        reasons.append("decision/influence signal: " + ", ".join(senior_hits[:3]))
    reasons.append(f"public professional location: {country}")
    evidence = json.dumps({
        "engine": "Connection Fit Intelligence v1",
        "prompt_loaded": bool(_prompt_text()),
        "overlap": sorted(list(overlap))[:10],
        "role_hits": role_hits[:10],
        "seniority_hits": senior_hits[:10],
        "country": country,
    }, ensure_ascii=False)
    return score, "; ".join(reasons), evidence


def _extract_linkedin_candidate(result: dict, target_country: str, source_query: str) -> dict | None:
    url = _canon_linkedin(result.get("url") or "")
    if not url:
        return None
    title = re.sub(r"\s+", " ", result.get("title") or "").strip()
    snippet = re.sub(r"\s+", " ", result.get("snippet") or "").strip()
    combined = f"{title} {snippet}"

    # Require explicit public-location support for the country used to find the profile.
    if target_country and not re.search(rf"\b{re.escape(target_country)}\b", combined, re.I):
        aliases = {
            "United States": ["USA", "U.S.", "United States"],
            "United Kingdom": ["UK", "U.K.", "United Kingdom", "England", "Scotland", "Wales", "Northern Ireland"],
            "United Arab Emirates": ["UAE", "United Arab Emirates", "Dubai", "Abu Dhabi"],
        }
        if not any(re.search(rf"\b{re.escape(a)}\b", combined, re.I) for a in aliases.get(target_country, [])):
            return None

    clean_title = re.sub(r"\s*[|·-]\s*LinkedIn\s*$", "", title, flags=re.I).strip()
    parts = re.split(r"\s+[–—-]\s+", clean_title, maxsplit=1)
    name = parts[0].strip() if parts else ""
    headline = parts[1].strip() if len(parts) > 1 else ""
    if not name or len(name) > 100:
        return None
    company = ""
    m = re.search(r"(?i)\bat\s+([^|·,]+)", headline)
    if m:
        company = m.group(1).strip()
    return {
        "profile_url": url, "normalized_url": url.lower().rstrip("/"), "name": name,
        "headline": headline, "company": company, "location": target_country,
        "country": target_country, "snippet": snippet[:1200], "source_query": source_query,
    }


def _get_or_create_profile(candidate: dict, score: int, reason: str, evidence: str) -> int:
    ex = legacy.row("SELECT id FROM connection_profiles WHERE normalized_url=:u", u=candidate["normalized_url"])
    t = legacy.iso()
    if ex:
        legacy.execq(
            """UPDATE connection_profiles SET profile_url=:pu,name=:n,headline=:h,company=:co,location=:l,country=:c,
               snippet=:s,source_query=:q,fit_score=:fs,fit_reason=:fr,fit_evidence=:fe,last_verified_at=:t WHERE id=:i""",
            pu=candidate["profile_url"], n=candidate["name"], h=candidate["headline"], co=candidate["company"],
            l=candidate["location"], c=candidate["country"], s=candidate["snippet"], q=candidate["source_query"],
            fs=score, fr=reason, fe=evidence, t=t, i=ex["id"],
        )
        return int(ex["id"])
    try:
        with legacy.engine.begin() as c:
            r = c.execute(text("""INSERT INTO connection_profiles(
                normalized_url,profile_url,name,headline,company,location,country,snippet,source_query,
                fit_score,fit_reason,fit_evidence,discovered_at,last_verified_at)
                VALUES(:u,:pu,:n,:h,:co,:l,:c,:s,:q,:fs,:fr,:fe,:t,:t) RETURNING id"""), {
                "u": candidate["normalized_url"], "pu": candidate["profile_url"], "n": candidate["name"],
                "h": candidate["headline"], "co": candidate["company"], "l": candidate["location"],
                "c": candidate["country"], "s": candidate["snippet"], "q": candidate["source_query"],
                "fs": score, "fr": reason, "fe": evidence, "t": t,
            })
            return int(r.scalar_one())
    except Exception:
        ex = legacy.row("SELECT id FROM connection_profiles WHERE normalized_url=:u", u=candidate["normalized_url"])
        return int(ex["id"]) if ex else 0


def _reserve_profile(profile_id: int, team_id: int, user_id: int) -> bool:
    if not profile_id:
        return False
    t = legacy.iso()
    try:
        with legacy.engine.begin() as c:
            if CONN_GLOBAL_EXCLUSIVE:
                c.execute(text("INSERT INTO connection_global_claims(profile_id,team_id,telegram_user_id,claimed_at) VALUES(:p,:t,:u,:d)"), {"p": profile_id, "t": team_id, "u": user_id, "d": t})
            c.execute(text("""INSERT INTO connection_assignments(profile_id,team_id,assigned_user_id,status,assigned_at,updated_at)
                VALUES(:p,:t,:u,'ready',:d,:d)"""), {"p": profile_id, "t": team_id, "u": user_id, "d": t})
        return True
    except Exception:
        return False


def _ready_count(user_id: int) -> int:
    r = legacy.row("SELECT COUNT(*) c FROM connection_assignments WHERE assigned_user_id=:u AND status IN ('ready','saved')", u=user_id)
    return int((r or {"c": 0})["c"])


def _search_terms(pref: dict) -> list[str]:
    if (pref.get("target_query") or "").strip():
        terms = _tokens(pref["target_query"], 8)
    else:
        terms = _tokens(pref.get("profile_context") or "", 10)
    useful = [x for x in terms if x not in _STOPWORDS]
    if not useful:
        useful = ["author", "publishing", "writer", "editor", "literary", "books"]
    return useful[:6]


async def discover_connection_candidates(pref: dict, wanted: int) -> list[dict]:
    countries = json.loads(pref.get("target_countries") or "[]") or CONN_DEFAULT_COUNTRIES
    excluded = {x.lower() for x in json.loads(pref.get("excluded_countries") or "[]")}
    countries = [c for c in countries if c.lower() not in excluded]
    terms = _search_terms(pref)
    # Rotate by user + current minute so thousands of users do not all issue identical routes.
    seed = int(pref["telegram_user_id"]) + int(legacy.now().timestamp() // 300)
    countries = sorted(countries, key=lambda x: hash((seed, x)))
    terms = sorted(terms, key=lambda x: hash((seed, x)))
    routes = []
    for country in countries[:4]:
        for term in terms[:3]:
            routes.append((country, f'site:linkedin.com/in "{term}" "{country}"'))
    routes = routes[:8]

    sem = asyncio.Semaphore(CONN_CONCURRENCY)

    async def run_route(country, q):
        async with sem:
            try:
                return country, q, await legacy.search(q, max(10, min(30, wanted * 2)))
            except Exception:
                return country, q, []

    batches = await asyncio.gather(*(run_route(c, q) for c, q in routes))
    seen = set()
    out = []
    for country, q, results in batches:
        for r in results:
            candidate = _extract_linkedin_candidate(r, country, q)
            if not candidate or candidate["normalized_url"] in seen:
                continue
            public_text = f"{candidate.get('headline','')} {candidate.get('snippet','')} {candidate.get('location','')}"
            if any(re.search(rf"\b{re.escape(x)}\b", public_text, re.I) for x in json.loads(pref.get("excluded_countries") or "[]")):
                continue
            seen.add(candidate["normalized_url"])
            out.append(candidate)
    return out


async def replenish_user(user_id: int) -> dict:
    pref = legacy.row("SELECT * FROM connection_preferences WHERE telegram_user_id=:u AND enabled=1", u=user_id)
    if not pref:
        return {"added": 0, "ready": 0}
    current = await asyncio.to_thread(_ready_count, user_id)
    target = int(pref.get("ready_target") or CONN_READY_TARGET)
    need = max(0, target - current)
    if need <= 0:
        return {"added": 0, "ready": current}
    wanted = min(max(need, CONN_BATCH_SIZE), CONN_BATCH_SIZE * 2)
    added = 0
    try:
        candidates = await discover_connection_candidates(pref, wanted)
        min_score = int(pref.get("min_score") or CONN_MIN_SCORE)
        for candidate in candidates:
            if added >= need:
                break
            # Team-level suppression before scoring/storage.
            existing = legacy.row("""SELECT ca.id FROM connection_assignments ca
                JOIN connection_profiles cp ON cp.id=ca.profile_id
                WHERE ca.team_id=:t AND cp.normalized_url=:u LIMIT 1""", t=pref["team_id"], u=candidate["normalized_url"])
            if existing:
                continue
            score, reason, evidence = _fit_score(pref, candidate)
            if score < min_score:
                continue
            pid = await asyncio.to_thread(_get_or_create_profile, candidate, score, reason, evidence)
            if await asyncio.to_thread(_reserve_profile, pid, int(pref["team_id"]), user_id):
                added += 1
        legacy.execq("UPDATE connection_preferences SET last_refill_at=:d,last_error='',updated_at=:d WHERE telegram_user_id=:u", d=legacy.iso(), u=user_id)
    except Exception as e:
        legacy.execq("UPDATE connection_preferences SET last_refill_at=:d,last_error=:e,updated_at=:d WHERE telegram_user_id=:u", d=legacy.iso(), e=f"{type(e).__name__}: {e}"[:500], u=user_id)
    return {"added": added, "ready": await asyncio.to_thread(_ready_count, user_id)}


async def connection_worker():
    await asyncio.sleep(5)
    while True:
        try:
            prefs = legacy.rows("""SELECT * FROM connection_preferences WHERE enabled=1
                ORDER BY CASE WHEN last_refill_at='' THEN 0 ELSE 1 END, last_refill_at ASC
                LIMIT :n""", n=CONN_USERS_PER_CYCLE)
            for pref in prefs:
                try:
                    if _ready_count(int(pref["telegram_user_id"])) < int(pref.get("ready_target") or CONN_READY_TARGET):
                        await replenish_user(int(pref["telegram_user_id"]))
                except Exception as e:
                    print(f"CONNECTION_WORKER_USER_ERROR uid={pref.get('telegram_user_id')} {type(e).__name__}: {e}")
            await asyncio.sleep(CONN_INTERVAL)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"CONNECTION_WORKER_ERROR {type(e).__name__}: {e}")
            await asyncio.sleep(CONN_INTERVAL)


def enhanced_main_menu():
    base = _legacy_main_menu()
    kb = list(base.get("inline_keyboard", []))
    kb.insert(1, [{"text": "🌐 Connections", "callback_data": "conn:menu"}, {"text": "📈 Connection Status", "callback_data": "conn:status"}])
    return {"inline_keyboard": kb}


async def show_connection_status(chat: int, uid: int):
    pref = legacy.row("SELECT * FROM connection_preferences WHERE telegram_user_id=:u", u=uid)
    if not pref:
        return await legacy.send(chat, "🌐 Connection Intelligence is not configured yet.\nUse <code>/connectsetup YOUR_LINKEDIN_PROFILE_URL</code>.", enhanced_main_menu())
    stats = legacy.rows("SELECT status,COUNT(*) c FROM connection_assignments WHERE assigned_user_id=:u GROUP BY status", u=uid)
    d = {r["status"]: int(r["c"]) for r in stats}
    countries = ", ".join(json.loads(pref.get("target_countries") or "[]"))
    return await legacy.send(chat,
        f"<b>🌐 Connection Intelligence</b>\n"
        f"Background research: <b>{'ON' if pref['enabled'] else 'OFF'}</b>\n"
        f"Ready now: <b>{d.get('ready',0) + d.get('saved',0)}</b>\n"
        f"Connected / archived: <b>{d.get('connected',0)}</b>\n"
        f"Skipped: <b>{d.get('skipped',0)}</b>\n"
        f"Not relevant: <b>{d.get('not_relevant',0)}</b>\n"
        f"Ready target: <b>{pref['ready_target']}</b>\n"
        f"Minimum fit: <b>{pref['min_score']}/100</b>\n"
        f"Countries: {legacy.esc(countries or 'default non-Nigeria markets')}\n"
        f"Last refill: {legacy.esc(pref.get('last_refill_at') or 'not yet')}\n"
        f"Last error: {legacy.esc(pref.get('last_error') or 'none')}"
    )


async def show_connections(chat: int, uid: int, limit: int = CONN_DISPLAY_COUNT):
    pref = legacy.row("SELECT * FROM connection_preferences WHERE telegram_user_id=:u AND enabled=1", u=uid)
    if not pref:
        return await legacy.send(chat, "Set up your LinkedIn profile first:\n<code>/connectsetup https://www.linkedin.com/in/your-profile</code>")
    rs = legacy.rows("""SELECT ca.id assignment_id,ca.status,cp.* FROM connection_assignments ca
        JOIN connection_profiles cp ON cp.id=ca.profile_id
        WHERE ca.assigned_user_id=:u AND ca.status IN ('ready','saved')
        ORDER BY CASE WHEN ca.status='saved' THEN 0 ELSE 1 END, cp.fit_score DESC, ca.id ASC LIMIT :n""", u=uid, n=limit)
    if not rs:
        asyncio.create_task(replenish_user(uid))
        return await legacy.send(chat, "No ready profiles at this exact moment. Background research is active and the queue will refill automatically.")
    for p in rs:
        legacy.execq("UPDATE connection_assignments SET viewed_at=CASE WHEN viewed_at='' THEN :d ELSE viewed_at END,updated_at=:d WHERE id=:i", d=legacy.iso(), i=p["assignment_id"])
        kb = {"inline_keyboard": [
            [{"text": "🔗 Open LinkedIn", "url": p["profile_url"]}],
            [{"text": "✅ Mark Connected", "callback_data": f"conn:done:{p['assignment_id']}"}, {"text": "⏭ Skip", "callback_data": f"conn:skip:{p['assignment_id']}"}],
            [{"text": "🚫 Not Relevant", "callback_data": f"conn:no:{p['assignment_id']}"}, {"text": "💾 Save", "callback_data": f"conn:save:{p['assignment_id']}"}],
        ]}
        await legacy.send(chat,
            f"<b>{legacy.esc(p['name'])}</b>\n"
            f"{legacy.esc(p['headline'] or 'LinkedIn professional')}\n"
            f"📍 {legacy.esc(p['country'])}\n"
            f"Fit: <b>{p['fit_score']}/100</b>\n"
            f"Why: {legacy.esc(p['fit_reason'])}", kb)
    return await legacy.send(chat, f"Showing <b>{len(rs)}</b> of <b>{_ready_count(uid)}</b> ready profiles.", {"inline_keyboard":[[{"text":"➡️ Show Connections","callback_data":"conn:menu"},{"text":"📈 Status","callback_data":"conn:status"}]]})


async def setup_connections(chat: int, uid: int, arg: str):
    tm = legacy.team(uid)
    if not tm:
        return await legacy.send(chat, "Join or create a team first.")
    parts = [x.strip() for x in (arg or "").split("|", 1)]
    profile_url = _canon_linkedin(parts[0] if parts else "")
    if not profile_url:
        return await legacy.send(chat, "Use:\n<code>/connectsetup https://www.linkedin.com/in/your-profile</code>\nOptional focus:\n<code>/connectsetup URL | publishing authors literary agents</code>")
    focus = parts[1] if len(parts) > 1 else ""
    msg = await legacy.send(chat, "🔎 Reading your public professional positioning and preparing Connection Intelligence…")
    context = await research_owner_profile(profile_url)
    t = legacy.iso()
    countries = json.dumps(CONN_DEFAULT_COUNTRIES)
    excluded = json.dumps(CONN_EXCLUDED_COUNTRIES)
    ex = legacy.row("SELECT telegram_user_id FROM connection_preferences WHERE telegram_user_id=:u", u=uid)
    if ex:
        legacy.execq("""UPDATE connection_preferences SET team_id=:tid,linkedin_profile_url=:p,profile_context=:c,target_query=:q,
            target_countries=:tc,excluded_countries=:ec,min_score=:ms,ready_target=:rt,enabled=1,updated_at=:d WHERE telegram_user_id=:u""",
            tid=tm["id"], p=profile_url, c=context, q=focus, tc=countries, ec=excluded, ms=CONN_MIN_SCORE, rt=CONN_READY_TARGET, d=t, u=uid)
    else:
        legacy.execq("""INSERT INTO connection_preferences(telegram_user_id,team_id,linkedin_profile_url,profile_context,target_query,
            target_countries,excluded_countries,min_score,ready_target,enabled,last_refill_at,last_error,created_at,updated_at)
            VALUES(:u,:tid,:p,:c,:q,:tc,:ec,:ms,:rt,1,'','',:d,:d)""",
            u=uid, tid=tm["id"], p=profile_url, c=context, q=focus, tc=countries, ec=excluded, ms=CONN_MIN_SCORE, rt=CONN_READY_TARGET, d=t)
    asyncio.create_task(replenish_user(uid))
    return await legacy.send(chat,
        f"✅ <b>Connection Intelligence enabled</b>\n"
        f"Profile: {legacy.esc(profile_url)}\n"
        f"Ready-pool target: <b>{CONN_READY_TARGET}</b>\n"
        f"Minimum fit: <b>{CONN_MIN_SCORE}/100</b>\n"
        f"Excluded public location: <b>{legacy.esc(', '.join(CONN_EXCLUDED_COUNTRIES))}</b>\n\n"
        f"Research now continues in the background. Tap <b>Connections</b> whenever you want the profiles currently ready.",
        enhanced_main_menu())


async def update_connection_prefs(chat: int, uid: int, arg: str):
    pref = legacy.row("SELECT * FROM connection_preferences WHERE telegram_user_id=:u", u=uid)
    if not pref:
        return await legacy.send(chat, "Run /connectsetup first.")
    vals = _parse_connection_prefs(arg)
    countries = json.loads(pref["target_countries"] or "[]")
    excluded = json.loads(pref["excluded_countries"] or "[]")
    min_score = int(pref["min_score"])
    target = int(pref["ready_target"])
    query = pref.get("target_query") or ""
    if "countries" in vals:
        countries = [x.strip() for x in vals["countries"].split(",") if x.strip()]
    if "exclude" in vals:
        excluded = [x.strip() for x in vals["exclude"].split(",") if x.strip()]
    if "min" in vals:
        try: min_score = max(1, min(100, int(vals["min"])))
        except Exception: pass
    if "target" in vals:
        try: target = max(5, min(500, int(vals["target"])))
        except Exception: pass
    if "query" in vals:
        query = vals["query"]
    legacy.execq("""UPDATE connection_preferences SET target_countries=:tc,excluded_countries=:ec,min_score=:m,
        ready_target=:r,target_query=:q,updated_at=:d WHERE telegram_user_id=:u""",
        tc=json.dumps(countries), ec=json.dumps(excluded), m=min_score, r=target, q=query, d=legacy.iso(), u=uid)
    asyncio.create_task(replenish_user(uid))
    return await legacy.send(chat, "✅ Connection preferences updated. Background research will use the new criteria.")


async def handle_connection_callback(update: dict) -> bool:
    cq = update.get("callback_query") or {}
    if not cq:
        return False
    data = cq.get("data") or ""
    if not data.startswith("conn:"):
        return False
    u = cq.get("from") or {}
    uid = legacy.ensure_user(u)
    chat = ((cq.get("message") or {}).get("chat") or {}).get("id")
    message_id = (cq.get("message") or {}).get("message_id")
    if not chat:
        return True
    tm = legacy.team(uid)
    if not tm:
        await legacy.send(chat, "Join or create a team first.")
        return True
    if data == "conn:menu":
        await show_connections(chat, uid)
        return True
    if data == "conn:status":
        await show_connection_status(chat, uid)
        return True
    parts = data.split(":")
    if len(parts) != 3:
        return True
    action, assignment_id = parts[1], int(parts[2])
    a = legacy.row("SELECT * FROM connection_assignments WHERE id=:i AND assigned_user_id=:u AND team_id=:t", i=assignment_id, u=uid, t=tm["id"])
    if not a:
        await legacy.send(chat, "That connection assignment is no longer available.")
        return True
    t = legacy.iso()
    if action == "done":
        legacy.execq("UPDATE connection_assignments SET status='connected',connected_at=:d,archived_at=:d,updated_at=:d WHERE id=:i", d=t, i=assignment_id)
        event = "connected"
        label = "✅ Connected and archived"
    elif action == "skip":
        legacy.execq("UPDATE connection_assignments SET status='skipped',skipped_at=:d,archived_at=:d,updated_at=:d WHERE id=:i", d=t, i=assignment_id)
        event = "skipped"
        label = "⏭ Skipped and archived"
    elif action == "no":
        legacy.execq("UPDATE connection_assignments SET status='not_relevant',archived_at=:d,updated_at=:d WHERE id=:i", d=t, i=assignment_id)
        event = "not_relevant"
        label = "🚫 Marked not relevant and archived"
    elif action == "save":
        legacy.execq("UPDATE connection_assignments SET status='saved',updated_at=:d WHERE id=:i", d=t, i=assignment_id)
        event = "saved"
        label = "💾 Saved for later"
    else:
        return True
    legacy.execq("INSERT INTO connection_events(profile_id,team_id,telegram_user_id,event_type,created_at) VALUES(:p,:t,:u,:e,:d)", p=a["profile_id"], t=tm["id"], u=uid, e=event, d=t)
    if message_id:
        await legacy.edit_msg(chat, message_id, label)
    else:
        await legacy.send(chat, label)
    if action in {"done", "skip", "no"}:
        asyncio.create_task(replenish_user(uid))
    return True


_legacy_handle = legacy.handle
_legacy_main_menu = legacy.main_menu
legacy.main_menu = enhanced_main_menu


async def enhanced_handle(update: dict):
    if await handle_connection_callback(update):
        return
    m = update.get("message") or {}
    txt = (m.get("text") or "").strip()
    if txt.startswith("/"):
        parts = txt.split(maxsplit=1)
        cmd = parts[0].split("@")[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        u = m.get("from") or {}
        chat = (m.get("chat") or {}).get("id")
        if chat and u.get("id"):
            uid = legacy.ensure_user(u)
            if cmd == "/connections":
                return await show_connections(chat, uid)
            if cmd == "/connectionstatus":
                return await show_connection_status(chat, uid)
            if cmd == "/connectsetup":
                return await setup_connections(chat, uid, arg)
            if cmd == "/connectionprefs":
                return await update_connection_prefs(chat, uid, arg)
    return await _legacy_handle(update)


legacy.handle = enhanced_handle


@app.on_event("startup")
async def connection_startup():
    global _http_client
    init_connection_db()
    if _http_client is None:
        _http_client = legacy.httpx.AsyncClient(
            timeout=legacy.TIMEOUT, headers=legacy.HEADERS, follow_redirects=True,
            limits=legacy.httpx.Limits(max_connections=HTTP_MAX_CONNECTIONS, max_keepalive_connections=HTTP_KEEPALIVE_CONNECTIONS),
        )
    try:
        if legacy.TOKEN:
            await legacy.tg("setMyCommands", {"commands": json.dumps([
                {"command": "menu", "description": "Open Author Scout menu"},
                {"command": "find", "description": "Scout authors using filters or natural language"},
                {"command": "connections", "description": "Show qualified LinkedIn connections ready now"},
                {"command": "connectsetup", "description": "Set your LinkedIn profile for background connection research"},
                {"command": "connectionstatus", "description": "Show ready, connected and archived connection counts"},
                {"command": "connectionprefs", "description": "Tune connection markets, fit threshold and ready target"},
                {"command": "authors", "description": "Show recently scouted authors"},
                {"command": "lastsearch", "description": "Show exact last search routes"},
                {"command": "export", "description": "Download ChatGPT-ready author workbook"},
                {"command": "queue", "description": "Open ready outreach messages"},
                {"command": "campaign", "description": "Show authors, sent and reply totals"},
                {"command": "replies", "description": "Mark author replies"},
                {"command": "gmail", "description": "Connect Gmail / deliverability settings"},
                {"command": "autosend", "description": "Automatic sending status"},
                {"command": "team", "description": "Show team and invite code"},
                {"command": "howto", "description": "Complete Author Scout workflow guide"},
                {"command": "help", "description": "Show help"},
            ])})
    except Exception as e:
        print(f"CONNECTION_COMMAND_SETUP_ERROR {type(e).__name__}: {e}")
    app.state.connection_worker = asyncio.create_task(connection_worker())
    print("CONNECTION_WORKER started=True")


@app.on_event("shutdown")
async def connection_shutdown():
    global _http_client
    task = getattr(app.state, "connection_worker", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if _http_client is not None:
        try:
            await _http_client.aclose()
        except Exception:
            pass
        _http_client = None