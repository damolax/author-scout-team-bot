import React, { useEffect, useMemo, useRef, useState } from 'react'
import { SERVICE_MODES } from './service-modes.js'
import './service-dashboard.css'
import ScoutingStudio from './ScoutingStudio.jsx'
import ImportStudio from './ImportStudio.jsx'
import FlowStudio from './FlowStudio.jsx'
import CampaignStudio from './CampaignStudio.jsx'

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
  const common = ['Name','Email','Website','Country','City','Source URL','Evidence Notes','Subject','First Message','First Message English','Do Not Contact']
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
    if (!active || !keyValue) return undefined
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
  }, [active, keyValue, request, serviceKey, search, offset, reload])

  function chooseService(key) {
    if (serviceKey === key) return
    setServiceKey(key)
    setRows([])
    setSearch('')
    setOffset(0)
    setError('')
  }

  return (
    <section className="ld2">
      <div className="ld2-hero">
        <div>
          <p className="ld2-eyebrow">LETTER DESK / INTELLIGENT SCOUTING</p>
          <h1>One workspace.<br/><em>Six ways to discover opportunity.</em></h1>
          <p>Switch your service without losing the context, evidence or conversations behind each prospect.</p>
        </div>
        <div className="ld2-hero-actions">
          <span className="ld2-live"><i/> Connected to your workspace</span>
          <button type="button" className="ld2-button ld2-button-outline" onClick={() => setReload(n => n + 1)} disabled={loading || loadingSummary}>
            ↻ Refresh data
          </button>
        </div>
      </div>

      <div className="ld2-mode-grid" role="group" aria-label="Choose the scouting service">
        {SERVICE_MODES.map(mode => (
          <button type="button" key={mode.key} className={'ld2-mode ' + (mode.key === serviceKey ? 'is-active' : '')}
            aria-pressed={mode.key === serviceKey} onClick={() => chooseService(mode.key)}>
            <span className="ld2-mode-icon" aria-hidden="true">{SERVICE_ICONS[mode.key]}</span>
            <strong>{mode.label.replace(' Scouting', '')}</strong>
            <span>{mode.noun} research</span>
          </button>
        ))}
      </div>

      <div className="ld2-current-header">
        <div>
          <p className="ld2-eyebrow">ACTIVE SERVICE</p>
          <h2>{HEADLINES[serviceKey]}</h2>
          <p>{SERVICE_DESCRIPTIONS[serviceKey]}</p>
        </div>
        <button type="button" className="ld2-button" onClick={() => exportTemplate(current)}>
          ↓ Download {current.noun} import template
        </button>
      </div>

      <ScoutingStudio key={serviceKey} serviceKey={serviceKey} keyValue={keyValue} request={request} active={active} />
      <ImportStudio key={'import-'+serviceKey} serviceKey={serviceKey} keyValue={keyValue} active={active} onImported={()=>setReload(n=>n+1)} />
      <FlowStudio key={'flow-'+serviceKey} serviceKey={serviceKey} keyValue={keyValue} request={request} active={active} />
      <CampaignStudio key={'campaign-'+serviceKey} serviceKey={serviceKey} keyValue={keyValue} request={request} active={active} />

      <div className="ld2-metrics" aria-label="Service performance">
        {[
          ['Research leads',metrics?.prospect_count],
          ['Drafts to review',metrics?.draft_count],
          ['Sent messages',metrics?.sent_count],
          ['Awaiting replies',metrics?.awaiting_reply_count],
        ].map(([label,value]) => <div className="ld2-metric" key={label}>
          <span>{label}</span>
          <strong>{loadingSummary ? '…' : fmt(value)}</strong>
        </div>)}
      </div>

      <div className="ld2-leads-panel">
        <div className="ld2-list-header">
          <div>
            <h3>Prospect research</h3>
            <p>{fmt(total)} opportunities in this service</p>
          </div>
          <label className="ld2-search">
            <span aria-hidden="true">⌕</span>
            <input type="search" aria-label="Search this service's leads" placeholder="Search name, website or email"
              value={search} onChange={e => { setSearch(e.target.value); setOffset(0) }}/>
          </label>
        </div>
        {error && <p className="ld2-error" role="alert">{error} Make sure the Neon service endpoints are enabled in staging.</p>}
        <div className="ld2-table-wrap">
          <table className="ld2-table">
            <thead><tr><th>Prospect</th><th>Email</th><th>Research status</th><th>Source</th></tr></thead>
            <tbody>
              {loading
                ? <tr><td colSpan={4} className="ld2-empty">Loading verified workspace data…</td></tr>
                : rows.length === 0
                ? <tr><td colSpan={4} className="ld2-empty">No prospects found for this service yet. Open the import panel or Scouting Studio to add prospects.</td></tr>
                : rows.map(lead => <tr key={lead.opportunity_id}>
                  <td><strong>{lead.name}</strong><small>{[lead.city, lead.country].filter(Boolean).join(' · ') || current.noun}</small></td>
                  <td>{lead.email || <span className="ld2-muted">Not found</span>}</td>
                  <td><span className={'ld2-status ' + (lead.status === 'research_complete' ? 'is-ready' : '')}>{String(lead.status || 'new').replaceAll('_',' ')}</span></td>
                  <td>{safeLink(lead.source_url || lead.website)
                    ? <a href={safeLink(lead.source_url || lead.website)} target="_blank" rel="noopener noreferrer">View evidence ↗</a>
                    : <span className="ld2-muted">No source</span>}</td>
                </tr>)}
            </tbody>
          </table>
        </div>
        <div className="ld2-pagination">
          <span>{total ? fmt(offset+1) + '–' + fmt(Math.min(total,offset+rows.length)) + ' of ' + fmt(total) : 'No records'}</span>
          <div>
            <button type="button" disabled={loading || offset === 0} onClick={() => setOffset(n=>Math.max(0,n-25))}>← Previous</button>
            <button type="button" disabled={loading || offset + 25 >= total} onClick={() => setOffset(n=>n+25)}>Next →</button>
          </div>
        </div>
      </div>
    </section>
  )
}
