import React,{useEffect,useState} from 'react'
import './prospect-profile.css'
const safeLink=(url)=>{try{const u=new URL(url);return ['https:','http:'].includes(u.protocol)?u.href:null}catch{return null}}
const fmt=(date)=>date?new Date(date).toLocaleDateString():'—'
export default function ProspectProfile({serviceKey,opportunityId,keyValue,request,onClose}){
  const [record,setRecord]=useState(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(true)
  const [section,setSection]=useState('research')
  useEffect(()=>{
    let cancelled=false
    setBusy(true);setError('');setRecord(null)
    request('/api/v2/letterdesk/services/'+serviceKey+'/leads/'+opportunityId,keyValue)
      .then(data=>{if(!cancelled)setRecord(data)})
      .catch(e=>{if(!cancelled)setError(e.message||'Profile unavailable')})
      .finally(()=>{if(!cancelled)setBusy(false)})
    return()=>{cancelled=true}
  },[serviceKey,opportunityId,keyValue,request])
  useEffect(()=>{
    const down=e=>{if(e.key==='Escape')onClose()}
    window.addEventListener('keydown',down)
    return()=>window.removeEventListener('keydown',down)
  },[onClose])
  const lead=record?.lead||{}
  const tabs=[['research','Research'],['evidence','Evidence'],['messages','Messages'],['history','Upload history']]
  return <div className="ld-profile-layer" role="dialog" aria-modal="true" aria-label="Prospect profile">
    <button type="button" className="ld-profile-backdrop" onClick={onClose} aria-label="Close profile"/>
    <aside className="ld-profile-panel">
      <div className="ld-profile-header"><div><small>PROSPECT 360° · {serviceKey.replaceAll('-',' ')}</small>
        <h2>{lead.name||'Prospect details'}</h2>
        <p>{[lead.city,lead.country].filter(Boolean).join(' · ')}{lead.kind?' · '+lead.kind:''}</p>
      </div><button type="button" onClick={onClose}>✕ Close</button></div>
      {busy?<p>Loading evidence and correspondence…</p>:error?<p role="alert">{error}</p>:<>
        <div className="ld-profile-summary"><span>{lead.email||'No verified email'}</span>
          <span>{record?.suppressed?'Do not contact':'Contact status: '+(lead.contact_verification||'unverified')}</span>
          <span>{record?.opportunity?.status||'research needed'}</span></div>
        <div className="ld-profile-tabs">{tabs.map(([key,label])=><button type="button" key={key}
          className={section===key?'active':''} onClick={()=>setSection(key)}>{label}</button>)}</div>
        {section==='research'&&<div className="ld-profile-section">
          <h3>Research record</h3>
          <dl>{[['Website',lead.website],['Source',lead.source_url],['City',lead.city],['Country',lead.country],
            ['Evidence summary',record?.opportunity?.evidence_summary],['Research status',record?.opportunity?.status]]
            .map(([key,value])=><div key={key}><dt>{key}</dt><dd>{safeLink(value)?<a href={safeLink(value)} target="_blank" rel="noopener noreferrer">{value} ↗</a>:value||'Not yet recorded'}</dd></div>)}</dl>
          <h3>Language and translation review</h3>
          <div className="ld-profile-language">
            <strong>{record?.language?.language||'No language confirmed'}</strong>
            <p>{record?.language?.source?.replaceAll('_',' ')||'Unknown'} · {record?.language?.confidence||'unverified'}</p>
            {record?.language?.needs_confirmation&&<p>Country is only a suggestion. Verify this prospect's preferred language before creating or translating any outbound message.</p>}
            {record?.language?.alternatives?.length>1&&<small>Possible regional languages: {record.language.alternatives.join(', ')}</small>}
          </div>
          <h3>Service-specific details</h3><pre>{JSON.stringify(record?.opportunity?.service_details||{},null,2)}</pre>
        </div>}
        {section==='evidence'&&<div className="ld-profile-section"><h3>Verified source observations</h3>
          {(record.evidence||[]).length?record.evidence.map(e=><article key={e.id}>
            <p>{e.observation||'Observation pending'}</p>
            <small>Recorded {fmt(e.collected_at)} · {e.confidence||'unverified'}</small>
            {safeLink(e.source_url)&&<p><a href={safeLink(e.source_url)} target="_blank" rel="noopener noreferrer">View original source ↗</a></p>}
          </article>):<p>No source-backed observations recorded yet.</p>}</div>}
        {section==='messages'&&<div className="ld-profile-section"><h3>Conversation history</h3>
          {(record.messages||[]).length?record.messages.map(m=><article key={m.id}>
            <small>{m.status} · {fmt(m.created_at)} · {m.sender_email||'Sender not assigned'}</small>
            <h4>{m.subject||'No subject'}</h4>
            <p className="ld-profile-message">{m.body||'No message body'}</p>
            {m.body_english&&<details><summary>English review version</summary><p className="ld-profile-message">{m.body_english}</p></details>}
          </article>):<p>No messages recorded. Imported messages may be optional.</p>}</div>}
        {section==='history'&&<div className="ld-profile-section"><h3>Provenance and imports</h3>
          {(record.imports||[]).length?record.imports.map(x=><article key={x.id}>
            <strong>{x.filename}</strong><p>File row {x.row_number} · {x.disposition} · {fmt(x.created_at)}</p>
            <small>{x.reason||'No changes applied without review'}</small>
          </article>):<p>No individual upload history is attached to this record yet.</p>}</div>}
      </>}
    </aside>
  </div>
}
