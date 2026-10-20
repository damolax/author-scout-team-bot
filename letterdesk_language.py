"""Conservative prospect language selection.

Country is a hint, not a verified language. No text is machine-translated here.
Only explicitly recorded preference/evidence may determine an approved language.
"""
from __future__ import annotations
COUNTRY_SUGGESTIONS={
 "spain":("es",["es","ca","eu","gl","en"]),
 "france":("fr",["fr","en"]),"italy":("it",["it","en"]),
 "germany":("de",["de","en"]),"portugal":("pt",["pt","en"]),
 "brazil":("pt-BR",["pt-BR","en"]),"mexico":("es-MX",["es-MX","en"]),
 "nigeria":("en",["en","yo","ig","ha"]),"iceland":("is",["is","en"]),
 "united states":("en-US",["en-US","es"]),"united kingdom":("en-GB",["en-GB"]),
 "canada":("en",["en","fr"]),"belgium":("nl",["nl","fr","de","en"]),
 "switzerland":("de",["de","fr","it","rm","en"])
}
def language_recommendation(country,preferred="",evidence_language=""):
    selected=str(preferred or "").strip()
    verified=str(evidence_language or "").strip()
    name=str(country or "").strip().lower()
    hint,options=COUNTRY_SUGGESTIONS.get(name,("",[]))
    if selected:
        return {"language":selected,"source":"confirmed_preference",
                "confidence":"user_provided","alternatives":options,
                "translation_required":False,"needs_confirmation":False}
    if verified:
        return {"language":verified,"source":"documented_writing_language",
                "confidence":"evidence_supplied","alternatives":options,
                "translation_required":False,"needs_confirmation":False}
    return {"language":hint,"source":"country_hint_only" if hint else "unknown",
        "confidence":"low" if hint else "none","alternatives":options,
        "translation_required":True,"needs_confirmation":True}
