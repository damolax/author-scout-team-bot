"""Letter Desk 2.0 — Phase 3 public-web scout, adapted from Scout source discovery.

Deliberately bounded and evidence-first:
* Six service-specific query plans, not one template for every sector.
* DNS/URL/robots checks before fetching a business site; no login-walled pages.
* Never guesses email addresses or marks them delivery-verified.
* Collected evidence is for review, not authorization to send.
* Google Maps discovery requires the official Places API (separate adapter).
"""
from __future__ import annotations
import ipaddress
import re
import socket
from dataclasses import dataclass, asdict
from urllib.parse import urljoin, urlparse, urlunparse, unquote
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

SERVICE_DEFINITIONS = {
    "author": {
        "label": "Author Scouting",
        "angles": ["author recent book publication", "writer interview literary event", "independent novelist new release", "literary magazine contributor"],
        "signals": ["books", "novel", "author", "poetry", "essay", "publication", "interview"],
        "directory_exclusions": ["goodreads.com", "amazon.com", "wikipedia.org"],
    },
    "automation": {
        "label": "Automation Scouting",
        "angles": ["business manual spreadsheet process", "company operations and forms", "service business appointment workflow", "business onboarding team process"],
        "signals": ["workflow", "manual", "booking", "spreadsheet", "appointment", "forms", "operations", "integrations"],
        "directory_exclusions": [],
    },
    "website-design": {
        "label": "Website Design Scouting",
        "angles": ["business official website contact", "local service company website", "agency company services contact", "growing small business new website"],
        "signals": ["website", "services", "portfolio", "contact", "book", "about"],
        "directory_exclusions": [],
    },
    "digital-planner": {
        "label": "Digital Planner Scouting",
        "angles": ["digital planner creator shop", "printable planner templates creator", "Notion planner digital templates shop", "digital stationery business"],
        "signals": ["planner", "digital download", "printable", "template", "etsy", "shop"],
        "directory_exclusions": ["etsy.com", "pinterest.com"],
    },
    "shopify": {
        "label": "Shopify Scouting",
        "angles": ["independent ecommerce store products", "shopify brand new collection", "online shop contact store", "direct to consumer emerging brand"],
        "signals": ["products", "cart", "checkout", "collection", "shopify", "shipping", "returns"],
        "directory_exclusions": ["shopify.com", "apps.shopify.com"],
    },
    "google-maps": {
        "label": "Google Maps Scouting",
        "angles": ["local businesses Google Business Profile", "local services official website", "restaurants cafes professional contact", "local business location services"],
        "signals": ["address", "opening hours", "location", "services", "directions", "contact"],
        "directory_exclusions": [],
    },
}
# Never mistake a platform, search engine, or news article for a direct prospect's site.
BLOCK_HOSTS = {
    "google.com", "bing.com", "duckduckgo.com", "facebook.com", "instagram.com",
    "linkedin.com", "tiktok.com", "twitter.com", "x.com", "youtube.com",
    "yelp.com", "tripadvisor.com", "medium.com", "reddit.com", "quora.com",
    "wikipedia.org", "amazon.com", "goodreads.com", "pinterest.com",
    "shopify.com", "etsy.com", "clutch.co", "crunchbase.com", "apps.shopify.com",
    "github.com", "wordpress.org", "schema.org", "googleapis.com"
}
NOISE_EMAIL = re.compile(r"(?:example\.|noreply@|no-reply@|donotreply@|sentry\.|wixpress\.|webpack|cloudflare|recaptcha|@2x)", re.I)
EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@(?:[A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,24}(?![\w.-])", re.I)
USER_AGENT = "LetterDesk-Research/1.0 (+https://author-scout-team-bot.vercel.app)"
MAX_BODY = 384 * 1024
CONTACT_PATHS = ("/contact", "/contact-us", "/about", "/about-us", "/impressum")

def _clean(value: str, maximum: int = 100) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\x00", " ")).strip()[:maximum]

def build_queries(service_key: str, niche: str = "", city: str = "", country: str = "", extra_signals=None) -> list[str]:
    """Deterministic service-appropriate queries. No fictitious business names."""
    if service_key not in SERVICE_DEFINITIONS:
        raise ValueError("Unknown scouting service")
    niche = _clean(niche, 60).replace('"', '')
    place = _clean(" ".join(x for x in (city, country) if x), 90).replace('"', '')
    quote = lambda value: f'"{value}"' if value else ""
    qualifier = " ".join(x for x in (quote(niche), quote(place)) if x)
    definition = SERVICE_DEFINITIONS[service_key]
    results = []
    for angle in definition["angles"]:
        q = _clean(f'{quote(angle)} {qualifier} official contact website', 220)
        if q not in results: results.append(q)
    for item in list(extra_signals or [])[:4]:
        item = _clean(item, 45).replace('"', '')
        if not item: continue
        q = _clean(f'{quote(niche or definition["label"])} {quote(place)} {quote(item)} contact website', 220)
        if q not in results: results.append(q)
    return results[:8]

def _is_blocked_hostname(hostname: str) -> bool:
    h = hostname.lower().strip(".")
    return not h or h == "localhost" or h.endswith((".localhost", ".local", ".internal", ".onion")) or any(h == item or h.endswith("." + item) for item in BLOCK_HOSTS)

def normalized_public_url(value: str, *, resolve_dns: bool = True) -> str:
    """Restrict to public HTTPS/HTTP websites; check all resolved addresses."""
    original = _clean(value, 1800)
    if not original: raise ValueError("A website URL is required")
    try: parsed = urlparse(original)
    except Exception: raise ValueError("Invalid website URL")
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not parsed.hostname:
        raise ValueError("Only public HTTP(S) websites are supported")
    try: port = parsed.port
    except ValueError: raise ValueError("Invalid website port")
    if port not in (None, 80, 443): raise ValueError("Nonstandard ports are disabled")
    hostname = parsed.hostname.lower()
    if _is_blocked_hostname(hostname): raise ValueError("Search platforms, private hosts and directories cannot be directly scanned")
    try:
        direct = ipaddress.ip_address(hostname)
        if not direct.is_global: raise ValueError("Private and reserved IP addresses are blocked")
        # Literal IPs have no prospect identity and are unnecessary for this use case.
        raise ValueError("A business domain is required rather than an IP address")
    except ValueError as e:
        if "blocked" in str(e) or "rather than" in str(e): raise
    if resolve_dns:
        try: addresses = socket.getaddrinfo(hostname, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError as e: raise ValueError("Website domain could not be resolved") from e
        if not addresses: raise ValueError("No website IP addresses found")
        for entry in addresses:
            ip = ipaddress.ip_address(entry[4][0].split("%")[0])
            if not ip.is_global: raise ValueError("DNS resolves to a nonpublic network")
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path or "/", "", parsed.query[:500], ""))

def _http_get_checked(client, url: str, *, max_redirects=2) -> tuple[str,str,int]:
    seen=set()
    for _ in range(max_redirects + 1):
        url = normalized_public_url(url)
        if url in seen: raise ValueError("Redirect loop")
        seen.add(url)
        with client.stream("GET", url, follow_redirects=False, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"}) as res:
            if res.status_code in (301, 302, 303, 307, 308):
                loc = res.headers.get("location", "")
                if not loc: raise ValueError("Redirect without Location")
                url = urljoin(url, loc)
                continue
            if res.status_code != 200: raise ValueError(f"HTTP {res.status_code}")
            typ = res.headers.get("content-type", "").split(";")[0].lower()
            if typ and not (typ.startswith("text/html") or typ.startswith("text/plain") or typ == "application/xhtml+xml"):
                raise ValueError("Non-HTML website resource")
            if int(res.headers.get("content-length") or 0) > MAX_BODY: raise ValueError("Page exceeds 384KB scan cap")
            chunks=[]; total=0
            for chunk in res.iter_bytes():
                total+=len(chunk)
                if total > MAX_BODY: raise ValueError("Page exceeds 384KB scan cap")
                chunks.append(chunk)
            return url, b"".join(chunks).decode("utf-8", errors="replace"), res.status_code
    raise ValueError("Redirect cap exceeded")

def _robots_allowed(client, url: str, cache: dict) -> bool:
    p=urlparse(url)
    origin=f"{p.scheme}://{p.netloc}"
    if origin not in cache:
        robots=origin+"/robots.txt"
        try:
            robots_url=normalized_public_url(robots)
            with client.stream("GET", robots_url, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as res:
                if res.status_code in (401,403):
                    cache[origin]=False
                elif res.status_code == 404:
                    cache[origin]=None
                elif res.status_code != 200:
                    cache[origin]=False  # fail closed for transient site errors
                else:
                    data=res.read(80_001)
                    if len(data)>80_000: cache[origin]=False
                    else:
                        parser=RobotFileParser()
                        parser.parse(data.decode("utf-8",errors="replace").splitlines())
                        cache[origin]=parser
        except (httpx.RequestError, ValueError):
            cache[origin]=False
    parsed=cache[origin]
    return parsed is None or (parsed is not False and parsed.can_fetch(USER_AGENT, url))

def inspect_website(value: str, *, client=None, max_pages: int = 3) -> dict:
    """Inspect only the prospect's own public site and a few contact pages."""
    site = normalized_public_url(value)
    root = urlparse(site).hostname
    owned = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(6.5), trust_env=False)
    robots_cache={}
    inspected=[]
    emails=[]
    signals=[]
    name=""
    try:
        to_visit=[site]
        for _ in range(min(max_pages, 4)):
            if not to_visit: break
            url=to_visit.pop(0)
            if any(r["url"]==url for r in inspected): continue
            if not _robots_allowed(client, url, robots_cache):
                inspected.append({"url":url,"status":"robots_blocked"})
                continue
            try:
                final, html, status = _http_get_checked(client,url)
                doc=BeautifulSoup(html,"html.parser")
                for s in doc(["script","style","svg","template"]):s.decompose()
                title=doc.title.get_text(" ",strip=True) if doc.title else ""
                if not name: name=_clean((doc.h1.get_text(" ",strip=True) if doc.h1 else "") or title, 120)
                visible=_clean(doc.get_text(" ",strip=True),18000)
                inspected.append({"url":final,"status":"fetched","page_title":_clean(title,140)})
                if len(inspected)==1:
                    for suffix in CONTACT_PATHS[:2]:
                        new=urljoin(final,suffix)
                        if urlparse(new).hostname==root and new not in to_visit: to_visit.append(new)
                    for a in doc.select("a[href]"):
                        href=str(a.get("href") or "")
                        if any(hint in href.lower() for hint in ("contact","impressum")):
                            dest=urljoin(final,href)
                            if urlparse(dest).hostname==root and dest not in to_visit: to_visit.insert(0,dest)
                for anchor in doc.select("a[href^='mailto:']"):
                    raw=unquote(str(anchor.get("href") or "")[7:].split("?")[0])
                    for candidate in EMAIL_RE.findall(raw):
                        e=candidate.lower()
                        if not NOISE_EMAIL.search(e) and not any(x["email"]==e for x in emails):
                            emails.append({"email":e,"source_url":final,"method":"explicit_mailto","verification":"published_not_verified"})
                # Visible email text on the official page is a candidate requiring review, never verified delivery.
                for candidate in EMAIL_RE.findall(visible):
                    e=candidate.lower()
                    if not NOISE_EMAIL.search(e) and not any(x["email"]==e for x in emails):
                        emails.append({"email":e,"source_url":final,"method":"published_text","verification":"published_not_verified"})
                signals.append({"source_url":final,"excerpt":visible[:400]})
            except (httpx.RequestError,ValueError) as e:
                inspected.append({"url":url,"status":"failed","error":_clean(str(e),160)})
    finally:
        if owned: client.close()
    return {
        "website":site,"name":name or root,"email_candidates":emails[:8],
        "pages":inspected,"evidence":signals[:4],
        "email_status":"publicly_observed_unverified" if emails else "not_found",
    }

def search_public_web(queries: list[str], *, max_results: int = 6) -> tuple[list[dict],list[str]]:
    """DDGS backed search. Returns website candidates, never presumed sales prospects."""
    from ddgs import DDGS
    candidates=[]; errors=[]
    seen=set()
    for query in queries[:4]:
        try:
            with DDGS(timeout=9) as ddgs:
                found=ddgs.text(query,max_results=max(1,min(int(max_results),15)))
                for item in found or []:
                    raw=str(item.get("href") or item.get("url") or "")
                    try:
                        u=normalized_public_url(raw,resolve_dns=False)
                    except ValueError: continue
                    host=urlparse(u).hostname
                    # Restrict to actual official site targets instead of portals/news.
                    if host in seen: continue
                    seen.add(host)
                    candidates.append({"url":u,"search_query":query,"snippet":_clean(item.get("body") or "",400),"title":_clean(item.get("title") or "",140)})
        except Exception as e:
            errors.append(f"Search provider returned an error for one query: {type(e).__name__}")
    return candidates,errors

def website_identity(website: str, email: str, name: str, service_key: str) -> str:
    host=(urlparse(website).hostname or "").lower().removeprefix("www.")
    if service_key=="author":
        # Different authors can share the same publisher or hosted site.
        if email: return "email:"+email.lower()
        return "author:"+re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")[:80]+":"+host
    return "site:"+host if host else "email:"+email.lower()


def search_google_places(query: str, api_key: str, max_results: int = 8, *, client=None) -> list[dict]:
    """Official Google Places Text Search (New), not scraping Google Maps UI.

    Requires an enabled Places API (New) and a budget/quotas set in Google Cloud.
    Google listing info is treated as third-party evidence, not contact verification.
    """
    if not api_key or not api_key.strip():
        raise ValueError("Google Places API is not configured for the Maps workspace")
    query=_clean(query,150)
    if len(query)<4: raise ValueError("Specify a business type and location")
    owned=client is None
    client=client or httpx.Client(timeout=12,trust_env=False)
    try:
        res=client.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "X-Goog-Api-Key":api_key,
                "X-Goog-FieldMask":"places.id,places.displayName,places.websiteUri,places.googleMapsUri,places.formattedAddress,places.primaryType",
                "Content-Type":"application/json",
            },
            json={"textQuery":query,"maxResultCount":max(1,min(int(max_results),10))},
        )
        if res.status_code != 200:
            raise RuntimeError("Google Places request failed; confirm API authorization, permissions and billing")
        listings=[]
        for p in res.json().get("places",[])[:10]:
            pid=_clean(p.get("id"),160)
            if not pid:continue
            website=p.get("websiteUri") or ""
            try: website=normalized_public_url(website,resolve_dns=False)
            except ValueError: website=""
            maps_url=p.get("googleMapsUri") or ""
            if not maps_url.startswith("https://www.google.com/maps/") and not maps_url.startswith("https://maps.google.com/"):
                maps_url=""
            listings.append({
                "name":_clean((p.get("displayName") or {}).get("text") or "",120),
                "place_id":pid,
                "website":website,
                "maps_url":maps_url,
                "address":_clean(p.get("formattedAddress"),250),
                "category":_clean(p.get("primaryType"),100),
                "search_query":query,
            })
        return listings
    finally:
        if owned:client.close()
