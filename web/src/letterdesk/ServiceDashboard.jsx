import React, { useEffect, useMemo, useRef, useState } from 'react'
import { SERVICE_MODES } from './service-modes.js'
import './service-dashboard.css'
import './service-workspace-layout.css'
import ScoutingStudio from './ScoutingStudio.jsx'
import ImportStudio from './ImportStudio.jsx'
import FlowStudio from './FlowStudio.jsx'
import CampaignStudio from './CampaignStudio.jsx'
import ReplyStudio from './ReplyStudio.jsx'
import ProspectProfile from './ProspectProfile.jsx'

const SERVICE_ICONS = Object.freeze({
  author: '✦', automation: '⟲', 'website-design': '▣',
  'digital-planner': '▦', shopify: '◈', 'google-maps': '⌖',
})
const HEADLINES = Object.freeze({
  author: 'Discover writers and the stories behind their work',
  automation: 'Find businesses whose workflows need a better system',
  'website-design': 'Identify real website opportunities',
  'digital-planner': 'Discover creators, shops and planner niches',
  shopify: 'Find ecommerce opportunities backed by evidence',
  'google-maps': 'Discover local businesses worth researching',
})
const SERVICE_DESCRIPTIONS = Object.freeze({
  author: 'Books, releases, interviews, public author profiles and verified professional contact paths.',
  automation: 'Operational friction, repetitive tasks, current tools and evidence of integration needs.',
  'website-design': 'Public website observations, customer journeys, accessibility and conversion opportunities.',
  'digital-planner': 'Digital creator stores, planner categories, product positioning and research-backed opportunities.',
  shopify: 'Shopify storefronts, product journeys, public technical observations and ecommerce gaps.',
  'google-maps': 'Local business profiles, location, category, website presence and professional contact sources.',
})
const fmt = value => (Number(value) || 0).toLocaleString()
function csvValue(value) { return '"' + String(value || '').replaceAll('"', '""') + '"' }
function safeLink(raw) {
  try { const u = new URL(raw); return ['https:','http:'].includes(u.protocol) ? u.href : null } catch { return null }
}
function exportTemplate(mode) {
  const common = ['Name','Email','Website','Country','Region','City','Preferred Language','Writing Language','Message Language','Research Date','Source URL','Evidence Notes','Subject','First Message','First Message English','Do Not Contact']
  const specific = Object.values(mode.fields).map(aliases => aliases[0])
  const graph = ['Message 01','Message0101Yes','Message0101No','Message0101Question','Message0201Yes','Message0201No']
  const headers = [...new Set([...common, ...specific, ...graph])]
  const csv = '\uFEFF' + headers.map(csvValue).join(',') + '\r\n'
  const href = URL.createObjectURL(new Blob([csv], {type:'text/csv;charset=utf-8;'}))
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = 'LetterDesk_' + mode.key + '_import_template.csv'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}

export default function ServiceDashboard({ active, keyValue, request }) {
  const [serviceKey, setServiceKey] = useState('author')
  const [screen, setScreen] = useState('overview')
  const [railOpen, setRailOpen] = useState(true)
  const [mobileRail, setMobileRail] = useState(false)
  const [profileId, setProfileId] = useState('')
  const [visited, setVisited] = useState(['overview'])
  const [services, setServices] = useState([])
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [loadingSummary, setLoadingSummary] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const requestSerial = useRef(0)
  const current = useMemo(() => SERVICE_MODES.find(s => s.key === serviceKey) || SERVICE_MODES[0], [serviceKey])
  const metrics = services.find(s => s.service_key === serviceKey)

  useEffect(() => {
    if (!active || !keyValue) return undefined
    let cancelled = false
    setLoadingSummary(true)
    request('/api/v2/letterdesk/services', keyValue).then(result => {
      if (!cancelled) { setServices(result.services || []); setError('') }
    }).catch(e => { if (!cancelled) setError(e.message || 'Unable to load your workspaces.') })
      .finally(() => { if (!cancelled) setLoadingSummary(false) })
    return () => { cancelled = true }
  }, [active, keyValue, request, reload])

  useEffect(() => {
    if (!active || !keyValue || !['prospects','overview'].includes(screen)) return undefined
    const serial = ++requestSerial.current
    let cancelled = false
    const timer = setTimeout(() => {
      setLoading(true)
      const query = new URLSearchParams({limit:'25',offset:String(offset),search:search.trim()})
      request('/api/v2/letterdesk/services/' + serviceKey + '/leads?' + query.toString(), keyValue)
        .then(result => {
          if (cancelled || serial !== requestSerial.current) return
          setRows(result.leads || [])
          setTotal(Number(result.total || 0))
          setError('')
        }).catch(e => {
          if (cancelled || serial !== requestSerial.current) return
          setError(e.message || 'Could not load your prospects.')
        }).finally(() => {
          if (!cancelled && serial === requestSerial.current) setLoading(false)
        })
    }, 160)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [active, keyValue, request, serviceKey, search, offset, reload, screen])

  function chooseService(key) {
    if (serviceKey === key) return
    setServiceKey(key)
    setProfileId('')
    setScreen('overview')
    setRows([])
    setSearch('')
    setOffset(0)
    setError('')
  }

  const nav = [
    {key:'overview',name:'Overview',icon:'▦',desc:'Service snapshot and priorities'},
    {key:'prospects',name:'Prospects',icon:'♙',desc:'Contacts, evidence and histories'},
    {key:'research',name:'Scouting',icon:'⌕',desc:'Evidence-led prospect discovery'},
    {key:'imports',name:'Imports',icon:'⇧',desc:'Bulk uploads and conflict review'},
    {key:'flows',name:'Flow Builder',icon:'⑂',desc:'Visual conversation paths'},
    {key:'campaigns',name:'Gmail & Campaigns',icon:'✉',desc:'Senders and reviewed outreach'},
    {key:'inbox',name:'Reply Inbox',icon:'▤',desc:'Reply decisions and next actions'},
    {key:'analytics',name:'Analytics',icon:'▥',desc:'Delivery and review metrics'},
  ]
  const chosen = nav.find(n=>n.key===screen) || nav[0]
  function navigate(next) {
    setScreen(next);setVisited(v=>v.includes(next)?v:[...v,next]);setMobileRail(false);setProfileId('')
  }
  const metricsCards=[
    ['Research leads',metrics?.prospect_count],['Drafts to review',metrics?.draft_count],
    ['Sent messages',metrics?.sent_count],['Awaiting replies',metrics?.awaiting_reply_count],
  ]
  const leadsTable = <div className="ld2-leads-panel">
    <div className="ld2-list-header">
      <div><h3>Prospects and research</h3><p>{fmt(total)} opportunities in this service</p></div>
      <label className="ld2-search"><span aria-hidden="true">⌕</span>
        <input type="search" aria-label="Search this service's leads" placeholder="Search name, website or email"
          value={search} onChange={e=>{setSearch(e.target.value);setOffset(0)}}/>
      </label>
    </div>
    {error&&<p className="ld2-error" role="alert">{error}</p>}
    <div className="ld2-table-wrap"><table className="ld2-table">
      <thead><tr><th>Prospect</th><th>Email</th><th>Research status</th><th>Evidence</th><th>Profile</th></tr></thead>
      <tbody>{loading?<tr><td colSpan={5} className="ld2-empty">Loading workspace data…</td></tr>:
        rows.length===0?<tr><td colSpan={5} className="ld2-empty">No matching prospects. Try Imports or Scouting to add contacts.</td></tr>:
        rows.map(lead=><tr key={lead.opportunity_id}>
          <td><strong>{lead.name}</strong><small>{[lead.city,lead.country].filter(Boolean).join(' · ')||current.noun}</small></td>
          <td>{lead.email||<span className="ld2-muted">Not verified</span>}</td>
          <td><span className={'ld2-status '+(lead.status==='research_complete'?'is-ready':'')}>{String(lead.status||'new').replaceAll('_',' ')}</span></td>
          <td>{safeLink(lead.source_url||lead.website)?<a href={safeLink(lead.source_url||lead.website)} target="_blank" rel="noopener noreferrer">View source ↗</a>:<span className="ld2-muted">No source</span>}</td>
          <td><button type="button" className="ld2-profile-action" onClick={()=>setProfileId(lead.opportunity_id)}>Open profile →</button></td>
        </tr>)}
      </tbody>
    </table></div>
    <div className="ld2-pagination"><span>{total?fmt(offset+1)+'–'+fmt(Math.min(total,offset+rows.length))+' of '+fmt(total):'No records'}</span>
      <div><button disabled={loading||offset===0} onClick={()=>setOffset(v=>Math.max(0,v-25))}>← Previous</button>
        <button disabled={loading||offset+25>=total} onClick={()=>setOffset(v=>v+25)}>Next →</button></div>
    </div>
  </div>
  return <section className={'ld2 ld2-shell '+(!railOpen?'ld2-collapsed ':'')+(mobileRail?'ld2-mobile-rail':'')}>
    <button type="button" className="ld2-mobile-menu" aria-label="Toggle workspace menu" aria-expanded={mobileRail} onClick={()=>setMobileRail(v=>!v)}>☰ <span>{current.label.replace(' Scouting','')} / {chosen.name}</span></button>
    {mobileRail&&<button className="ld2-rail-backdrop" type="button" aria-label="Close menu" onClick={()=>setMobileRail(false)}/>}
    <aside className="ld2-rail" aria-label="Service and tool navigation">
      <div className="ld2-rail-brand"><span className="ld2-brand-mark">LD</span>{railOpen&&<strong>Letter Desk</strong>}
        <button className="ld2-rail-collapse" type="button" aria-label={railOpen?'Collapse sidebar':'Expand sidebar'} onClick={()=>setRailOpen(v=>!v)}>{railOpen?'‹':'›'}</button>
      </div>
      <label className="ld2-service-select">{railOpen&&<span>ACTIVE SERVICE</span>}
        <select aria-label="Select service" value={serviceKey} onChange={e=>chooseService(e.target.value)}>
          {SERVICE_MODES.map(m=><option key={m.key} value={m.key}>{m.label.replace(' Scouting','')}</option>)}
        </select>
      </label>
      <nav className="ld2-rail-links">{nav.map(item=><button type="button" key={item.key}
        className={'ld2-rail-item '+(screen===item.key?'active':'')} title={item.name}
        aria-current={screen===item.key?'page':undefined} onClick={()=>navigate(item.key)}>
        <span className="ld2-rail-icon" aria-hidden="true">{item.icon}</span>
        {railOpen&&<span>{item.name}</span>}
      </button>)}</nav>
      <div className="ld2-rail-bottom">{railOpen?'Six services · one organized workspace':'✦'}</div>
    </aside>
    <main className="ld2-content">
      <header className="ld2-page-header">
        <div><p className="ld2-eyebrow">{current.label.replace(' Scouting','').toUpperCase()} / {chosen.name.toUpperCase()}</p>
          <h1>{screen==='overview'?HEADLINES[serviceKey]:chosen.name}</h1><p>{screen==='overview'?SERVICE_DESCRIPTIONS[serviceKey]:chosen.desc}</p></div>
        <div className="ld2-page-actions"><button type="button" onClick={()=>setReload(v=>v+1)} disabled={loadingSummary}>↻ Refresh</button>
          {screen==='imports'&&<button type="button" className="ld2-button" onClick={()=>exportTemplate(current)}>↓ Import template</button>}</div>
      </header>
      {screen==='overview'&&<>
        <div className="ld2-metrics" aria-label="Service snapshot">{metricsCards.map(([label,value])=><div className="ld2-metric" key={label}><span>{label}</span><strong>{loadingSummary?'…':fmt(value)}</strong></div>)}</div>
        <div className="ld2-home-actions">
          <button onClick={()=>navigate('inbox')}><b>Review replies →</b><small>Respond to conversations that need attention</small></button>
          <button onClick={()=>navigate('imports')}><b>Import prospects →</b><small>Check new contacts, evidence and messages</small></button>
          <button onClick={()=>navigate('flows')}><b>Design a flow →</b><small>Build and simulate response paths</small></button>
        </div>
        {leadsTable}
      </>}
      {screen==='prospects'&&leadsTable}
      {visited.includes('research')&&<div hidden={screen!=='research'} className="ld2-screen-panel"><ScoutingStudio key={serviceKey} serviceKey={serviceKey} keyValue={keyValue} request={request} active={active&&screen==='research'} standalone/></div>}
      {visited.includes('imports')&&<div hidden={screen!=='imports'} className="ld2-screen-panel"><ImportStudio key={'import-'+serviceKey} serviceKey={serviceKey} keyValue={keyValue} active={active&&screen==='imports'} onImported={()=>setReload(n=>n+1)} standalone/></div>}
      {visited.includes('flows')&&<div hidden={screen!=='flows'} className="ld2-screen-panel"><FlowStudio key={'flow-'+serviceKey} serviceKey={serviceKey} keyValue={keyValue} request={request} active={active&&screen==='flows'} standalone/></div>}
      {visited.includes('campaigns')&&<div hidden={screen!=='campaigns'} className="ld2-screen-panel"><CampaignStudio key={'campaign-'+serviceKey} serviceKey={serviceKey} keyValue={keyValue} request={request} active={active&&screen==='campaigns'} standalone/></div>}
      {visited.includes('inbox')&&<div hidden={screen!=='inbox'} className="ld2-screen-panel"><ReplyStudio key={'reply-'+serviceKey} serviceKey={serviceKey} keyValue={keyValue} request={request} active={active&&screen==='inbox'} standalone/></div>}
      {screen==='analytics'&&<><div className="ld2-metrics">{metricsCards.map(([label,value])=><div className="ld2-metric" key={label}><span>{label}</span><strong>{fmt(value)}</strong></div>)}</div><p className="ld2-analytics-note">These figures come from your service's actual recorded opportunities and messages. Sending remains subject to account verification and campaign controls.</p></>}
      {profileId&&<ProspectProfile serviceKey={serviceKey} opportunityId={profileId} keyValue={keyValue} request={request} onClose={()=>setProfileId('')}/>}
    </main>
  </section>
}
