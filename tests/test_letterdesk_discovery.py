"""Phase 3 no-network regression suite for the six-mode discovery engine."""
import unittest
from unittest.mock import patch, MagicMock

from letterdesk_discovery import (
    SERVICE_DEFINITIONS, build_queries, normalized_public_url,
    website_identity, inspect_website, search_google_places,
)

class DiscoveryTests(unittest.TestCase):
    def test_all_six_services_produce_distinct_targeted_queries(self):
        self.assertEqual(len(SERVICE_DEFINITIONS), 6)
        first=[]
        for key in SERVICE_DEFINITIONS:
            queries=build_queries(key,niche="test niche",city="Madrid",country="Spain")
            self.assertGreaterEqual(len(queries),4)
            self.assertLessEqual(len(queries),8)
            self.assertTrue(all("Madrid" in q and "Spain" in q for q in queries))
            first.append(queries[0])
        self.assertEqual(len(set(first)),6)

    def test_extra_signals_are_bounded(self):
        q=build_queries("automation",extra_signals=["manual invoices","intake forms","manual scheduling","spreadsheets","fifth ignored"])
        self.assertLessEqual(len(q),8)
        self.assertTrue(any("manual invoices" in x for x in q))
        self.assertFalse(any("fifth ignored" in x for x in q))

    def test_known_unsafe_targets_rejected(self):
        urls=[
            "http://127.0.0.1", "http://10.0.0.1", "http://[::1]",
            "http://localhost", "http://service.internal",
            "http://google.com/search?q=abc", "http://example.org:8080",
            "file:///etc/passwd", "ftp://example.org", "https://user:secret@example.org",
        ]
        for url in urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    normalized_public_url(url,resolve_dns=False)

    def test_public_company_site_can_be_normalized(self):
        self.assertEqual(normalized_public_url("https://www.sample-company.org/about#contact",resolve_dns=False),
                         "https://www.sample-company.org/about")

    def test_dedupe_protects_distinct_authors_on_shared_domain(self):
        a=website_identity("https://publisher.example.org","alice@example.org","Alice Writer","author")
        b=website_identity("https://publisher.example.org","bob@example.org","Bob Writer","author")
        self.assertNotEqual(a,b)
        self.assertEqual(website_identity("https://shop.example.org","hello@example.org","A","shopify"),
                         website_identity("https://shop.example.org","sales@example.org","B","shopify"))

    @patch("letterdesk_discovery._robots_allowed",return_value=True)
    @patch("letterdesk_discovery._http_get_checked")
    @patch("letterdesk_discovery.socket.getaddrinfo")
    def test_extracts_only_published_mailto_with_source(self,dns,http,robots):
        dns.return_value=[(2,1,6,"",("93.184.216.34",443))]
        html="""<html><head><title>Example Business</title></head><body>
            <h1>Example Business</h1><p>Public contact information</p>
            <script>var hidden='secret@example.org'</script>
            <a href="mailto:hello@example.org?subject=hello">Contact us</a></body></html>"""
        http.return_value=("https://example.org/",html,200)
        result=inspect_website("https://example.org/",max_pages=1)
        self.assertEqual(result["email_candidates"][0]["email"],"hello@example.org")
        self.assertEqual(result["email_candidates"][0]["method"],"explicit_mailto")
        self.assertEqual(result["email_candidates"][0]["verification"],"published_not_verified")
        self.assertEqual(result["email_candidates"][0]["source_url"],"https://example.org/")
        self.assertFalse(any(e["email"]=="secret@example.org" for e in result["email_candidates"]))

    def test_places_adapter_requires_auth_key(self):
        with self.assertRaises(ValueError):
            search_google_places("coffee in Madrid",api_key="")

    def test_places_adapter_uses_official_api_and_returns_websites(self):
        fake=MagicMock()
        fake.post.return_value.status_code=200
        fake.post.return_value.json.return_value={
            "places":[{"id":"place-123","displayName":{"text":"Example Cafe"},
                       "websiteUri":"https://example.org",
                       "googleMapsUri":"https://www.google.com/maps/place/example-cafe",
                       "formattedAddress":"Madrid, Spain","primaryType":"cafe"}]
        }
        res=search_google_places("cafe Madrid","a-valid-test-key",client=fake)
        self.assertEqual(len(res),1)
        self.assertEqual(res[0]["name"],"Example Cafe")
        self.assertEqual(res[0]["place_id"],"place-123")
        self.assertEqual(res[0]["website"],"https://example.org/")
        self.assertEqual(fake.post.call_args.args[0],"https://places.googleapis.com/v1/places:searchText")
        self.assertIn("X-Goog-FieldMask",fake.post.call_args.kwargs["headers"])

if __name__=="__main__":
    unittest.main()
