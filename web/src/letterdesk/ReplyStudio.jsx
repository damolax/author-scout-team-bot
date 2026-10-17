import React,{useEffect,useState} from 'react'
import './reply-studio.css'

const OUTCOMES=[
 ['positive','Positive / interested'],['yes','Yes (contextual)'],['no','No (contextual)'],
 ['question','Question'],['objection','Concern / objection'],
 ['not_now','Not now'],['negative','Declines further contact'],
 ['opt_out','Unsubscribe / do not contact'],['bounce','Confirmed hard bounce'],
 ['uncertain','Needs human interpretation']
]
const fmt=(time)=>{try{return time?new Date(time).toLocaleString():'—'}catch{return '—'}}
function clientKey(){
  if(typeof crypto!=='undefined'&&crypto.randomUUID)return crypto.randomUUID()
  return 'reply-'+Date.now()+'-'+Math.random().toString(36).slice(2)
}
export default function ReplyStudio({serviceKey,keyValue,request,active}){
  const [open,setOpen]=useState(false)
  const [conversations,setConversations]=useState([])
  const [inbox,setInbox]=useState([])
  const [flows,setFlows]=useState([])
  const [sync,setSync]=useState([])
  const [writeEnabled,setWriteEnabled]=useState(false)
  const [readEnabled,setReadEnabled]=useState(false)
  const [filter,setFilter]=useState('all')
  const [selectedReply,setSelectedReply]=useState('')
  const [reviewOutcome,setReviewOutcome]=useState('uncertain')
  const [conversation,setConversation]=useState('')
  const [sender,setSender]=useState('')
  const [body,setBody]=useState('')
  const [suggestion,setSuggestion]=useState(null)
  const [selectedFlow,setSelectedFlow]=useState('')
  const [working,setWorking]=useState('')
  const [notice,setNotice]=useState('')
  const [error,setError]=useState('')
  const [lastReviewed,setLastReviewed]=useState(null)
  const [idempotencyKey,setIdempotencyKey]=useState(clientKey)

  const prefix='/api/v2/letterdesk/services/'+serviceKey
  const get=(path)=>request(prefix+path,keyValue)
  const post=(path,payload)=>request(prefix+path,keyValue,{method:'POST',body:JSON.stringify(payload)})

  async function refresh(){
    if(!active||!keyValue)return
    try{
      const [items,people,health,designs]=await Promise.all([
        get('/replies?filter='+encodeURIComponent(filter)),
        get('/replies/conversations'),get('/replies/sync-health'),
        get('/flows')])
      setInbox(items.replies||[])
      setConversations(people.conversations||[])
      setSync(health.connections||[])
      setFlows((designs.flows||[]).filter(d=>d.status==='draft'))
      setWriteEnabled(Boolean(items.write_enabled))
      setReadEnabled(Boolean(health.read_active))
    }catch(e){setError(e.message||'Reply workspace could not load')}
  }
  useEffect(()=>{
    setOpen(false);setInbox([]);setConversations([]);setSync([]);setFlows([])
    setSelectedReply('');setReviewOutcome('uncertain');setConversation('')
    setSender('');setBody('');setSelectedFlow('');setLastReviewed(null)
    setSuggestion(null);setError('');setNotice('');setIdempotencyKey(clientKey())
  },[serviceKey])
  useEffect(()=>{if(active&&keyValue)refresh()},[active,keyValue,serviceKey,filter])

  const reply=inbox.find(x=>x.id===selectedReply)||null
  const selectedConversation=conversations.find(x=>x.id===conversation)

  function chooseReply(id){
    setSelectedReply(id)
    const entry=inbox.find(x=>x.id===id)
    setReviewOutcome(entry?.final_outcome||entry?.suggested_outcome||'uncertain')
    setLastReviewed(null);setNotice('')
  }
  function chooseConversation(id){
    setConversation(id)
    const item=conversations.find(x=>x.id===id)
    setSender(item?.email||'')
    setSelectedFlow(item?.flow_design_id||'')
    setBody('');setSuggestion(null);setIdempotencyKey(clientKey());setNotice('')
  }
  async function classify(){
    if(!body.trim())return
    setWorking('classify');setError('');setNotice('')
    try{
      const response=await post('/replies/classify',{text:body})
      setSuggestion(response.suggestion)
      setNotice('Suggestion only. No prospect or campaign has been changed.')
    }catch(e){setError(e.message)}
    finally{setWorking('')}
  }
  async function record(){
    if(!writeEnabled||!conversation||!sender||!body.trim())return
    setWorking('record');setError('');setNotice('')
    try{
      const result=await post('/replies/manual',{
        conversation_id:conversation,sender_email:sender,text:body,
        idempotency_key:idempotencyKey})
      setNotice(result.created?
        'Reply recorded. Future queued emails to this contact have been held. No reply was sent.':
        'This reply was already recorded; no duplicate created.')
      setBody('');setSuggestion(null);setIdempotencyKey(clientKey())
      await refresh()
      if(result.reply_id)chooseReply(result.reply_id)
    }catch(e){setError(e.message)}
    finally{setWorking('')}
  }
  async function assign(){
    if(!writeEnabled||!conversation)return
    setWorking('assign');setError('');setNotice('')
    try{
      const result=await post('/replies/conversations/'+conversation+'/flow',
        {flow_id:selectedFlow||null})
      setNotice('Conversation bound to '+(selectedFlow?'a saved design':'its service starter')+
        ' (revision '+result.flow_revision+'). Nothing was sent.')
      await refresh()
    }catch(e){setError(e.message)}
    finally{setWorking('')}
  }
  async function review(){
    if(!reply||reply.status!=='pending_review'||!writeEnabled)return
    setWorking('review');setError('');setNotice('')
    try{
      const result=await post('/replies/'+reply.id+'/review',{outcome:reviewOutcome})
      setLastReviewed(result)
      setNotice(result.status==='stopped'?
        'Contact stopped. New queued messages remain held and the address has been suppressed.':
        'Reply reviewed. A suggested next branch is available for manual editing; nothing was sent.')
      await refresh()
    }catch(e){setError(e.message)}
    finally{setWorking('')}
  }
  return <section className="ld-replies" aria-label="Reply intelligence and review">
    <div className="ld-replies-header">
      <div><span className="ld-replies-kicker">PHASE 7 / CONVERSATION SAFETY</span>
        <h3>Reply Inbox & Decisions</h3>
        <p>Review real responses, keep every service separate and advance message branches only after approval.</p></div>
      <button type="button" onClick={()=>setOpen(v=>!v)} aria-expanded={open}>
        {open?'Hide inbox ↑':'Open inbox ↓'}</button>
    </div>
    {open&&<div className="ld-replies-content">
      <div className="ld-replies-status">
        <strong>{readEnabled?'Gmail thread-monitoring permission enabled':'Gmail thread monitoring disabled'}</strong>
        <span>Only known sent threads can be checked when the recipient explicitly authorizes Gmail read-only access.
          All inbound messages and draft suggestions are protected. This screen never sends email.</span>
      </div>
      {error&&<p role="alert" className="ld-replies-error">{error}</p>}
      {notice&&<p role="status" className="ld-replies-notice">{notice}</p>}
      <div className="ld-replies-statrow">
        {[
          ['Replies on this page',inbox.length],['Awaiting review',inbox.filter(x=>x.status==='pending_review').length],
          ['Stopped contacts',inbox.filter(x=>x.status==='stopped').length],['Monitored sender accounts',sync.length]
        ].map(([k,v])=><div key={k}><strong>{v}</strong><span>{k}</span></div>)}
      </div>
      {!!sync.length&&<div className="ld-replies-health">
        <div className="ld-replies-blockhead"><strong>Gmail synchronization health</strong><small>For senders assigned to this service</small></div>
        {sync.map(s=><div key={s.primary_email} className="ld-replies-healthrow">
          <span><strong>{s.primary_email}</strong><small>{s.has_read_permission?'Authorized Gmail read-only scope':'Reply read permission missing'}</small></span>
          <span><strong>{s.status}</strong><small>{s.last_success_at?'Last verified '+fmt(s.last_success_at):'No successful check yet'}</small></span>
        </div>)}
      </div>}
      <div className="ld-replies-panels">
        <section className="ld-replies-panel">
          <div className="ld-replies-blockhead"><strong>Conversation responses</strong>
            <div><select aria-label="Filter replies" value={filter} onChange={e=>setFilter(e.target.value)}>
              <option value="all">All</option><option value="pending_review">Needs review</option>
              <option value="reviewed">Reviewed</option><option value="stopped">Stopped</option>
            </select><button type="button" onClick={refresh}>Refresh</button></div>
          </div>
          {inbox.length===0?<p className="ld-replies-muted">No replies recorded for this service yet.</p>
            :<div className="ld-replies-list">{inbox.map(x=><button key={x.id} type="button" className={'ld-replies-listitem '+(selectedReply===x.id?'is-selected':'')}
              onClick={()=>chooseReply(x.id)}>
              <strong>{x.prospect_name}</strong>
              <span>{x.sender_email} · {fmt(x.received_at)}</span>
              <small>{x.status.replaceAll('_',' ')} · Suggested {x.suggested_outcome.replaceAll('_',' ')}</small>
            </button>)}</div>}
          {reply&&<div className="ld-replies-detail">
            <div className="ld-replies-blockhead"><strong>Review from {reply.prospect_name}</strong><small>{reply.source==='gmail_thread'?'Gmail verified thread':'Manually recorded'}</small></div>
            <p className="ld-replies-previewtext">{reply.body}</p>
            <p className="ld-replies-muted">Suggested: <strong>{reply.suggested_outcome}</strong> ({reply.outcome_confidence}). This is not a verified interpretation.</p>
            <label>Final decision<select value={reviewOutcome} onChange={e=>setReviewOutcome(e.target.value)}>
              {OUTCOMES.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
            {['negative','opt_out','bounce'].includes(reviewOutcome)&&<p className="ld-replies-warning">
              Confirming this outcome will suppress the contact across all services in your team.</p>}
            <button type="button" disabled={!writeEnabled||reply.status!=='pending_review'||Boolean(working)} onClick={review}>
              {working==='review'?'Recording review…':'Confirm reviewed decision'}</button>
            {reply.status!=='pending_review'&&<p className="ld-replies-muted">This reply was already reviewed or stopped. Decisions are retained for audit.</p>}
            {(lastReviewed?.draft_for_human_review||reply.proposed_draft)&&<div className="ld-replies-draft">
              <strong>Possible next message — human review only</strong>
              <p>Branch: {(lastReviewed?.draft_for_human_review||reply.proposed_draft).code}</p>
              <p>{(lastReviewed?.draft_for_human_review||reply.proposed_draft).subject}</p>
              <pre>{(lastReviewed?.draft_for_human_review||reply.proposed_draft).body}</pre>
              <small>Personalization placeholders are not automatically resolved. This is not queued for sending.</small>
            </div>}
          </div>}
        </section>
        <section className="ld-replies-panel">
          <div className="ld-replies-blockhead"><strong>Record or test a reply</strong><span>Human-controlled</span></div>
          <p className="ld-replies-muted">Choose a prospect's existing sent conversation. Paste only replies you are authorized to handle. Use Preview before recording.</p>
          <label>Conversation<select value={conversation} onChange={e=>chooseConversation(e.target.value)}>
            <option value="">Select a sent conversation</option>
            {conversations.map(c=><option key={c.id} value={c.id}>{c.name} — {c.email||'No email'} · {c.status}</option>)}
          </select></label>
          <label>Sender address<input type="email" readOnly value={sender} placeholder="Select a conversation" /></label>
          <label>Reply content<textarea rows={6} maxLength={12000} value={body}
            onChange={e=>{setBody(e.target.value);setSuggestion(null)}} placeholder="Paste a received reply to preview its meaning…" /></label>
          <div className="ld-replies-buttons">
            <button type="button" onClick={classify} disabled={!body.trim()||Boolean(working)}>Preview interpretation</button>
            <button type="button" className="ld-replies-main" onClick={record}
              disabled={!writeEnabled||!conversation||!sender||!body.trim()||Boolean(working)}>
              Record received reply</button>
          </div>
          {suggestion&&<p className="ld-replies-notice">Suggested: <strong>{suggestion.outcome}</strong> — {suggestion.reason}. Human confirmation required.</p>}
          {!writeEnabled&&<p className="ld-replies-warning">Saving and making decisions is currently disabled in staging. Classification preview is available.</p>}
          {selectedConversation&&<div className="ld-replies-bind">
            <div className="ld-replies-blockhead"><strong>Conversation message path</strong><small>Frozen at assignment</small></div>
            <label>Which flow should guide this contact?
              <select value={selectedFlow} onChange={e=>setSelectedFlow(e.target.value)}>
                <option value="">Service starter: Message01</option>
                {flows.map(f=><option key={f.id} value={f.id}>{f.name} · revision {f.revision}</option>)}
              </select></label>
            <button type="button" disabled={!writeEnabled||Boolean(working)} onClick={assign}>Assign reviewed flow template</button>
            <p className="ld-replies-muted">Existing recorded replies prevent replacing the flow history. Editing a shared template never silently changes an assigned contact.</p>
          </div>}
        </section>
      </div>
    </div>}
  </section>
}
