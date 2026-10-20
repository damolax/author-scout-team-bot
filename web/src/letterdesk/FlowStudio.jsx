import React,{useEffect,useMemo,useState} from 'react'
import './flow-studio.css'
import FlowCanvas from './FlowCanvas.jsx'
import {canLink} from './flow-geometry.js'

const OUTCOMES=['yes','no','positive','question','objection','not_now','negative','opt_out','no_reply','bounce','uncertain']
const ACTIONS=['draft_for_review','manual_review','wait','stop']
const STAGES=['initial','interested','question','objection','followup','proposal_discussion','alternative','terminal','generic','not_now','success']
const FRIENDLY={yes:'Yes',no:'No',positive:'Positive',question:'Question',objection:'Objection',not_now:'Not now',negative:'Explicit decline',opt_out:'Opt out',no_reply:'No reply',bounce:'Bounce',uncertain:'Uncertain'}
const COLOR={yes:'#238a56',no:'#bd7547',positive:'#40a777',question:'#5b84c9',objection:'#a87a48',not_now:'#a98a58',negative:'#ca5955',opt_out:'#cb5955',bounce:'#a84d55',no_reply:'#6a83aa',uncertain:'#8b8492'}
const START='Message01'
function copy(value){return JSON.parse(JSON.stringify(value))}
function rootNode(document){return document.nodes.find(n=>n.code===START) || document.nodes[0]}
function graphLayout(doc){
  const nodes=doc?.nodes||[]
  const edges=doc?.edges||[]
  const depth=new Map()
  const queue=[START]
  depth.set(START,0)
  while(queue.length){
    const p=queue.shift()
    const d=depth.get(p)
    for(const e of edges.filter(x=>x.from===p&&x.to)){
      if(!depth.has(e.to)&&d<10){depth.set(e.to,d+1);queue.push(e.to)}
    }
  }
  const max=depth.size?Math.max(...depth.values()):0
  nodes.forEach(n=>{if(!depth.has(n.code))depth.set(n.code,max+1)})
  const bands=new Map()
  for(const n of nodes){
    const d=depth.get(n.code)||0
    if(!bands.has(d))bands.set(d,[])
    bands.get(d).push(n.code)
  }
  const positions={}
  for(const [d,codes] of bands){
    codes.forEach((code,i)=>{positions[code]={x:25+d*275,y:23+i*139}})
  }
  const maxCol=Math.max(...bands.keys(),0)
  const maxRows=Math.max(...[...bands.values()].map(x=>x.length),1)
  return {positions,width:Math.max(550,(maxCol+1)*275+50),height:Math.max(260,maxRows*139+24)}
}
const defaultVariant=(id)=>({id,subject:'',body:''})
function splitLabel(code){return code.replace(/(Yes|NoReply|No|Question|Objection|Later|Review|OptOut|Bounce)$/,' / $1')}
function emptyNode(code){return {code,stage:'generic',subject:'',body:'',delayMinutes:0,reviewRequired:true,variants:[]}}
function parseError(err){return typeof err?.message==='string'?err.message:'Could not complete the request'}

export default function FlowStudio({serviceKey,keyValue,request,active ,standalone=false}){
  const [open,setOpen]=useState(standalone)
  const [saved,setSaved]=useState([])
  const [flowId,setFlowId]=useState('')
  const [revision,setRevision]=useState(0)
  const [name,setName]=useState('')
  const [language,setLanguage]=useState('en')
  const [doc,setDoc]=useState(null)
  const [selected,setSelected]=useState(START)
  const [selectedOutcome,setSelectedOutcome]=useState('yes')
  const [messageCount,setMessageCount]=useState(0)
  const [noReplyCount,setNoReplyCount]=useState(0)
  const [simulation,setSimulation]=useState(null)
  const [validation,setValidation]=useState(null)
  const [notice,setNotice]=useState('')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState('')
  const [writeEnabled,setWriteEnabled]=useState(false)
  const [newBranch,setNewBranch]=useState({outcome:'question',action:'draft_for_review',to:''})

  async function fetchJson(path,options={}){
    return request('/api/v2/letterdesk/services/'+serviceKey+'/flows'+path,keyValue,options)
  }
  async function loadIndex(){
    if(!keyValue||!active)return
    const data=await fetchJson('')
    setSaved(data.flows||[])
    setWriteEnabled(Boolean(data.write_enabled))
  }
  async function startNew(){
    setBusy('starter');setError('');setNotice('')
    try{
      const starter=await fetchJson('/starter')
      const template=starter.document
      setDoc(template)
      setName((serviceKey.replaceAll('-',' ')+' conversation').replace(/^./,x=>x.toUpperCase()))
      setLanguage('en');setFlowId('');setRevision(0)
      setSelected(START);setSimulation(null);setValidation(null)
    }catch(e){setError(parseError(e))}
    finally{setBusy('')}
  }
  useEffect(()=>{
    setDoc(null);setFlowId('');setRevision(0)
    setSaved([]);setValidation(null);setSimulation(null)
    setSelected(START);setName('');setError('');setNotice('')
    setOpen(standalone);setWriteEnabled(false)
  },[serviceKey])
  useEffect(()=>{
    if(!active||!keyValue||!open)return
    let cancel=false
    async function initial(){
      try{
        const [index,starter]=await Promise.all([fetchJson(''),fetchJson('/starter')])
        if(cancel)return
        setSaved(index.flows||[])
        setWriteEnabled(Boolean(index.write_enabled))
        setDoc(current=>current||starter.document)
        setName(n=>n||'New '+serviceKey.replaceAll('-',' ')+' conversation')
      }catch(e){if(!cancel)setError(parseError(e))}
    }
    initial()
    return()=>{cancel=true}
  },[active,serviceKey,keyValue,open])

  const positions=useMemo(()=>graphLayout(doc),[doc])
  const selectedNode=doc?.nodes?.find(n=>n.code===selected)
  const edgesFromSelected=doc?.edges?.filter(x=>x.from===selected)||[]
  const canWrite=writeEnabled&&Boolean(keyValue)

  function editDoc(editor){
    setDoc(before=>{
      if(!before)return before
      const next=copy(before)
      editor(next)
      return next
    })
    setValidation(null);setSimulation(null);setNotice('')
  }
  function editNode(key,value){
    editDoc(next=>{const node=next.nodes.find(n=>n.code===selected);if(node)node[key]=value})
  }
  function renameSelected(value){
    if(!doc)return
    const name=value.trim()
    if(!/^(Message[0-9]{2,8}(Yes|No|Question|Objection|Later|NoReply|Review|OptOut|Bounce)?|MSG-[0-9]{2,6})$/.test(name)){
      setError('Use Message01 or a branch name such as Message0101Yes.')
      return
    }
    if(doc.nodes.some(n=>n.code===name&&n.code!==selected)){setError('That message code is already used.');return}
    editDoc(next=>{
      next.nodes.find(n=>n.code===selected).code=name
      next.edges.forEach(e=>{if(e.from===selected)e.from=name;if(e.to===selected)e.to=name;if(e.branchLabel===selected)e.branchLabel=name})
    })
    setSelected(name);setError('')
  }
  function createNode(){
    if(!doc||doc.nodes.length>=45)return
    let i=1,code
    do{code='Message'+String(300+i).padStart(4,'0')+'Yes';i++}while(doc.nodes.some(n=>n.code===code)&&i<400)
    editDoc(next=>next.nodes.push(emptyNode(code)))
    setSelected(code)
  }
  function addAfter(from,outcome){
    if(!doc)return
    const root=doc.nodes.find(n=>n.code===from)
    if(!root||['terminal','success'].includes(root.stage)){setError('Completed messages cannot have outgoing branches.');return}
    const existing=doc.edges.find(e=>e.from===from&&e.outcome===outcome)
    if(existing){if(existing.to)setSelected(existing.to);setError('This response branch already exists. Edit it instead.');return}
    if(doc.nodes.length>=45||doc.edges.length>=120){setError('This template has reached its safe graph limit.');return}
    const stop=['negative','opt_out','bounce'].includes(outcome)
    let code=''
    if(!stop){
      let index=1
      do{
        const suffix=outcome==='yes'||outcome==='positive'?'Yes':outcome==='no'?'No':
          outcome==='question'?'Question':outcome==='objection'?'Objection':
          outcome==='not_now'?'Later':outcome==='no_reply'?'NoReply':'Review'
        code='Message'+String(500000+index)+suffix;index++
      }while(doc.nodes.some(n=>n.code===code))
    }
    editDoc(next=>{
      if(!stop)next.nodes.push(emptyNode(code))
      next.edges.push({from,outcome,to:stop?null:code,action:stop?'stop':'draft_for_review',
        ...(outcome==='no_reply'?{delayMinutes:10080}:{})})
    })
    if(!stop)setSelected(code)
    setError('')
  }
  function connectExisting(from,to,outcome){
    if(!doc)return
    const reason=canLink(doc,from,to,outcome)
    if(reason){setError(reason);return}
    if(doc.edges.length>=120){setError('Template reached its branch limit');return}
    editDoc(next=>next.edges.push({from,to,outcome,action:'draft_for_review',
      ...(outcome==='no_reply'?{delayMinutes:10080}:{})}))
    setSelected(to);setError('')
  }
  function removeSelected(){
    if(selected===START||!doc||!window.confirm('Delete this message and all branches connected to it?'))return
    const code=selected
    editDoc(next=>{
      next.nodes=next.nodes.filter(n=>n.code!==code)
      next.edges=next.edges.filter(e=>e.from!==code&&e.to!==code&&e.branchLabel!==code)
    })
    setSelected(START)
  }
  function editEdge(index,key,value){
    editDoc(next=>{
      const indices=next.edges.map((e,i)=>({i,e})).filter(x=>x.e.from===selected)
      const target=next.edges[indices[index]?.i]
      if(!target)return
      if(key==='action'){
        target.action=value
        if(value==='stop')target.to=null
        if(value!=='stop')delete target.branchLabel
      }else if(key==='to')target.to=value||null
      else if(key==='branchLabel')target.branchLabel=value||undefined
      else target[key]=value
      if(['negative','opt_out','bounce'].includes(target.outcome)){
        target.action='stop';target.to=null
      }
    })
  }
  function appendBranch(){
    if(!doc)return
    const existing=doc.edges.some(e=>e.from===selected&&e.outcome===newBranch.outcome)
    if(existing){setError('This message already has a branch for that reply. Edit the existing branch instead.');return}
    if(doc.edges.length>=120){setError('The editor supports up to 120 branches per template.');return}
    const terminal=['negative','opt_out','bounce'].includes(newBranch.outcome)
    const action=terminal?'stop':newBranch.action
    const target=action==='stop'?null:(newBranch.to||null)
    if(action!=='stop'&&action!=='manual_review'&&!target){setError('Choose a target message.');return}
    const entry={from:selected,outcome:newBranch.outcome,to:target,action}
    if(newBranch.outcome==='no_reply')entry.delayMinutes=10080
    editDoc(next=>next.edges.push(entry))
    setError('')
  }
  function deleteBranch(index){
    editDoc(next=>{
      const hit=next.edges.map((e,i)=>({e,i})).filter(x=>x.e.from===selected)[index]
      if(hit)next.edges.splice(hit.i,1)
    })
  }
  function addVariant(){
    if(!selectedNode||selectedNode.variants.length>=8)return
    const id=String.fromCharCode(65+selectedNode.variants.length)
    editDoc(next=>next.nodes.find(n=>n.code===selected).variants.push(defaultVariant(id)))
  }
  function editVariant(index,key,value){
    editDoc(next=>next.nodes.find(n=>n.code===selected).variants[index][key]=value)
  }
  async function validate(){
    if(!doc)return
    setBusy('validate');setError('');setNotice('')
    try{
      const result=await fetchJson('/validate',{method:'POST',body:JSON.stringify(doc)})
      setValidation(result);setNotice(result.ok?'Validated: the draft branches are structurally sound. No messages sent.':'Review the highlighted issues below.')
    }catch(e){setError(parseError(e))}
    finally{setBusy('')}
  }
  async function simulate(){
    if(!doc)return
    setBusy('simulate');setError('');setSimulation(null)
    try{
      const r=await fetchJson('/simulate',{method:'POST',body:JSON.stringify({
        document:doc,current:selected,outcome:selectedOutcome,
        messageCount,noReplyFollowups:noReplyCount})})
      setSimulation(r.result)
    }catch(e){setError(parseError(e)+' — validate the flow before simulating.')}
    finally{setBusy('')}
  }
  async function save(){
    if(!canWrite||!doc)return
    setBusy('save');setError('');setNotice('')
    try{
      const checked=await fetchJson('/validate',{method:'POST',body:JSON.stringify(doc)})
      setValidation(checked)
      if(!checked.ok){setError('Fix the validation errors before saving.');return}
      const method=flowId?'PUT':'POST'
      const endpoint=flowId?'/'+flowId:''
      const body={name,language,document:doc,...(flowId?{expectedRevision:revision}:{})}
      const r=await fetchJson(endpoint,{method,body:JSON.stringify(body)})
      setFlowId(r.id);setRevision(r.revision)
      setNotice('Draft revision '+r.revision+' saved. Nothing has been published or sent.')
      await loadIndex()
    }catch(e){setError(parseError(e))}
    finally{setBusy('')}
  }
  async function loadFlow(id){
    if(!id)return startNew()
    setBusy('load');setError('')
    try{
      const r=await fetchJson('/'+id)
      setFlowId(r.flow.id);setRevision(r.flow.revision)
      setDoc(r.flow.document);setName(r.flow.name);setLanguage(r.flow.language||'en')
      setSelected(rootNode(r.flow.document).code);setValidation(null);setSimulation(null)
      setNotice('Loaded saved draft revision '+r.flow.revision+'.')
    }catch(e){setError(parseError(e))}
    finally{setBusy('')}
  }
  async function archive(){
    if(!canWrite||!flowId||!window.confirm('Archive this draft? Its revision history will remain available.'))return
    setBusy('archive');setError('')
    try{
      await fetchJson('/'+flowId+'/archive',{method:'POST',body:'{}'})
      setNotice('Draft archived. Conversation records were not changed.')
      await loadIndex()
      await startNew()
    }catch(e){setError(parseError(e))}
    finally{setBusy('')}
  }
  return <section className= "ld-flow" aria-label="Conversation automation designer">
    <div className="ld-flow-heading">
      <div>
        <span className="ld-flow-kicker">VISUAL AUTOMATION / CONVERSATION DESIGN</span>
        <h3>Conversation Builder</h3>
        <p>Create the paths behind every message: interest, questions, objections, No, follow-ups and opt-outs.</p>
      </div>
      <button className="ld-flow-toggle" type="button" onClick={()=>setOpen(v=>!v)} aria-expanded={open}>
        {open?'Close builder ↑':'Open builder ↓'}
      </button>
    </div>
    {open&&doc&&<div className="ld-flow-main">
      <div className="ld-flow-toolbar">
        <div className="ld-flow-identity">
          <label>Template name<input value={name} maxLength={110} onChange={e=>setName(e.target.value)} /></label>
          <label>Saved templates<select value={flowId} onChange={e=>loadFlow(e.target.value)}>
            <option value="">Unsaved new template</option>
            {saved.map(x=><option value={x.id} key={x.id}>{x.name} · r{x.revision}{x.status==='archived'?' [archived]':''}</option>)}
          </select></label>
        </div>
        <div className="ld-flow-toolbar-buttons">
          <button type="button" onClick={startNew} disabled={Boolean(busy)}>＋ New</button>
          <button type="button" onClick={validate} disabled={Boolean(busy)}>Check flow</button>
          <button type="button" className="ld-flow-save" onClick={save} disabled={!canWrite||Boolean(busy)}>{busy==='save'?'Saving…':'Save draft'}</button>
          {flowId&&<button type="button" onClick={archive} disabled={!canWrite||Boolean(busy)}>Archive</button>}
        </div>
      </div>
      {!canWrite&&<div className="ld-flow-lock" role="status">
        Read-only staging: you can edit the sample in this browser, test branches and validate it. Saving templates is currently disabled pending login and persistence acceptance.
      </div>}
      <div className="ld-flow-summary">
        <label>Messages per contact
          <select value={doc.maxMessagesPerContact} onChange={e=>editDoc(d=>d.maxMessagesPerContact=Number(e.target.value))}>
            {Array.from({length:12},(_,i)=><option key={i} value={i+1}>{i+1}</option>)}
          </select>
        </label>
        <label>No-reply follow-ups
          <select value={doc.maxNoReplyFollowups} onChange={e=>editDoc(d=>d.maxNoReplyFollowups=Number(e.target.value))}>
            {[0,1,2,3].map(n=><option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <label>Language<input value={language} onChange={e=>setLanguage(e.target.value)} maxLength={12}/></label>
        <span>{doc.nodes.length} message nodes · {doc.edges.length} decision paths · revision {revision||'unsaved'}</span>
      </div>

      <div className="ld-flow-section-top"><strong>Visual decision map</strong><span>Select any message to edit it. Connect messages using outcome rules below.</span></div>
      <FlowCanvas doc={doc} selected={selected} onSelect={code=>{setSelected(code);setSimulation(null)}}
         onAdd={addAfter} onConnect={connectExisting}/>
       <div className="ld-flow-editor">
        <div className="ld-flow-edit-panel">
          <div className="ld-flow-section-top"><strong>Message editor</strong>
            <div><button type="button" onClick={createNode} disabled={doc.nodes.length>=45}>＋ Add message</button>
              <button type="button" onClick={removeSelected} disabled={selected===START}>Remove</button></div>
          </div>
          {selectedNode&&<div className="ld-flow-fields">
            <label>Message ID
              <input key={'code-'+selected} defaultValue={selectedNode.code} onBlur={e=>{if(e.target.value!==selectedNode.code)renameSelected(e.target.value)}}/>
              <small>Examples: Message01, Message0101Yes, Message0101No</small></label>
            <label>Stage<select value={selectedNode.stage} onChange={e=>editNode('stage',e.target.value)}>
              {STAGES.map(s=><option key={s} value={s}>{s.replaceAll('_',' ')}</option>)}</select></label>
            <label>Subject<input value={selectedNode.subject||''} onChange={e=>editNode('subject',e.target.value)} maxLength={400} placeholder="Optional: can inherit thread subject" /></label>
            <label>Message content<textarea value={selectedNode.body||''} onChange={e=>editNode('body',e.target.value)} maxLength={16000}
              rows={6} placeholder={selectedNode.stage==='terminal'?'Terminal branch: no reply is sent':'Write a carefully researched and appropriate message…'} /></label>
            <div className="ld-flow-node-hint">Every message requires review. Placeholders include <code>{'{{first_name}}'}</code>, <code>{'{{book_title}}'}</code>, and <code>{'{{evidence_observation}}'}</code>. Claims must be verified before use.</div>
            <div className="ld-flow-variants-top"><strong>Alternative versions</strong><button type="button" onClick={addVariant} disabled={selectedNode.variants.length>=8}>＋ Add variant</button></div>
            {selectedNode.variants.map((v,i)=><div className="ld-flow-variant" key={i}>
              <label>Variant ID<input value={v.id} onChange={e=>editVariant(i,'id',e.target.value)} maxLength={32}/></label>
              <label>Subject<input value={v.subject||''} onChange={e=>editVariant(i,'subject',e.target.value)} maxLength={400}/></label>
              <label>Body<textarea rows={3} maxLength={16000} value={v.body||''} onChange={e=>editVariant(i,'body',e.target.value)} /></label>
              <button type="button" onClick={()=>editDoc(d=>{d.nodes.find(n=>n.code===selected).variants.splice(i,1)})}>Remove variant</button>
            </div>)}
          </div>}
        </div>
        <div className="ld-flow-edit-panel">
          <div className="ld-flow-section-top"><strong>Response branches</strong><span>When a prospect replies to {selected}</span></div>
          <div className="ld-flow-edges">
            {edgesFromSelected.length===0&&<p className="ld-flow-muted">No responses configured yet.</p>}
            {edgesFromSelected.map((e,i)=><div className="ld-flow-edge" key={selected+'-'+i}>
              <div className="ld-flow-edge-head"><b style={{color:COLOR[e.outcome]}}>{FRIENDLY[e.outcome]}</b><button type="button" onClick={()=>deleteBranch(i)}>Remove</button></div>
              <label>Reply outcome<select value={e.outcome} onChange={ev=>editEdge(i,'outcome',ev.target.value)}>
                {OUTCOMES.map(x=><option key={x} value={x}>{FRIENDLY[x]}</option>)}</select></label>
              <label>Action<select value={e.action} onChange={ev=>editEdge(i,'action',ev.target.value)}
                disabled={['negative','opt_out','bounce'].includes(e.outcome)}>
                {ACTIONS.map(x=><option key={x} value={x}>{x.replaceAll('_',' ')}</option>)}</select></label>
              {e.action!=='stop'&&<label>Next message<select value={e.to||''} onChange={ev=>editEdge(i,'to',ev.target.value)}>
                <option value="">Review without selected message</option>
                {doc.nodes.filter(n=>n.code!==selected).map(n=><option key={n.code} value={n.code}>{n.code}</option>)}
              </select></label>}
              {e.action==='stop'&&<label>Terminal label (optional)<select value={e.branchLabel||''} onChange={ev=>editEdge(i,'branchLabel',ev.target.value)}>
                <option value="">Stop without label</option>
                {doc.nodes.filter(n=>n.stage==='terminal').map(n=><option key={n.code} value={n.code}>{n.code}</option>)}
              </select></label>}
              {e.outcome==='no_reply'&&<label>Wait before reviewed follow-up (days)
                <input type="number" min="1" max="365" value={Math.round((e.delayMinutes||10080)/1440)}
                  onChange={ev=>editEdge(i,'delayMinutes',Number(ev.target.value)*1440)}/></label>}
            </div>)}
          </div>
          <div className="ld-flow-add-edge">
            <strong>Add a decision path</strong>
            <label>Reply<select value={newBranch.outcome} onChange={e=>setNewBranch(b=>({...b,outcome:e.target.value}))}>
              {OUTCOMES.map(x=><option key={x} value={x}>{FRIENDLY[x]}</option>)}</select></label>
            <label>Action<select value={newBranch.action} onChange={e=>setNewBranch(b=>({...b,action:e.target.value}))}>
              {ACTIONS.map(x=><option key={x} value={x}>{x.replaceAll('_',' ')}</option>)}</select></label>
            <label>Target<select value={newBranch.to} onChange={e=>setNewBranch(b=>({...b,to:e.target.value}))}>
              <option value="">No target</option>
              {doc.nodes.filter(n=>n.code!==selected).map(n=><option key={n.code} value={n.code}>{n.code}</option>)}
            </select></label>
            <button type="button" onClick={appendBranch}>＋ Add branch</button>
          </div>
        </div>
      </div>

      <div className="ld-flow-simulator">
        <div><strong>Test this conversation path</strong><p>Simulate a reply without sending or reading anyone's inbox.</p></div>
        <label>Reply outcome<select value={selectedOutcome} onChange={e=>setSelectedOutcome(e.target.value)}>
          {OUTCOMES.map(x=><option key={x} value={x}>{FRIENDLY[x]}</option>)}</select></label>
        <label>Messages already sent<input type="number" min="0" max="100" value={messageCount} onChange={e=>setMessageCount(Number(e.target.value))}/></label>
        <label>Earlier no-reply follow-ups<input type="number" min="0" max="100" value={noReplyCount} onChange={e=>setNoReplyCount(Number(e.target.value))}/></label>
        <button type="button" disabled={Boolean(busy)} onClick={simulate}>Test branch →</button>
      </div>
      {simulation&&<div className="ld-flow-simulation-result" role="status">
        <b>{simulation.action.replaceAll('_',' ')}</b>
        {simulation.nextCode&&<span> → {simulation.nextCode}</span>}
        {simulation.branchLabel&&<span> · {simulation.branchLabel}</span>}
        <small>{simulation.reason||simulation.note||'Test only; no message sent'}</small>
      </div>}
      {validation&&<div className={'ld-flow-validation '+(validation.ok?'is-ok':'is-fail')} role="status">
        <strong>{validation.ok?'✓ Flow structure is valid':'Flow has '+validation.errors.length+' issues'}</strong>
        {!!validation.errors.length&&<ul>{validation.errors.map((e,i)=><li key={i}>{e}</li>)}</ul>}
      </div>}
      {error&&<p className="ld-flow-error" role="alert">{error}</p>}
      {notice&&<p className="ld-flow-notice" role="status">{notice}</p>}
    </div>}
  </section>
}
