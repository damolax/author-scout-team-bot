"""Field-level, non-destructive comparison of incoming prospect data.

Never overwrite sent messages, contact suppressions, other-service histories,
or existing research. Any changed field requires user review.
"""
from __future__ import annotations
from urllib.parse import urlparse

COMPARE_FIELDS=("name","email","website","maps_url","country","city","source_url",
                "evidence_notes","subject","first_message","first_message_english")
def norm_value(field,value):
    if value is None:return ""
    if isinstance(value,(dict,list)):return str(value)
    v=str(value).strip()
    if field in ("email","country","city"):return v.casefold()
    if field in ("website","maps_url","source_url"):
        try:
            p=urlparse(v)
            if p.scheme in ("http","https") and p.hostname:
                return (p.hostname.lower()+p.path.rstrip("/")+(("?"+p.query) if p.query else "")).strip()
        except ValueError:pass
    return v
def compare_record(incoming,prior):
    """Compare supplied non-empty fields only, never treat absence as deletion."""
    diff=[]
    for field in COMPARE_FIELDS:
        new=incoming.get(field)
        if new is None or not str(new).strip():continue
        previous=prior.get(field)
        if norm_value(field,new)==norm_value(field,previous):continue
        diff.append({"field":field,"change":"added" if not previous else "changed",
                     "previous":str(previous or "")[:16000],"incoming":str(new)[:16000]})
    new_details=incoming.get("service_details") or {}
    old_details=prior.get("service_details") or {}
    if not isinstance(new_details,dict):new_details={}
    if not isinstance(old_details,dict):old_details={}
    for key,new in new_details.items():
        if not str(new or "").strip():continue
        before=old_details.get(key)
        if norm_value(key,new)!=norm_value(key,before):
            diff.append({"field":"service_details."+key,
                         "change":"added" if not before else "changed",
                         "previous":str(before or "")[:16000],"incoming":str(new)[:16000]})
    new_branches=incoming.get("branches") or {}
    old_branches=prior.get("branches") or {}
    for key,new in new_branches.items():
        if not str(new or "").strip():continue
        before=old_branches.get(key)
        if norm_value(key,new)!=norm_value(key,before):
            diff.append({"field":"branches."+key,"change":"added" if not before else "changed",
                         "previous":str(before or "")[:16000],"incoming":str(new)[:16000]})
    return {"exact":not diff,"differences":diff,
            "new_fields":sum(x["change"]=="added" for x in diff),
            "changed_fields":sum(x["change"]=="changed" for x in diff)}
