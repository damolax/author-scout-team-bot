"""Phase 5: safe, versioned conversation-flow rules. Pure and provider-independent.

A flow design is NOT an outbound campaign. Nothing here sends or schedules mail.
Each reply outcome is contextual and results in a draft, a stop, or human review.
"""
from __future__ import annotations
import re
from copy import deepcopy

SERVICE_MODES=("author","automation","website-design","digital-planner","shopify","google-maps")
OUTCOMES=("yes","no","positive","question","objection","not_now","negative",
          "opt_out","no_reply","bounce","uncertain")
STOP_OUTCOMES={"negative","opt_out","bounce"}
ACTIONS=("draft_for_review","manual_review","stop","wait")
CODE=re.compile(r"^(?:Message[0-9]{2,8}(?:Yes|No|Question|Objection|Later|NoReply|Review|OptOut|Bounce)?|MSG-[0-9]{2,6})$")
VARIANT_ID=re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
STAGES={"initial","interested","question","objection","followup","proposal_discussion",
        "alternative","terminal","generic","not_now","success"}
PLACEHOLDERS=("first_name","prospect_name","business_name","book_title","website",
              "city","country","evidence_observation","your_name","service_name")
SERVICE_TEXT={
 "author": ("Author conversation", "Your recent work and the literary conversation",
            "Hello {{first_name}},\n\nI noticed {{evidence_observation}}. I'd be interested in learning more about the direction behind {{book_title}}. Would you be open to a brief conversation?"),
 "automation": ("Automation discovery", "A question about your workflow",
             "Hello {{first_name}},\n\nI noticed {{evidence_observation}}. Is improving this part of your workflow something you're considering?"),
 "website-design": ("Website design discovery", "A question about your website",
             "Hello {{first_name}},\n\nWhile reviewing {{website}}, I noticed {{evidence_observation}}. Is improving that experience a current priority?"),
 "digital-planner": ("Planner creator conversation", "A question about your digital products",
             "Hello {{first_name}},\n\nI noticed {{evidence_observation}} in your planner products. Are you exploring updates or new experiences for customers?"),
 "shopify": ("Shopify store conversation", "A question about your store",
             "Hello {{first_name}},\n\nI noticed {{evidence_observation}} on {{website}}. Is refining the customer experience something you're considering?"),
 "google-maps": ("Local business conversation", "A quick question about your local presence",
             "Hello {{first_name}},\n\nWhile checking your public business listing, I noticed {{evidence_observation}}. Is updating your Google Business Profile currently a priority?"),
}

def starter_flow(service):
    if service not in SERVICE_MODES:raise ValueError("Unknown service")
    label,subject,initial=SERVICE_TEXT[service]
    def node(code,stage,body="",subject="",variants=None):
        return {"code":code,"stage":stage,"subject":subject,"body":body,
                "delayMinutes":0,"reviewRequired":True,
                "variants":variants or []}
    nodes=[
      node("Message01","initial",initial,subject,[
        {"id":"A","subject":"","body":""}, {"id":"B","subject":"","body":""}
      ]),
      node("Message0101Yes","interested",
           "Thank you for your reply. What would be most useful for you to explore first?"),
      node("Message0101No","terminal"),
      node("Message0101Question","question",
           "Thank you for asking. I'll review your question and respond with information specific to your situation."),
      node("Message0101Objection","objection",
           "I appreciate the concern. I'll address your specific question before suggesting anything further."),
      node("Message0101Later","terminal"),
      node("Message0101NoReply","followup",
           "Hello {{first_name}}, I'm following up on my earlier note. No need to reply if this is not relevant."),
      node("Message0201Yes","proposal_discussion",
           "That sounds useful. I'd like to understand your priorities before outlining an appropriate next step."),
      node("Message0201No","alternative",
           "Thanks for clarifying. I'll respond to what you've said rather than assume the same approach suits you."),
      node("Message0201Question","question",
           "I'll review your question and prepare a specific reply."),
    ]
    edges=[
      {"from":"Message01","outcome":"yes","to":"Message0101Yes","action":"draft_for_review"},
      {"from":"Message01","outcome":"positive","to":"Message0101Yes","action":"draft_for_review"},
      {"from":"Message01","outcome":"no","to":None,"action":"stop","branchLabel":"Message0101No"},
      {"from":"Message01","outcome":"negative","to":None,"action":"stop","branchLabel":"Message0101No"},
      {"from":"Message01","outcome":"question","to":"Message0101Question","action":"draft_for_review"},
      {"from":"Message01","outcome":"objection","to":"Message0101Objection","action":"draft_for_review"},
      {"from":"Message01","outcome":"not_now","to":None,"action":"stop","branchLabel":"Message0101Later"},
      {"from":"Message01","outcome":"no_reply","to":"Message0101NoReply","action":"draft_for_review","delayMinutes":10080},
      {"from":"Message0101Yes","outcome":"yes","to":"Message0201Yes","action":"draft_for_review"},
      {"from":"Message0101Yes","outcome":"positive","to":"Message0201Yes","action":"draft_for_review"},
      {"from":"Message0101Yes","outcome":"no","to":"Message0201No","action":"draft_for_review"},
      {"from":"Message0101Yes","outcome":"negative","to":None,"action":"stop"},
      {"from":"Message0101Yes","outcome":"question","to":"Message0201Question","action":"draft_for_review"},
    ]
    return {"serviceKey":service,"maxMessagesPerContact":3,"maxNoReplyFollowups":1,
            "nodes":nodes,"edges":edges,
            "description":f"Draft-only starter for {label}. All claims must be evidence-verified."}

def _safe_text(value,limit):
    return isinstance(value,str) and len(value)<=limit and "\x00" not in value

def validate_flow(flow,service=None):
    problems=[]
    if not isinstance(flow,dict):return ["A flow document must be an object."]
    if service and flow.get("serviceKey")!=service:
        problems.append("This template belongs to another service.")
    if flow.get("serviceKey") not in SERVICE_MODES:
        problems.append("Unknown service in template.")
    nodes=flow.get("nodes")
    edges=flow.get("edges")
    if not isinstance(nodes,list) or not 1<=len(nodes)<=45:
        return problems+["A flow requires 1–45 nodes."]
    if not isinstance(edges,list) or len(edges)>120:
        return problems+["A flow can have no more than 120 branches."]
    cap=flow.get("maxMessagesPerContact")
    follows=flow.get("maxNoReplyFollowups")
    if type(cap)!=int or cap not in range(1,13):problems.append("Message cap must be from 1 to 12.")
    if type(follows)!=int or follows not in range(0,4):problems.append("No-reply follow-up cap must be from 0 to 3.")
    if not _safe_text(flow.get("description",""),800):
        problems.append("Description is too long.")
    codes=set()
    nodes_by_code={}
    for node in nodes:
        if not isinstance(node,dict):problems.append("Invalid node structure.");continue
        code=node.get("code")
        if not isinstance(code,str) or not CODE.fullmatch(code):
            problems.append(f"Invalid message code: {str(code)[:40]}");continue
        if code in codes:problems.append(f"Repeated node: {code}")
        codes.add(code);nodes_by_code[code]=node
        if node.get("stage","generic") not in STAGES:problems.append(f"{code}: unknown stage.")
        if not _safe_text(node.get("subject",""),400) or "\n" in node.get("subject","") or "\r" in node.get("subject",""):
            problems.append(f"{code}: subject must be a single line under 400 characters.")
        if not _safe_text(node.get("body",""),16000):problems.append(f"{code}: body too long.")
        if node.get("reviewRequired") is not True:problems.append(f"{code}: all messages require review.")
        delay=node.get("delayMinutes",0)
        if type(delay)!=int or not 0<=delay<=525600:problems.append(f"{code}: invalid delay.")
        variants=node.get("variants",[])
        if not isinstance(variants,list) or len(variants)>8:problems.append(f"{code}: maximum eight variants.");continue
        ids=set()
        for v in variants:
            if not isinstance(v,dict):problems.append(f"{code}: invalid variant.");continue
            vid=v.get("id")
            if not isinstance(vid,str) or not VARIANT_ID.fullmatch(vid) or vid in ids:problems.append(f"{code}: invalid or repeated variant ID.")
            ids.add(vid)
            if not _safe_text(v.get("subject",""),400) or "\n" in v.get("subject","") or "\r" in v.get("subject",""):
                problems.append(f"{code}: invalid variant subject.")
            if not _safe_text(v.get("body",""),16000):problems.append(f"{code}: invalid variant body.")
    if not any(c in codes for c in ("Message01","MSG-01")):problems.append("Missing Message01 starting node.")
    outgoing=set()
    nexts={c:[] for c in codes}
    for edge in edges:
        if not isinstance(edge,dict):problems.append("Invalid branch structure.");continue
        src=edge.get("from");target=edge.get("to");outcome=edge.get("outcome");action=edge.get("action")
        if src not in codes:problems.append(f"Unknown source: {str(src)[:40]}")
        if target is not None and target not in codes:problems.append(f"Unknown target: {str(target)[:40]}")
        if src in nodes_by_code and nodes_by_code[src].get("stage") in ("terminal","success"):
            problems.append(f"Completed message cannot have outgoing branches: {src}")
        if target in nodes_by_code and nodes_by_code[target].get("stage")=="terminal":
            problems.append(f"Terminal label cannot be used as a sendable target: {target}")
        if outcome not in OUTCOMES:problems.append(f"Invalid response outcome: {str(outcome)[:30]}")
        if action not in ACTIONS:problems.append(f"Invalid branch action: {str(action)[:30]}")
        key=(src,outcome)
        if key in outgoing:problems.append(f"Duplicate outcome from {str(src)[:30]}: {str(outcome)[:30]}")
        outgoing.add(key)
        label=edge.get("branchLabel")
        if label and (label not in codes or nodes_by_code.get(label,{}).get("stage")!="terminal"):
            problems.append("Stop branch label must be a terminal message node.")
        if label and action!="stop":problems.append("Branch label is only valid for a stop action.")
        if action=="stop" and target is not None:problems.append("Stop branch cannot schedule another message.")
        if action in ("draft_for_review","manual_review","wait") and not target:
            # Review with no target can be a pause, but use explicit manual_review.
            if action!="manual_review":problems.append("Active branch requires a target.")
        if outcome in STOP_OUTCOMES and (action!="stop" or target is not None):
            problems.append(f"Explicit refusal / opt-out / bounce must stop: {outcome}")
        if outcome=="no_reply":
            delay=edge.get("delayMinutes",0)
            if type(delay)!=int or delay<1440 or delay>525600:
                problems.append("No-reply follow-ups require a delay of at least 1 day.")
        elif edge.get("delayMinutes",0) is not None and (type(edge.get("delayMinutes",0))!=int or not 0<=edge.get("delayMinutes",0)<=525600):
            problems.append("Invalid branch delay.")
        if src in nexts and target in codes:nexts[src].append(target)
    stack=set();visited=set()
    def visit(code):
        if code in stack:problems.append(f"Conversation cycle near {code}");return
        if code in visited:return
        visited.add(code);stack.add(code)
        for child in nexts.get(code,[]):visit(child)
        stack.remove(code)
    for code in codes:visit(code)
    if len(problems)>40:problems=problems[:40]+["Additional validation errors omitted."]
    return list(dict.fromkeys(problems))

def simulate(flow,current_code,outcome,message_count=0,no_reply_followups=0):
    if outcome not in OUTCOMES:outcome="uncertain"
    edge=next((x for x in flow.get("edges",[]) if x["from"]==current_code and x["outcome"]==outcome),None)
    if outcome in STOP_OUTCOMES:
        return {"action":"stop","reason":outcome,"suppress":outcome in ("opt_out","negative"),
                "branchLabel":edge.get("branchLabel") if edge else None}
    if outcome=="uncertain":return {"action":"manual_review","reason":"Reply interpretation uncertain"}
    if message_count>=flow.get("maxMessagesPerContact",0):
        return {"action":"stop","reason":"Message cap reached"}
    if outcome=="no_reply" and no_reply_followups>=flow.get("maxNoReplyFollowups",0):
        return {"action":"stop","reason":"No-reply follow-up cap reached"}
    if not edge:return {"action":"manual_review","reason":"No configured branch"}
    if edge["action"]=="stop":return {"action":"stop","reason":"Configured stop branch","suppress":False,"branchLabel":edge.get("branchLabel")}
    if edge["action"]=="wait":return {"action":"wait","nextCode":edge.get("to"),"delayMinutes":edge.get("delayMinutes",0)}
    return {"action":"draft_for_review" if edge["action"]=="draft_for_review" else "manual_review",
            "nextCode":edge.get("to"),"requiresHumanApproval":True,
            "note":"Simulation only: no email was prepared or sent."}
