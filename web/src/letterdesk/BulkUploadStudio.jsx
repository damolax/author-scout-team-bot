import React,{useEffect,useRef,useState} from 'react'
import './bulk-upload-studio.css'

const API=(import.meta.env.VITE_API_BASE_URL||'https://author-scout-team-bot.onrender.com').replace(/\/$/,'')
const CHUNK=1024*1024
const MAX_BYTES=64*CHUNK

async function api(route,key,method='GET',data){
  const ctrl=new AbortController()
  const timer=setTimeout(()=>ctrl.abort(),45000)
  try {
    const response=await fetch(API+route,{method,signal:ctrl.signal,
      headers:{...(key?{'X-Author-Scout-Key':key}:{}),...(data===undefined?{}:
        data instanceof Blob?{'Content-Type':'application/octet-stream'}:{'Content-Type':'application/json'})},
      ...(data===undefined?{}:{body:data instanceof Blob?data:JSON.stringify(data)})})
    const body=await response.json().catch(()=>({}))
    if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Request failed ('+response.status+').')
    return body
  }catch(error){
    if(error?.name==='AbortError')throw new Error('Request timed out. Your uploaded chunks can be resumed.')
    throw error
  }finally{clearTimeout(timer)}
}
async function fileSha(file){
  if(!globalThis.crypto?.subtle)throw new Error('SHA-256 requires a secure HTTPS browser session.')
  const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer())
  return Array.from(new Uint8Array(hash)).map(x=>x.toString(16).padStart(2,'0')).join('')
}
const percent=(value,total)=>total?Math.min(100,Math.round(100*value/total)):0
const sum=(obj,keys)=>keys.reduce((n,k)=>n+(Number(obj?.[k])||0),0)

export default function BulkUploadStudio({serviceKey,keyValue,active,onImported}){
  const [file,setFile]=useState(null)
  const [job,setJob]=useState(null)
  const [jobs,setJobs]=useState([])
  const [busy,setBusy]=useState('')
  const [error,setError]=useState('')
  const [note,setNote]=useState('')
  const [stageProgress,setStageProgress]=useState(0)
  const [confirmed,setConfirmed]=useState(false)
  const [expanded,setExpanded]=useState(false)
  const stopped=useRef(false)
  const prefix='/api/v2/letterdesk/services/'+serviceKey+'/bulk-uploads'
  const activeJob=job?.id

  async function refreshJobs(){
    if(!active||!keyValue||!expanded)return
    try{
      const result=await api(prefix,keyValue)
      setJobs(result.jobs||[])
      if(!result.enabled)setNote('Large-file uploads have not been enabled on this protected staging server.')
    }catch(e){setError(e.message)}
  }
  async function refreshJob(id){
    const latest=await api(prefix+'/'+id,keyValue)
    setJob(latest)
    if(latest.status==='completed'){
      setNote('Import completed: '+latest.accepted_rows+' saved or linked; '+
        latest.skipped_rows+' skipped. Messages remain UNSENT drafts.')
      onImported?.()
    }
    if(latest.status==='failed')setError('Import requires review: '+(latest.last_error||'processing failed')+
      '. Existing completed batches are retained safely.')
    return latest
  }
  useEffect(()=>{
    stopped.current=false
    setFile(null);setJob(null);setStageProgress(0);setError('');setNote('')
    setExpanded(false);setConfirmed(false);setJobs([])
    return()=>{stopped.current=true}
  },[serviceKey])
  useEffect(()=>{if(active&&keyValue&&expanded)refreshJobs()},[active,keyValue,serviceKey,expanded])
  useEffect(()=>{
    if(!expanded||!active||!activeJob||!['previewing','queued','processing'].includes(job?.status))return
    let cancelled=false
    const timer=setInterval(async()=>{
      if(cancelled)return
      try{
        const p=await api(prefix+'/'+activeJob,keyValue)
        if(cancelled)return
        setJob(p)
        if(p.status==='completed'){
          setNote('Completed '+p.processed_rows+' rows. All messages remain unsent.')
          onImported?.()
        }
        if(p.status==='failed')setError('Processing interrupted: '+p.last_error)
      }catch(e){if(!cancelled)setError(e.message)}
    },3000)
    return()=>{cancelled=true;clearInterval(timer)}
  },[expanded,active,activeJob,job?.status,keyValue,serviceKey])

  async function upload(){
    if(!file||busy)return
    setBusy('upload');setError('');setNote('Computing file fingerprint…');setConfirmed(false)
    try{
      if(file.size>MAX_BYTES)throw new Error('The maximum file size is 64 MB.')
      const sha=await fileSha(file)
      const manifest=await api(prefix,keyValue,'POST',{
        filename:file.name,size:file.size,sha256:sha
      })
      const jobId=manifest.id
      const pending=await api(prefix+'/'+jobId,keyValue)
      setJob(pending)
      if(pending.status==='ready'){
        setNote('File is already validated. Review the import details and confirm below.')
        return
      }
      if(pending.status!=='uploading'&&pending.status!=='previewing'){
        throw new Error('This upload is already '+pending.status+'.')
      }
      const received=new Set(pending.uploaded_part_numbers||[])
      let finished=received.size
      setStageProgress(percent(finished,manifest.parts))
      if(pending.status==='uploading'){
        let next=0
        async function worker(){
          while(next<manifest.parts){
            const index=next++
            if(stopped.current)return
            if(received.has(index))continue
            const start=index*CHUNK
            const payload=file.slice(start,Math.min(file.size,start+CHUNK))
            let attempts=0
            while(true){
              try{
                await api(prefix+'/'+jobId+'/parts/'+index,keyValue,'POST',payload)
                break
              }catch(e){
                attempts++
                if(attempts>=3)throw e
              }
            }
            finished++
            setStageProgress(percent(finished,manifest.parts))
          }
        }
        await Promise.all(Array.from({length:Math.min(3,manifest.parts)},()=>worker()))
        await api(prefix+'/'+jobId+'/finish',keyValue,'POST',{})
      }
      const state=await refreshJob(jobId)
      setNote(state.status==='previewing'?'All chunks uploaded. Background validation is running.':
        'Upload staged. Checking rows.')
    }catch(e){setError(e.message+' You can select the same file to resume without re-uploading successful chunks.')}
    finally{setBusy('')}
  }
  async function confirm(){
    if(!job?.confirmation_token||!job?.write_enabled||busy)return
    if(!window.confirm('Import these records into Neon? Contacts may be created, but messages stay unsent drafts.'))return
    setBusy('confirm');setError('')
    try{
      const result=await api(prefix+'/'+job.id+'/confirm',keyValue,'POST',
        {confirmation_token:job.confirmation_token})
      setConfirmed(true)
      setNote(result.message)
      await refreshJob(job.id)
    }catch(e){setError(e.message)}
    finally{setBusy('')}
  }
  const s=job?.preview_summary
  const processing=['queued','processing'].includes(job?.status)
  const progress=percent(job?.processed_rows,job?.rows_total)
  return <section className="ld-bulk">
    <div className="ld-bulk-title">
      <div><span>HIGH-CAPACITY IMPORT</span><strong>Bulk upload · up to 50,000 records</strong>
        <p>Encrypted chunk uploads, database checkpoints, automatic progress updates and safe retry after interruption.</p></div>
      <button type="button" aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}>
        {expanded?'Hide bulk uploader ↑':'Open bulk uploader ↓'}</button>
    </div>
    {expanded&&<div className="ld-bulk-content">
      <label>Select CSV or Excel (maximum 64 MB, 50,000 records)
        <input type="file" accept=".csv,.xlsx,.xlsm" onChange={e=>{
          const chosen=e.target.files?.[0]||null
          setFile(chosen);setError('');setNote('')
          if(chosen&&chosen.size>MAX_BYTES)setError('The maximum supported file size is 64 MB.')
        }}/></label>
      <button type="button" className="ld-bulk-primary" onClick={upload}
        disabled={!file||Boolean(busy)||(file.size>MAX_BYTES)}>
        {busy==='upload'?'Uploading / verifying…':'Upload and preview in background'}</button>
      {busy==='upload'&&<div className="ld-bulk-progress"><span>Transferring encrypted chunks · {stageProgress}%</span>
        <progress max="100" value={stageProgress}/></div>}
      {job&&<div className="ld-bulk-job">
        <div className="ld-bulk-status"><strong>{job.filename}</strong>
          <span>{String(job.status).replaceAll('_',' ')}</span></div>
        {['uploading','previewing'].includes(job.status)&&
          <p>Uploaded {job.parts_received||0} of {job.parts||0} parts.
            Validation runs in the background without sending emails.</p>}
        {s&&<div className="ld-bulk-counts">
          {[
            ['Found',s.rows_total],['New contacts',s.created],
            ['Existing / linked',s.linked],['Suppressed',s.suppressed],
            ['Invalid',s.invalid],['Excluded old statuses',s.skipped_duplicate],
            ['Unsent drafts',s.first_message_drafts]
          ].map(([label,value])=><div key={label}><strong>{value||0}</strong><small>{label}</small></div>)}
        </div>}
        {job.preview_sample?.length>0&&<details className="ld-bulk-samples">
          <summary>Review first {job.preview_sample.length} records</summary>
          <div>{job.preview_sample.map(x=><p key={x.row}>
            <strong>Row {x.row} — {x.name}</strong> · {x.email||x.website||'No contact'} · {x.disposition}
            {x.reason?' — '+x.reason:''}
          </p>)}</div>
        </details>}
        {job.status==='ready'&&<div className="ld-bulk-confirm">
          <p>Review the totals before importing. No personalized messages will be sent.</p>
          {job.write_enabled
            ?<button type="button" className="ld-bulk-primary" disabled={Boolean(busy)} onClick={confirm}>
                Confirm import of {s?.rows_total||0} rows</button>
            :<p className="ld-bulk-locked">Database importing is disabled on this preview until acceptance testing.</p>}
        </div>}
        {processing&&<div className="ld-bulk-progress"><span>Saving in 500-row transactions · {progress}% · {job.processed_rows||0} / {job.rows_total||'?'} rows</span>
          <progress max="100" value={progress}/><small>Progress is persisted in Neon. You may return to this page later.</small></div>}
        {job.status==='completed'&&<p className="ld-bulk-done">Import completed. Saved/linked {job.accepted_rows||0}; skipped {job.skipped_rows||0}. No emails were sent.</p>}
      </div>}
      {error&&<p className="ld-bulk-error" role="alert">{error}</p>}
      {note&&<p className="ld-bulk-note" role="status">{note}</p>}
      <div className="ld-bulk-history"><div><strong>Recent bulk jobs</strong><button type="button" onClick={refreshJobs}>Refresh</button></div>
        {jobs.length?jobs.map(item=><button key={item.id} className="ld-bulk-historyitem" type="button"
          onClick={()=>refreshJob(item.id)}>
          <span>{item.filename}<small>{new Date(item.created_at).toLocaleString()}</small></span>
          <span>{item.status.replaceAll('_',' ')} · {item.processed_rows||0} rows</span>
        </button>):<p>No large-file jobs yet.</p>}
      </div>
    </div>}
  </section>
}
