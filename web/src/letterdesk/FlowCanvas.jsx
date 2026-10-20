import React,{useEffect,useMemo,useRef,useState} from 'react'
import {autoLayout,orthogonalPath,NODE_W,NODE_H} from './flow-geometry.js'
import './flow-canvas.css'
const TAG={yes:'YES',positive:'INTEREST',no:'NO',question:'QUESTION',objection:'OBJECTION',not_now:'LATER',no_reply:'NO REPLY',uncertain:'REVIEW'}
export default function FlowCanvas({doc,selected,onSelect,onAdd,onConnect}){
  const computed=useMemo(()=>autoLayout(doc),[doc])
  const [manual,setManual]=useState({})
  const [zoom,setZoom]=useState(1)
  const [linkFrom,setLinkFrom]=useState('')
  const [branchFrom,setBranchFrom]=useState('')
  const [branchOutcome,setBranchOutcome]=useState('yes')
  const [notice,setNotice]=useState('')
  const [dragging,setDragging]=useState(null)
  const scroller=useRef(null)
  const positions={...computed.positions,...manual}
  const width=Math.max(computed.width,...Object.values(positions).map(p=>p.x+NODE_W+90),500)
  const height=Math.max(computed.height,...Object.values(positions).map(p=>p.y+NODE_H+100),420)
  useEffect(()=>{setManual({});setLinkFrom('');setBranchFrom('')},[doc?.serviceKey])
  useEffect(()=>{
    if(!dragging)return
    function move(e){
      if(e.pointerId!==dragging.pointerId)return
      const dx=(e.clientX-dragging.x)/zoom,dy=(e.clientY-dragging.y)/zoom
      setManual(m=>({...m,[dragging.code]:{
        x:Math.max(15,dragging.left+dx),y:Math.max(15,dragging.top+dy)}}))
    }
    function up(e){if(e.pointerId===dragging.pointerId)setDragging(null)}
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',up)
    return()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',up)}
  },[dragging,zoom])
  const useNode=(code)=>{
    if(linkFrom){
      if(linkFrom===code){setLinkFrom('');return}
      onConnect(linkFrom,code,branchOutcome)
      setLinkFrom('');setNotice('')
    }else onSelect(code)
  }
  const kind=(node)=>['terminal','success'].includes(node.stage)
  return <section className="ld-canvas-shell" aria-label="Interactive visual conversation builder">
    <div className="ld-canvas-tools">
      <span><strong>Flow canvas</strong> <small>{doc.nodes.length} messages · {doc.edges.length} paths</small></span>
      <div>
        <button type="button" onClick={()=>{setManual({});setNotice('Auto layout restored')}}>Organize flow</button>
        <button type="button" onClick={()=>setZoom(z=>Math.max(.55,Math.round((z-.1)*100)/100))}>−</button>
        <output aria-label="Canvas zoom">{Math.round(zoom*100)}%</output>
        <button type="button" onClick={()=>setZoom(z=>Math.min(1.6,Math.round((z+.1)*100)/100))}>＋</button>
        <button type="button" onClick={()=>{setZoom(1);if(scroller.current){scroller.current.scrollLeft=0;scroller.current.scrollTop=0}}}>Reset view</button>
      </div>
    </div>
    <p className="ld-canvas-instruction">Drag cards to arrange them. Use the connector ◉ to link messages, or + to create the next branch. Select a card to edit its message.</p>
    {linkFrom&&<div className="ld-canvas-linkprompt" role="status">Connecting from <strong>{linkFrom}</strong>
      <select aria-label="Response to connect" value={branchOutcome} onChange={e=>setBranchOutcome(e.target.value)}>
        {['yes','positive','no','question','objection','not_now','no_reply','uncertain'].map(x=><option value={x} key={x}>{TAG[x]}</option>)}
      </select>
      <span>Now click the destination message.</span>
      <button type="button" onClick={()=>setLinkFrom('')}>Cancel</button>
    </div>}
    {notice&&<p className="ld-canvas-notice" role="status">{notice}</p>}
    <div className="ld-canvas-viewport" ref={scroller} tabIndex={0} aria-label="Scrollable and zoomable conversation canvas">
      <div className="ld-canvas-dimensions" style={{width:width*zoom,height:height*zoom}}>
        <div className="ld-canvas-plane" style={{width,height,transform:`scale(${zoom})`}}>
          <svg className="ld-canvas-wires" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
            <defs><marker id="ld-canvas-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M1 1 L9 5 L1 9" fill="none" stroke="#669980" strokeWidth="1.5"/></marker></defs>
            {doc.edges.filter(e=>e.to&&positions[e.from]&&positions[e.to]).map((e,i)=>
              <path key={e.from+'-'+e.outcome+'-'+i} d={orthogonalPath(positions[e.from],positions[e.to])}
                stroke={e.outcome==='yes'||e.outcome==='positive'?'#5caa7d':e.outcome==='no'?'#c58e62':'#819b9b'}
                strokeWidth="1.65" strokeOpacity=".75" fill="none" markerEnd="url(#ld-canvas-arrow)" strokeLinejoin="round"/>)}
          </svg>
          {doc.nodes.map(node=>{
            const p=positions[node.code];if(!p)return null
            const terminal=kind(node)
            return <div key={node.code} style={{left:p.x,top:p.y,width:NODE_W,height:NODE_H}}
              className={'ld-canvas-node '+(terminal?'terminal ':'')+(selected===node.code?'selected ':'')+(linkFrom===node.code?'link-origin':'')}>
              <div className="ld-canvas-node-handle" title="Drag this card" onPointerDown={e=>{
                if(e.button!==0)return
                e.preventDefault();setDragging({pointerId:e.pointerId,code:node.code,x:e.clientX,y:e.clientY,left:p.x,top:p.y})
              }}><span>⋮⋮</span> {node.stage.replaceAll('_',' ').toUpperCase()}</div>
              <button className="ld-canvas-node-content" type="button" onClick={()=>useNode(node.code)} aria-pressed={selected===node.code}
                onDragOver={e=>{if(e.dataTransfer.types.includes('application/x-letterdesk-node'))e.preventDefault()}}
                onDrop={e=>{e.preventDefault();const from=e.dataTransfer.getData('application/x-letterdesk-node');if(from){onConnect(from,node.code,branchOutcome);setLinkFrom('')}}}>
                <strong>{node.code}</strong><small>{terminal?'End conversation / do not send':(node.body||'Click to edit this message').slice(0,83)}</small>
              </button>
              {!terminal&&<div className="ld-canvas-node-actions">
                <button title={'Add response after '+node.code} aria-label={'Add response after '+node.code}
                  type="button" onClick={()=>{onSelect(node.code);setBranchFrom(branchFrom===node.code?'':node.code)}}>＋</button>
                <button title={'Drag this connector to another message'} aria-label={'Drag connector from '+node.code+' to another message'}
                  type="button" draggable="true" onDragStart={e=>{
                    e.dataTransfer.setData('application/x-letterdesk-node',node.code)
                    e.dataTransfer.effectAllowed='link';setLinkFrom(node.code);setBranchFrom('')
                  }} onDragEnd={()=>setLinkFrom('')}
                  onClick={()=>{onSelect(node.code);setLinkFrom(node.code);setBranchFrom('')}}>◉</button>
              </div>}
              {branchFrom===node.code&&<div className="ld-canvas-quickadd">
                <strong>Add response</strong>
                <select aria-label="New response type" value={branchOutcome} onChange={e=>setBranchOutcome(e.target.value)}>
                  {['yes','no','positive','question','objection','not_now','no_reply','uncertain','opt_out'].map(x=><option key={x} value={x}>{TAG[x]||'OPT OUT'}</option>)}
                </select>
                <button type="button" onClick={()=>{
                  onAdd(node.code,branchOutcome);setBranchFrom('');setNotice('New branch added for review')
                }}>Add message</button>
                <button type="button" onClick={()=>setBranchFrom('')}>Cancel</button>
              </div>}
            </div>
          })}
        </div>
      </div>
    </div>
    <div className="ld-canvas-footnote">Response conditions and sending caps remain subject to validation. A visual connection never sends email.</div>
  </section>
}
