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
    count = spec["count"]
    country = spec.get("country", "")
    genre = spec.get("genre", "")
    gender = spec.get("gender", "any")
    name_filter = spec.get("name", "")
    language = spec.get("language", "")
    year = spec.get("year", "")
    free_query = spec.get("query", "")
    require_email = spec.get("require_email", True)
    require_website = spec.get("require_website", True)
    country_term = _COUNTRY_ALIASES.get((country or "").strip().lower(), country)

    intent_parts = []
    if name_filter: intent_parts.append(f'"{name_filter}"')
    if free_query: intent_parts.append(free_query)
    if country_term: intent_parts.append(country_term)
    if genre: intent_parts.append(genre)
    if language: intent_parts.append(language)
    if gender in {"male", "female"}: intent_parts.append(gender)
    base = " ".join(dict.fromkeys([x.strip() for x in intent_parts if x.strip()])).strip() or "author"
    activity_year = year or str(legacy.YEAR)
    queries = [
        f'{base} author official website contact email',
        f'{base} writer novelist official site',
        f'{base} author {activity_year} release event',
    ]

    started = time.monotonic()
    if progress:
        await progress(f"⚡ <b>Fast scout started</b>\nRunning discovery routes together for: {legacy.esc(base)}")
    result_sets = await asyncio.gather(*(fast_search(q, max(12, count * 2)) for q in queries), return_exceptions=True)
    seen, cands = set(), []
    raw_results = 0
    # One database read replaces one duplicate query per candidate.
    if country_term:
        existing_rows = await asyncio.to_thread(legacy.rows,
            "SELECT name FROM prospects WHERE lower(country)=lower(:c)", c=country_term)
    else:
        existing_rows = await asyncio.to_thread(legacy.rows, "SELECT name FROM prospects")
    existing_names = {re.sub(r"[^a-z0-9]", "", (r.get("name") or "").lower()) for r in existing_rows}
    for rs in result_sets:
        if isinstance(rs, Exception):
            continue
        raw_results += len(rs)
        for r in rs:
            n = legacy.cand(r.get("title", ""), r.get("snippet", ""))
            if not n:
                continue
            if name_filter:
                wanted = [x.lower() for x in re.findall(r"[A-Za-zÀ-ÿ'’-]+", name_filter)]
                if wanted and not all(x in n.lower() for x in wanted):
                    continue
            k = re.sub(r"[^a-z0-9]", "", n.lower())
            if not k or k in seen:
                continue
            # Reject globally-known duplicate identities before network verification.
            if k in existing_names:
                continue
            seen.add(k)
            cands.append((n, r.get("url") or ""))

    max_check = min(len(cands), max(count * 6, 30))
    if progress:
        await progress(f"📋 <b>{len(cands)} new candidate identities</b>\nVerifying public website + email with up to {AUTHOR_RESEARCH_CONCURRENCY} concurrent workers.")

    checked = with_email = with_website = 0
    out = []
    sem = asyncio.Semaphore(AUTHOR_RESEARCH_CONCURRENCY)

    async def verify_one(n, h):
        async with sem:
            d = await _contact_research(n, country_term, genre, h)
            # Fail fast before spending another search on activity.
            if require_website and not d.get("website"):
                return d, False
            if require_email and not d.get("email"):
                return d, False
            d = await _enrich_activity(d)
            return d, True

    tasks = [asyncio.create_task(verify_one(n, h)) for n, h in cands[:max_check]]
    last_progress = 0
    try:
        for fut in asyncio.as_completed(tasks):
            try:
                d, qualified = await fut
            except Exception:
                checked += 1
                continue
            checked += 1
            if d.get("website"): with_website += 1
            if d.get("email"): with_email += 1
            if qualified:
                out.append(d)
            if progress and (checked - last_progress >= 5 or len(out) >= count):
                last_progress = checked
                await progress(
                    f"🔬 <b>High-speed verification</b>\nChecked: {checked}/{max_check}\n"
                    f"Accepted: <b>{len(out)}</b> / {count}\nWebsites: {with_website}\nPublic emails: {with_email}"
                )
            if len(out) >= count:
                break
    finally:
        if len(out) >= count:
            for task in tasks:
                if not task.done():
                    task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    seconds = time.monotonic() - started
    print(f"FAST_FIND_DONE seconds={seconds:.2f} raw={raw_results} candidates={len(cands)} checked={checked} accepted={len(out)}")
    return out[:count], {
        "raw_results": raw_results, "candidates": len(cands), "checked": checked,
        "with_email": with_email, "with_website": with_website, "query": base, "queries": queries,
        "elapsed_seconds": round(seconds, 2),
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