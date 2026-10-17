import React,{useEffect,useRef,useState} from 'react'
import './import-studio.css'

const MAX_FILE_BYTES=8*1024*1024
const API=(import.meta.env.VITE_API_BASE_URL||'https://author-scout-team-bot.onrender.com').replace(/\/$/,'')

async function transfer(path,key,method='GET',file=null,token=''){
  const controller=new AbortController()
  const timer=setTimeout(()=>controller.abort(),105000)
  try{
    const headers=key?{'X-Author-Scout-Key':key}:{}
    const options={method,headers,signal:controller.signal}
    if(file){
      const form=new FormData()
      form.append('file',file,file.name)
      if(token)form.append('preview_token',token)
      options.body=form
    }
    const response=await fetch(API+path,options)
    const body=await response.json().catch(()=>({}))
    if(!response.ok)throw new Error(body.detail||'The import request could not be completed.')
    return body
  }catch(e){
    if(e.name==='AbortError')throw new Error('Import timed out. Check your connection and try previewing again.')
    throw e
  }finally{clearTimeout(timer)}
}

export default function ImportStudio({serviceKey,keyValue,active,onImported}) {
  const fileRef=useRef(null)
  const [file,setFile]=useState(null)
  const [preview,setPreview]=useState(null)
  const [imports,setImports]=useState([])
  const [busy,setBusy]=useState('')
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [expanded,setExpanded]=useState(false)
  const [undoPreview,setUndoPreview]=useState(null)
  const [undoFilename,setUndoFilename]=useState('')

  async function history(){
    if(!keyValue||!active)return
    try{
      const data=await transfer('/api/v2/letterdesk/services/'+serviceKey+'/imports',keyValue)
      setImports(data.imports||[])
    }catch(e){setError(e.message)}
  }
  useEffect(()=>{if(active&&keyValue&&expanded)history()},[active,keyValue,serviceKey,expanded])

  function chooseFile(next) {
    setFile(next||null)
    setPreview(null)
    setError('');setNotice('')
    if(next&&next.size>MAX_FILE_BYTES)setError('This file exceeds the 8 MB import limit.')
    else if(next&&!/\.(csv|xlsx|xlsm)$/i.test(next.name))setError('Choose a CSV or Excel workbook (.xlsx / .xlsm).')
  }

  async function downloadTemplate(){
    setError('')
    try{
      const response=await fetch(API+'/api/v2/letterdesk/services/'+serviceKey+'/imports/template.csv',{
        headers:{'X-Author-Scout-Key':keyValue}
      })
      if(!response.ok)throw new Error('The template is temporarily unavailable')
      const blob=await response.blob()
      const url=URL.createObjectURL(blob)
      const anchor=document.createElement('a')
      anchor.href=url
      anchor.download='LetterDesk_'+serviceKey+'_Import_Template.csv'
      document.body.appendChild(anchor);anchor.click();anchor.remove()
      setTimeout(()=>URL.revokeObjectURL(url),2000)
    }catch(e){setError(e.message)}
  }

  async function previewFile(){
    if(!file||error||busy)return
    setBusy('preview');setPreview(null);setError('');setNotice('')
    try{
      const p=await transfer('/api/v2/letterdesk/services/'+serviceKey+'/imports/preview',keyValue,'POST',file)
      setPreview(p)
      if(!p.write_enabled)setNotice('Preview is ready. Saving to staging is still locked until account and import safety checks pass.')
    }catch(e){setError(e.message)}
    finally{setBusy('')}
  }

  async function confirm(){
    if(!preview?.write_enabled||!preview.preview_token||busy)return
    const count=(preview.summary?.created||0)+(preview.summary?.linked||0)+(preview.summary?.suppressed||0)
    if(!count){setError('No importable or suppressible rows in this file.');return}
    setBusy('import');setError('')
    try{
      const result=await transfer('/api/v2/letterdesk/services/'+serviceKey+'/imports/confirm',
        keyValue,'POST',file,preview.preview_token)
      setNotice('Saved '+(result.summary?.created||0)+' new leads; '+(result.summary?.linked||0)+
        ' linked. Any first messages are UNSENT drafts awaiting review.')
      setPreview(null);setFile(null)
      if(fileRef.current)fileRef.current.value=''
      await history()
      onImported?.()
    }catch(e){setError(e.message)}
    finally{setBusy('')}
  }
  async function viewUndo(batch){
    setBusy('undo-preview');setError('');setNotice('');setUndoPreview(null)
    try{
      const p=await transfer('/api/v2/letterdesk/services/'+serviceKey+
        '/imports/'+encodeURIComponent(batch.id)+'/undo-preview',keyValue)
      setUndoPreview(p);setUndoFilename('')
    }catch(e){setError(e.message||'Could not inspect undo safety.')}
    finally{setBusy('')}
  }

  async function confirmUndo(){
    if(!undoPreview?.write_enabled||!undoPreview?.summary?.eligible||
        undoFilename!==undoPreview.filename||busy)return
    if(!window.confirm('Undo the selected import? Unused records may be removed permanently. Suppressions will remain.'))return
    setBusy('undo');setError('');setNotice('')
    try{
      const controller=new AbortController()
      const timer=setTimeout(()=>controller.abort(),60000)
      let response
      try{
        response=await fetch(API+'/api/v2/letterdesk/services/'+serviceKey+'/imports/'+
          encodeURIComponent(undoPreview.batch_id)+'/undo',{
            method:'POST',headers:{'X-Author-Scout-Key':keyValue,'Content-Type':'application/json'},
            body:JSON.stringify({filename:undoFilename,confirmation_token:undoPreview.confirmation_token}),
            signal:controller.signal
          })
      }finally{clearTimeout(timer)}
      const data=await response.json().catch(()=>({}))
      if(!response.ok)throw new Error(data.detail||'Import undo was not completed.')
      setNotice('Import reversed. '+(data.summary?.removed_drafts||0)+' unused drafts and '+
        (data.summary?.removed_leads||0)+' unshared leads removed. Shared contacts and opt-outs kept.')
      setUndoPreview(null);setUndoFilename('')
      await history()
      onImported?.()
    }catch(e){setError(e.message||'Unable to reverse import. No changes were confirmed.')}
    finally{setBusy('')}
  }

  const s=preview?.summary||{}
  return <section className="ld-import-card" aria-label="Service import workspace">
    <div className="ld-import-top">
      <div><span className="ld-import-kicker">SERVICE DATABASE / BULK IMPORT</span>
        <h3>Import prospects and message paths</h3>
        <p>Excel or CSV. First messages and Yes/No message branches are entirely optional.</p></div>
      <div className="ld-import-actions">
        <button type="button" onClick={downloadTemplate}>↓ Download template</button>
        <button type="button" onClick={()=>setExpanded(!expanded)} aria-expanded={expanded}>
          {expanded?'Hide importer ↑':'Open importer ↓'}</button>
      </div>
    </div>

    {expanded&&<div className="ld-import-content">
      <div className="ld-import-guidance">
        <strong>What your file can include</strong>
        <p>Prospect name plus email or website; service-specific research fields; source URL; optional subject,
        first message and branches such as <code>Message01</code>, <code>Message0101Yes</code> and <code>Message0101No</code>.</p>
        <p>The system checks duplicates, opt-outs, missing information and old sent statuses. It never sends imported messages automatically.</p>
      </div>

      <div className="ld-import-file">
        <label htmlFor={'ld-import-'+serviceKey}>Choose an Excel or CSV file (maximum 8 MB, 5,000 records)</label>
        <input ref={fileRef} id={'ld-import-'+serviceKey} type="file" accept=".csv,.xlsx,.xlsm,text/csv" onChange={e=>chooseFile(e.target.files?.[0]||null)} />
        <button disabled={!file||busy||Boolean(error)} type="button" onClick={previewFile}>
          {busy==='preview'?'Validating file…':'Preview and check duplicates'}
        </button>
      </div>

      {preview&&<div className="ld-import-preview">
        <div className="ld-import-preview-head"><div>
          <strong>Import preview · {preview.filename}</strong>
          <p>{preview.sheet} · {s.rows_total||0} rows found · not yet saved</p></div>
          <small>{(preview.branch_columns||[]).length} message-branch columns recognized</small></div>
        <div className="ld-import-metrics">
          {[
            ['New contacts',s.created],['Existing / linked',s.linked],
            ['Suppressed',s.suppressed],['Invalid rows',s.invalid],
            ['Excluded old statuses',s.skipped_duplicate],['Possible review drafts',s.first_message_drafts],
          ].map(([label,count])=><div key={label}><strong>{count||0}</strong><span>{label}</span></div>)}
        </div>
        <div className="ld-import-scroll">
          <table><thead><tr><th>Row</th><th>Prospect</th><th>Email</th><th>Action</th><th>Messages</th></tr></thead>
          <tbody>{(preview.sample||[]).map(x=><tr key={x.row}>
            <td>{x.row}</td><td><strong>{x.name||'Missing name'}</strong><small>{x.reason||x.website||''}</small></td>
            <td>{x.email||'—'}</td><td><span className={'ld-import-tag '+x.disposition}>{String(x.disposition||'').replaceAll('_',' ')}</span></td>
            <td>{x.first_message?'Draft · ':''}{(x.branches||[]).length} branches</td>
          </tr>)}</tbody></table>
        </div>
        {s.rows_total>25&&<p className="ld-import-footnote">Displaying 25 sample rows; all {s.rows_total} were validated.</p>}
        {preview.write_enabled
          ? <button className="ld-import-confirm" type="button" disabled={Boolean(busy)||!(s.created+s.linked+s.suppressed)}
              onClick={confirm}>{busy==='import'?'Saving to Neon…':'Confirm and save reviewed import'}</button>
          : <p className="ld-import-locked">Saving is disabled on this preview. The file has not been written to Neon.</p>}
      </div>}
      {error&&<p className="ld-import-error" role="alert">{error}</p>}
      {notice&&<p className="ld-import-notice" role="status">{notice}</p>}
      <div className="ld-import-history">
        <div className="ld-import-history-head"><strong>Previous imports for this service</strong>
          <button onClick={history} type="button">Refresh</button></div>
        {imports.length?<ul>{imports.slice(0,8).map(x=><li key={x.id}>
            <span>{x.filename} <small>{new Date(x.created_at).toLocaleString()} · {x.status.replaceAll('_',' ')}</small></span>
            <span>{x.rows_imported||0} accepted · {x.rows_skipped||0} skipped
              {x.status==='completed'&&<button type="button" disabled={Boolean(busy)}
                onClick={()=>viewUndo(x)} className="ld-import-undo-trigger">Review undo</button>}
            </span>
          </li>)}</ul>:<p>No completed imports recorded yet.</p>}
        {undoPreview&&<div className="ld-import-undo-panel">
          <strong>Review import reversal · {undoPreview.filename}</strong>
          <p>{undoPreview.summary.draft_messages} imported message drafts · {undoPreview.summary.owned_opportunities} batch-owned opportunities · {undoPreview.summary.owned_leads} batch-owned leads.</p>
          <p>Messages already sent or queued: {undoPreview.summary.changed_messages+undoPreview.summary.queued_messages}.
            Replies: {undoPreview.summary.replied_conversations}. Shared or researched contacts will be retained.
            Do-not-contact records are never removed by undo.</p>
          {!undoPreview.summary.eligible?<p className="ld-import-error">Automatic undo is blocked because records have been used, edited or answered.</p>
          : !undoPreview.write_enabled?<p className="ld-import-locked">Undo is disabled in this protected preview.</p>
          : <><label>Type the complete filename to confirm
                <input value={undoFilename} onChange={e=>setUndoFilename(e.target.value)}
                  placeholder={undoPreview.filename} autoComplete="off" /></label>
              <button type="button" disabled={Boolean(busy)||undoFilename!==undoPreview.filename}
                onClick={confirmUndo} className="ld-import-undo-danger">Undo unused imported records</button></>}
          <button type="button" onClick={()=>setUndoPreview(null)}>Cancel</button>
        </div>}
      </div>
    </div>}
  </section>
}