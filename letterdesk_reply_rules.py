"""Phase 7 deterministic reply triage and conservative flow preview.

No LLM access, inbox lookup, send, or automatic message approval. Classifications
are suggestions. Clear opt-outs stop immediately even before human review.
Unclear replies require human classification before any next-step draft is shown.
"""
from __future__ import annotations
import re
from email.utils import parseaddr

from letterdesk_flow_engine import SERVICE_MODES,starter_flow,simulate,validate_flow

STOPS=("opt_out","negative","bounce")
OUTCOMES=("yes","no","positive","question","objection","not_now","negative",
          "opt_out","bounce","uncertain")
OPT_OUT=[
    r"\b(?:unsubscribe|remove\s+me|take\s+me\s+off|delete\s+my\s+(?:email|contact))\b",
    r"\b(?:do\s+not|don'?t|never)\s+(?:email|contact|message|write|reach\s+out\s+to)\s+me\b",
    r"\b(?:stop\s+(?:emailing|contacting|messaging|writing)|no\s+more\s+email)\b",
    r"\b(?:darse?\s+de\s+baja|no\s+me\s+(?:escribas|contactes)|elimin(?:ad?|e)\s+mi\s+correo)\b",
]
DECLINE=[
    r"^(?:not\s+interested|i\s+am\s+not\s+interested|i'?m\s+not\s+interested)\b",
    r"\b(?:not\s+interested\s+in\s+(?:any|your)\s+(?:offers?|services?|messages?|contact))\b",
    r"\b(?:please\s+don't\s+follow\s+up|please\s+do\s+not\s+follow\s+up)\b",
    r"^(?:no\s+thanks?|no\s+thank\s+you|i'?ll\s+pass|i\s+will\s+pass)[.!]?$",
    r"^(?:no\s+me\s+interesa|no\s+estoy\s+interesad[oa])\b",
]
LATER=[
    r"\b(?:not\s+now|maybe\s+later|later\s+this\s+year|another\s+time|next\s+month|next\s+year)\b",
    r"\b(?:after\s+the\s+(?:holidays|launch|season)|too\s+busy\s+(?:right\s+now|at\s+the\s+moment))\b",
    r"\b(?:ahora\s+no|quiz[aá]s\s+m[aá]s\s+adelante|en\s+otro\s+momento)\b",
]
OBJECTION=[
    r"\b(?:too\s+expensive|no\s+budget|can't\s+afford|cannot\s+afford)\b",
    r"\b(?:is\s+this\s+(?:a\s+)?scam|sounds\s+like\s+spam|concerned\s+about)\b",
    r"\b(?:we\s+already\s+have\s+(?:a|someone|an)|not\s+sure\s+(?:it|this)\s+would)\b",
    r"\b(?:es\s+muy\s+caro|no\s+tenemos\s+presupuesto)\b",
]
POSITIVE=[
    r"^(?:yes|yeah|yep|sure|sounds\s+good|interested|absolutely|definitely)[.!]?$",
    r"\b(?:i'?m\s+interested|i\s+am\s+interested|let'?s\s+(?:talk|do\s+it|proceed)|please\s+send\s+details)\b",
    r"\b(?:me\s+interesa|s[ií],?\s+me\s+interesa|adelante|podemos\s+hablar)\b",
]
NEGATIVE=[
    r"^(?:no|nope|nah)[.!]?$",
    r"^(?:no\s+lo\s+creo)[.!]?$",
]
QUESTION_HINTS=["?","¿","could you","can you","would you","what is","how does","cuánto","cuanto","qué","que precio","tell me"]
BOUNCE_HINTS=["mailer-daemon","postmaster","delivery status notification","undeliverable"]

def canonical_address(value):
    addr=parseaddr(str(value or ""))[1].lower().strip()
    if not addr or "@" not in addr or len(addr)>254 or any(x in addr for x in "<>\r\n "):
        return ""
    return addr

def _matches(patterns,subject):
    return any(re.search(pattern,subject,re.I) for pattern in patterns)

def classify_reply(body,sender="",is_delivery_report=False):
    """Returns a suggestion only; negative and opt-out are high-confidence holds."""
    text=str(body or "")[:12000].replace("\r\n","\n")
    # Quoted history, common forwarded threads and signature lines must not
    # classify the new reply as an opt-out if only quoted text says 'unsubscribe'.
    fresh=text.split("\nOn ",1)[0]
    fresh=re.split(r"(?m)^[-_ ]*(?:Original Message|Mensaje original|Forwarded message)[-_ ]*$",fresh)[0]
    fresh="\n".join(line for line in fresh.splitlines() if not line.lstrip().startswith(">"))
    fresh=fresh.strip()[:3600]
    low=fresh.lower()
    address=canonical_address(sender)
    if is_delivery_report or (any(x in address for x in ("mailer-daemon","postmaster")) and any(x in low for x in BOUNCE_HINTS)):
        return {"outcome":"bounce","confidence":"high","reason":"Authenticated delivery report needs recipient confirmation"}
    if _matches(OPT_OUT,low):
        return {"outcome":"opt_out","confidence":"high","reason":"Explicit request to stop contacting"}
    if _matches(DECLINE,low):
        return {"outcome":"negative","confidence":"high","reason":"Explicitly declined the outreach"}
    if _matches(LATER,low):
        return {"outcome":"not_now","confidence":"high","reason":"Deferred further discussion"}
    if _matches(OBJECTION,low):
        return {"outcome":"objection","confidence":"low","reason":"Contains a concern needing a tailored answer"}
    if any(x in low for x in QUESTION_HINTS):
        return {"outcome":"question","confidence":"low","reason":"Asks a question that needs human response"}
    if _matches(NEGATIVE,low):
        return {"outcome":"no","confidence":"low","reason":"Context-dependent No, not necessarily a refusal"}
    if _matches(POSITIVE,low):
        return {"outcome":"positive","confidence":"low","reason":"Possibly interested; needs review"}
    return {"outcome":"uncertain","confidence":"uncertain","reason":"Meaning unclear; manual review required"}

def safe_draft(flow,current_code,outcome,message_count=0,no_reply_followups=0):
    if validate_flow(flow,flow.get("serviceKey")):
        return {"action":"manual_review","reason":"Template validation failed"}
    result=simulate(flow,current_code,outcome,message_count,no_reply_followups)
    if result.get("action")!="draft_for_review" or not result.get("nextCode"):
        return {**result,"draft":None}
    node=next((n for n in flow.get("nodes",[]) if n["code"]==result["nextCode"]),None)
    if not node or node.get("stage") in ("terminal","success") or not node.get("reviewRequired"):
        return {"action":"manual_review","reason":"No sendable approved node","draft":None}
    return {**result,"draft":{"code":node["code"],"subject":node.get("subject") or "",
                           "body":node.get("body") or "",
                           "contains_placeholders":bool(re.search(r"\{\{[^{}]+\}\}",node.get("body") or "")),
                           "requiresHumanApproval":True}}

def fallback_flow(service):
    if service not in SERVICE_MODES:raise ValueError("Unknown service")
    return starter_flow(service)
