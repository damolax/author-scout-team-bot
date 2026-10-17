import React,{useEffect,useState} from 'react'
import './scouting-studio.css'

const DEFAULT_NICHES={author:'emerging fiction authors',automation:'professional service businesses','website-design':'local service businesses','digital-planner':'digital planner creators',shopify:'independent ecommerce brands','google-maps':'local businesses'}

export default function ScoutingStudio({serviceKey,keyValue,request,active}) {
  const [niche,setNiche]=useState(DEFAULT_NICHES[serviceKey]||'')
  const [city,setCity]=useState('')
  const [country,setCountry]=useState('')
  const [signals,setSignals]=useState('')
  const [seedUrl,setSeedUrl]=useState('')
  const [plan,setPlan]=useState([])
  const [observables,setObservables]=useState([])
  const [jobs,setJobs]=useState([])
  const [open,setOpen]=useState(true)
  const [busy,setBusy]=useState('')
  const [message,setMessage]=useState('')
  const [error,setError]=useState('')
  const [canRun,setCanRun]=useState(false)
  const [selectedJob,setSelectedJob]=useState(null)
  const [results,setResults]=useState([])

  useEffect(()=>{
    setNiche(DEFAULT_NICHES[serviceKey]||'')
    setCity('');setCountry('');setSignals('');setSeedUrl('')
    setPlan([]);setObservables([]);setJobs([])
    setSelectedJob(null);setResults([]);setError('');setMessage('');setCanRun(false)
  },[serviceKey])

  useEffect(()=>{
    if(!active||!keyValue)return
    let cancelled=false
    const params=new URLSearchParams({niche,city,country,signals})
    const timer=setTimeout(()=>{
      request('/api/v2/letterdesk/services/'+serviceKey+'/scout/plan?'+params.toString(),keyValue)
        .then(r=>{if(cancelled)return;setPlan(r.queries||[]);setObservables(r.observable_signals||[]);setCanRun(Boolean(r.can_run));setError('')})
        .catch(e=>{if(!cancelled)setError(e.message||'Cannot prepare queries')})
    },350)
    return()=>{cancelled=true;clearTimeout(timer)}
  },[active,keyValue,request,serviceKey,niche,city,country,signals])

  async function loadJobs(){
    if(!active||!keyValue)return
    try{
      const response=await request('/api/v2/letterdesk/services/'+serviceKey+'/scout/jobs',keyValue)
      setJobs(response.jobs||[])
    }catch(e){setError(e.message||'Jobs unavailable')}
  }
  useEffect(()=>{if(active&&keyValue)loadJobs()},[active,keyValue,serviceKey])

  async function createJob(){
    if(!canRun)return
    setBusy('create');setMessage('');setError('')
    try{
      const response=await request('/api/v2/letterdesk/services/'+serviceKey+'/scout/jobs',keyValue,{
        method:'POST',body:JSON.stringify({niche:niche.trim(),city:city.trim(),country:country.trim(),
          signals:signals.split(',').map(x=>x.trim()).filter(Boolean).slice(0,4),
          start_urls:seedUrl.trim()?[seedUrl.trim()]:[],max_queries:2,max_results:6,max_sites:8})
      })
      setMessage('Discovery job created. No messages will be sent.')
      await loadJobs()
    }catch(e){setError(e.message||'Could not create job')}
    finally{setBusy('')}
  }
  async function runJob(id){
    if(!canRun||!id)return
    setBusy(id);setMessage('');setError('')
    try{
      const r=await request('/api/v2/letterdesk/services/'+serviceKey+'/scout/jobs/'+encodeURIComponent(id)+'/run',keyValue,{method:'POST'})
      setMessage('Research complete: '+(r.created||0)+' new leads, '+(r.linked||0)+' linked, '+(r.rejected||0)+' skipped. No messages sent.')
      await loadJobs();await getResults(id)
    }catch(e){setError(e.message||'Job failed');await loadJobs()}
    finally{setBusy('')}
  }
  async function getResults(id){
    setSelectedJob(id)
    try{
      const r=await request('/api/v2/letterdesk/services/'+serviceKey+'/scout/jobs/'+encodeURIComponent(id)+'/results',keyValue)
      setResults(r.results||[])
    }catch(e){setError(e.message||'Cannot load results')}
  }

  return <section className="ld-scout-panel" aria-label="Scouting Studio">
    <div className="ld-scout-heading">
      <div><span className="ld-scout-kicker">DISCOVERY ENGINE · {serviceKey.replaceAll('-',' ').toUpperCase()}</span>
        <h3>Scouting Studio</h3>
        <p>Build relevant queries, inspect official websites, and save evidence-backed leads.</p></div>
      <button className="ld-scout-toggle" type="button" onClick={()=>setOpen(!open)} aria-expanded={open}>{open?'Hide ↑':'Open ↓'}</button>
    </div>
    {open&&<div className="ld-scout-body">
      <div className="ld-scout-inputs">
        <label>Target niche / business type<input value={niche} maxLength={65} onChange={e=>setNiche(e.target.value)} /></label>
        <label>City or region<input value={city} maxLength={80} onChange={e=>setCity(e.target.value)} placeholder="e.g. Madrid" /></label>
        <label>Country<input value={country} maxLength={80} onChange={e=>setCountry(e.target.value)} placeholder="e.g. Spain" /></label>
        <label>Extra signals<input value={signals} maxLength={200} onChange={e=>setSignals(e.target.value)} placeholder="e.g. new business, upcoming event" /></label>
        <label className="ld-scout-seed">Optional official website<input value={seedUrl} onChange={e=>setSeedUrl(e.target.value)} placeholder="https://business-example.com" /></label>
      </div>
      <div className="ld-scout-columns">
        <div className="ld-scout-query-box">
          <div className="ld-scout-subhead"><strong>Queries for this service</strong><small>{plan.length} suggested</small></div>
          {plan.length?<ol>{plan.map((q,i)=><li key={i}>{q}</li>)}</ol>:<p className="ld-scout-empty">Preparing queries…</p>}
          <p className="ld-scout-tip"><strong>Look for:</strong> {observables.join(' · ')||'Service-specific observations'}</p>
        </div>
        <div className="ld-scout-run-box">
          <span className="ld-scout-kicker">RESEARCH CONTROLS</span>
          <h4>Evidence before outreach</h4>
          <p>Public contact candidates retain their exact source. Discovery never guesses addresses, verifies email delivery, or sends messages.</p>
          {serviceKey==='google-maps'&&<p className="ld-scout-map-note">Maps scouting requires the official Google Places API. The listing itself does not verify an email address.</p>}
          <button className="ld-scout-start" type="button" disabled={!canRun||Boolean(busy)||(!niche.trim()&&!seedUrl.trim())} onClick={createJob}>
            {busy==='create'?'Creating…':'Create scouting job'}</button>
          {!canRun&&<p className="ld-scout-lock">Preview: query planning is active; live collection will unlock after sign-in and job safety tests.</p>}
          {message&&<p className="ld-scout-success" role="status">{message}</p>}
          {error&&<p className="ld-scout-error" role="alert">{error}</p>}
        </div>
      </div>
      <div className="ld-scout-jobs">
        <div className="ld-scout-subhead"><strong>Recent jobs</strong><button type="button" onClick={loadJobs}>Refresh ↻</button></div>
        {jobs.length?<div className="ld-scout-job-list">{jobs.map(job=><div className="ld-scout-job" key={job.id}>
          <div><strong>{job.niche||serviceKey}</strong><small>{[job.city,job.country].filter(Boolean).join(', ')||'No location'} · {job.created_at?new Date(job.created_at).toLocaleString():''}</small></div>
          <span className={'ld-scout-tag status-'+job.status}>{job.status}</span>
          <span className="ld-scout-count">{job.leads_created||0} new · {job.leads_linked||0} linked</span>
          <button type="button" onClick={()=>getResults(job.id)}>Results</button>
          {job.status==='queued'&&<button type="button" disabled={!canRun||Boolean(busy)} onClick={()=>runJob(job.id)}>{busy===job.id?'Running…':'Run'}</button>}
        </div>)}</div>:<p className="ld-scout-empty">No research jobs recorded for this service yet.</p>}
        {selectedJob&&<div className="ld-scout-results">
          <div className="ld-scout-subhead"><strong>Saved public evidence</strong><small>{results.length} records</small></div>
          {!results.length?<p>No discoveries recorded for this job.</p>:results.map(result=><div className="ld-scout-result" key={result.id}>
            <strong>{result.name||'Research prospect'}</strong>
            <span>{result.email?(result.email+' · publicly observed, not verified'):'Email not found'}</span>
            {result.source_url?.startsWith('https://')&&<a href={result.source_url} target="_blank" rel="noopener noreferrer">View source ↗</a>}
          </div>)}
        </div>}
      </div>
    </div>}
  </section>
}