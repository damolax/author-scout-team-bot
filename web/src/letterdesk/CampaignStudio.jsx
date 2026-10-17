import React,{useEffect,useState} from 'react'
import './campaign-studio.css'

const BETA='Gmail connection and campaign sending are protected by separate staging permissions.'
const BASES=[
  {value:'explicit_opt_in',label:'Recipient explicitly requested contact'},
  {value:'existing_customer',label:'Existing customer or business relationship'},
  {value:'documented_legitimate_interest',label:'Documented legitimate interest (review applicable law)'},
]
const fmt=v=>(Number(v)||0).toLocaleString()

export default function CampaignStudio({active,serviceKey,keyValue,request}){
  const [open,setOpen]=useState(false)
  const [connections,setConnections]=useState([])
  const [senders,setSenders]=useState([])
  const [campaigns,setCampaigns]=useState([])
  const [identities,setIdentities]=useState({})
  const [newName,setNewName]=useState('')
  const [senderId,setSenderId]=useState('')
  const [aliasAccess,setAliasAccess]=useState(false)
  const [dailyLimit,setDailyLimit]=useState(10)
  const [timezone,setTimezone]=useState('Africa/Lagos')
  const [selectedCampaign,setSelectedCampaign]=useState('')
  const [entries,setEntries]=useState([])
  const [draftId,setDraftId]=useState('')
  const [availableDrafts,setAvailableDrafts]=useState([])
  const [recipient,setRecipient]=useState('')
  const [basis,setBasis]=useState('explicit_opt_in')
  const [basisEvidence,setBasisEvidence]=useState('')
  const [oauthEnabled,setOauthEnabled]=useState(false)
  const [writesEnabled,setWritesEnabled]=useState(false)
  const [working,setWorking]=useState('')
  const [notice,setNotice]=useState('')
  const [error,setError]=useState('')

  async function get(path){return request(path,keyValue)}
  async function post(path,payload){return request(path,keyValue,{method:'POST',body:JSON.stringify(payload||{})})}
  const root='/api/v2/letterdesk/services/'+serviceKey
  async function refresh(){
    try{
      const [conn,available,list]=await Promise.all([
        get('/api/v2/letterdesk/gmail/connections'),
        get(root+'/senders'),get(root+'/campaigns')])
      setConnections(conn.connections||[]);setOauthEnabled(Boolean(conn.oauth_enabled))
      setSenders(available.senders||[]);setWritesEnabled(Boolean(list.writes_enabled))
      setCampaigns(list.campaigns||[])
      const draftList=await get(root+'/campaigns/eligible-drafts')
      setAvailableDrafts(draftList.drafts||[])
      setError('')
    }catch(e){setError(e.message||'Could not load Gmail or campaign settings')}
  }
  useEffect(()=>{
    setOpen(false);setConnections([]);setSenders([]);setCampaigns([])
    setIdentities({});setNewName('');setSenderId('');setSelectedCampaign('')
    setEntries([]);setAvailableDrafts([]);setNotice('');setError('')
  },[serviceKey])
  useEffect(()=>{if(active&&keyValue)refresh()},[active,serviceKey,keyValue])

  useEffect(()=>{
    const params=new URLSearchParams(window.location.search)
    const status=params.get('gmail_status')
    if(!status)return
    setNotice(status==='connected'?'Google account connected. Review verified sender identities before using it.':
      'Google connection status: '+status.replaceAll('_',' ')+'. No campaign was activated.')
    params.delete('gmail_status')
    window.history.replaceState(null,'',window.location.pathname+(params.toString()?'?'+params:''))
  },[active])

  async function connect(){
    setWorking('connect');setError('');setNotice('')
    try{
      const r=await post('/api/v2/letterdesk/gmail/connect',{requestAliasVerification:aliasAccess})
      if(!r.authorization_url?.startsWith('https://accounts.google.com/'))throw new Error('Invalid Google authorization URL')
      window.location.assign(r.authorization_url)
    }catch(e){setError(e.message||'Cannot start Google connection');setWorking('')}
  }
  async function disconnect(id){
    if(!window.confirm('Disconnect this Gmail account? Any associated campaign will be paused.'))return
    setWorking(id);setError('')
    try{await post('/api/v2/letterdesk/gmail/connections/'+id+'/disconnect',{})
      setNotice('Google connection disconnected. Associated campaigns are paused.');await refresh()}
    catch(e){setError(e.message)}
    finally{setWorking('')}
  }
  async function seeIdentities(id){
    setWorking(id);setError('')
    try{
      const r=await get('/api/v2/letterdesk/gmail/connections/'+id+'/identities')
      setIdentities(v=>({...v,[id]:r.identities||[]}))
    }catch(e){setError(e.message)}
    finally{setWorking('')}
  }
  async function enableSender(identity,enable){
    setWorking(identity.id);setError('')
    try{await post(root+'/senders/'+identity.id+'/enable',{enabled:enable})
      setNotice((enable?'Enabled':'Disabled')+' Google-verified sender '+identity.email)
      await refresh()
      const conn=connections.find(x=>x.email===identity.google_account)
      if(conn)await seeIdentities(conn.id)
    }catch(e){setError(e.message)}
    finally{setWorking('')}
  }
  async function newCampaign(){
    if(!newName.trim()||!senderId)return
    setWorking('new');setError('');setNotice('')
    try{
      const r=await post(root+'/campaigns',{
        name:newName,max_daily:Number(dailyLimit),
        sender_identity_id:senderId,timezone_name:timezone,
        min_interval_seconds:180,send_window_start:9,send_window_end:17})
      setNewName('');setNotice('Draft campaign created. No mail was sent.')
      setSelectedCampaign(r.id);await refresh()
    }catch(e){setError(e.message)}
    finally{setWorking('')}
  }
  async function loadQueue(id){
    setSelectedCampaign(id)
    if(!id){setEntries([]);return}
    try{const data=await get(root+'/campaigns/'+id+'/queue');setEntries(data.queue||[])}
    catch(e){setError(e.message)}
  }
  async function stage(){
    if(!selectedCampaign||!draftId||!recipient||!basisEvidence)return
    setWorking('queue');setError('');setNotice('')
    try{
      await post(root+'/campaigns/'+selectedCampaign+'/queue',{
        message_record_id:draftId.trim(),recipient_email:recipient.trim(),
        permission_basis:basis,permission_evidence:basisEvidence.trim()})
      setDraftId('');setRecipient('');setBasisEvidence('')
      setNotice('Message added for explicit review. It has NOT been sent.')
      await loadQueue(selectedCampaign)
      await refresh()
    }catch(e){setError(e.message)}
    finally{setWorking('')}
  }
  async function approve(id){
    setWorking(id);setError('')
    try{
      await post(root+'/campaigns/'+selectedCampaign+'/queue/'+id+'/approve',{})
      setNotice('Approved for a future controlled release. Sending is currently disabled.')
      await loadQueue(selectedCampaign)
    }catch(e){setError(e.message)}
    finally{setWorking('')}
  }
  async function pause(){
    if(!selectedCampaign)return
    setWorking('pause');setError('')
    try{
      await post(root+'/campaigns/'+selectedCampaign+'/pause',{})
      setNotice('Campaign paused; queued messages held.')
      await refresh();await loadQueue(selectedCampaign)
    }catch(e){setError(e.message)}
    finally{setWorking('')}
  }
  return <section className="ld-campaign" aria-label="Gmail accounts and campaigns">
    <div className="ld-campaign-top">
      <div><span className="ld-campaign-kicker">PHASE 6 / ACCOUNT AND OUTREACH CONTROLS</span>
        <h3>Gmail & Campaign Center</h3>
        <p>Connect senders, assign them to this service, and review each campaign without risking premature sends.</p></div>
      <button type="button" className="ld-campaign-toggle" onClick={()=>setOpen(!open)} aria-expanded={open}>
        {open?'Hide center ↑':'Open center ↓'}</button>
    </div>
    {open&&<div className="ld-campaign-body">
      <div className="ld-campaign-banner">
        <strong>Controlled preview</strong>
        <span>{BETA} Connecting an account does not enable sending. Google OAuth requires the app's credentials, testing users and approved redirect URL.</span>
      </div>
      {error&&<p className="ld-campaign-error" role="alert">{error}</p>}
      {notice&&<p className="ld-campaign-notice" role="status">{notice}</p>}
      <div className="ld-campaign-two">
        <div className="ld-campaign-panel">
          <div className="ld-campaign-row"><h4>Gmail connections</h4>
            <button type="button" onClick={refresh}>↻ Refresh</button></div>
          <p>Add different Google accounts for different service workspaces. Only Google's accepted Send as identities qualify as verified.</p>
          <label className="ld-campaign-checkbox"><input type="checkbox" checked={aliasAccess} onChange={e=>setAliasAccess(e.target.checked)}/>
            <span>Request verified Send as aliases from Gmail settings<br/><small>Requires Google's restricted gmail.settings.basic scope; use only after app verification.</small></span></label>
          <button className="ld-campaign-primary" type="button" onClick={connect} disabled={!oauthEnabled||Boolean(working)}>
            {working==='connect'?'Opening Google…':'＋ Connect Gmail account'}</button>
          {!oauthEnabled&&<p className="ld-campaign-caution">Google account connection is locked in staging until OAuth configuration and security review pass.</p>}
          {connections.length===0?<p className="ld-campaign-muted">No Gmail accounts connected to this staging team.</p>:connections.map(c=><div className="ld-campaign-account" key={c.id}>
            <div><strong>{c.email}</strong><small>{c.status} · {fmt(c.verified_senders)} verified sender identities · {c.alias_access?'Alias verification granted':'Primary address only'}</small></div>
            <div><button onClick={()=>seeIdentities(c.id)} type="button">View addresses</button>
            {c.owner_is_you&&c.status==='connected'&&<button onClick={()=>disconnect(c.id)} type="button">Disconnect</button>}</div>
            {(identities[c.id]||[]).map(identity=><div key={identity.id} className="ld-campaign-identity">
              <span>{identity.email} <small>{identity.verification_status} via {identity.verification_source.replaceAll('_',' ')}</small></span>
              {c.owner_is_you&&identity.verification_status==='verified'&&<button type="button" disabled={!writesEnabled||Boolean(working)}
                onClick={()=>enableSender(identity,!identity.enabled)}>{identity.enabled?'Disable':'Enable for campaigns'}</button>}
            </div>)}
          </div>)}
        </div>
        <div className="ld-campaign-panel">
          <div className="ld-campaign-row"><h4>Sender assignment & new campaign</h4><span>{serviceKey.replaceAll('-',' ')}</span></div>
          <p>Select an enabled, Google-verified identity. Each service can use a different Gmail address or verified alias.</p>
          <label>Sender address<select value={senderId} onChange={e=>setSenderId(e.target.value)}>
            <option value="">Choose a connected, verified sender</option>
            {senders.filter(s=>s.enabled&&s.verification_status==='verified').map(s=>
              <option key={s.id} value={s.id}>{s.email} · {s.google_account}</option>)}
          </select></label>
          <label>Campaign name<input maxLength={100} value={newName} onChange={e=>setNewName(e.target.value)} placeholder="e.g. Madrid fiction author conversations"/></label>
          <div className="ld-campaign-pair">
            <label>Max per sender / day<input type="number" min="1" max="30" value={dailyLimit} onChange={e=>setDailyLimit(Number(e.target.value))}/></label>
            <label>Local timezone<input value={timezone} onChange={e=>setTimezone(e.target.value)} maxLength={80} placeholder="Europe/Madrid"/></label>
          </div>
          <p className="ld-campaign-muted">Default sending window: 9:00–17:00 local time. Minimum interval: three minutes. Automatic sending is not activated here.</p>
          <button className="ld-campaign-primary" type="button" disabled={!writesEnabled||!senderId||!newName.trim()||Boolean(working)}
            onClick={newCampaign}>Create draft campaign</button>
          {!writesEnabled&&<p className="ld-campaign-caution">Editing assignments and campaigns is currently disabled on this preview. Viewing remains available.</p>}
        </div>
      </div>
      <div className="ld-campaign-panel ld-campaign-full">
        <div className="ld-campaign-row"><h4>Campaign queue</h4><span>Review before any delivery</span></div>
        <label>Choose campaign<select value={selectedCampaign} onChange={e=>loadQueue(e.target.value)}>
          <option value="">Select draft campaign</option>
          {campaigns.map(c=><option key={c.id} value={c.id}>{c.name} · {c.status} · {c.sender_email||'no sender'} · {fmt(c.queue_total)} queued</option>)}
        </select></label>
        {selectedCampaign&&<>
          <div className="ld-campaign-queue-options">
            <label>Choose a prepared, unsent message<select value={draftId} onChange={e=>{
              const id=e.target.value
              const item=availableDrafts.find(x=>x.id===id)
              setDraftId(id);setRecipient(item?.recipient_email||'')
            }}>
              <option value="">Select a reviewed draft</option>
              {availableDrafts.map(d=><option key={d.id} value={d.id}>{d.prospect_name} — {d.recipient_email} — {(d.subject||'No subject').slice(0,55)}</option>)}
            </select></label>
            <label>Recipient email<input type="email" value={recipient} readOnly aria-label="Selected draft recipient" placeholder="Choose a draft first"/></label>
            <label>Contact basis<select value={basis} onChange={e=>setBasis(e.target.value)}>
              {BASES.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
            <label className="ld-campaign-evidence">Documented permission / relationship / business relevance<textarea
              value={basisEvidence} onChange={e=>setBasisEvidence(e.target.value)} rows={3} maxLength={1800}
              placeholder="Document specific permission or the existing relationship and relevant legal basis." /></label>
          </div>
          <div className="ld-campaign-buttons">
            <button type="button" disabled={!writesEnabled||Boolean(working)||!draftId||!recipient||basisEvidence.length<18}
              onClick={stage}>Add draft to review queue</button>
            <button type="button" disabled={!writesEnabled||Boolean(working)} onClick={pause}>Pause campaign</button>
            <button type="button" onClick={()=>loadQueue(selectedCampaign)}>Refresh queue</button>
          </div>
          <div className="ld-campaign-table">
            <table><thead><tr><th>Recipient</th><th>Status</th><th>Contact basis</th><th>Actions</th></tr></thead>
              <tbody>{entries.length?entries.map(q=><tr key={q.id}>
                <td>{q.recipient_email}</td><td>{q.status.replaceAll('_',' ')}</td><td>{q.permission_basis.replaceAll('_',' ')}</td>
                <td>{q.status==='pending_review'&&<button disabled={!writesEnabled||Boolean(working)}
                  type="button" onClick={()=>approve(q.id)}>Approve draft</button>}</td>
              </tr>):<tr><td colSpan="4">No prepared messages in this campaign.</td></tr>}</tbody></table>
          </div>
        </>}
        <p className="ld-campaign-muted">Phase 6 prepares authorized drafts and approval records. Actual delivery remains switched off until reply safety, Gmail authentication, and a single-account test are approved.</p>
      </div>
    </div>}
  </section>
}
