import React, { useCallback, useEffect, useState } from 'react'
import { authClient, sessionTokenFrom } from './auth.js'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'https://author-scout-team-bot.onrender.com').replace(/\/$/, '')

async function request(path, key, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (key) headers['X-Author-Scout-Key'] = key
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 25000)
  try {
    const res = await fetch(API_BASE + path, { ...options, headers, signal: controller.signal })
    let body = {}
    try { body = await res.json() } catch { body = {} }
    if (!res.ok) throw new Error(body.detail || body.error || 'Request failed')
    return body
  } catch (e) {
    if (e?.name === 'AbortError') {
      throw new Error('Author Scout took too long to respond. Please try again.')
    }
    throw e
  } finally {
    clearTimeout(timeout)
  }
}

async function waitForBackend(maxWaitMs = 75000) {
  const started = Date.now()
  let lastError = null
  while (Date.now() - started < maxWaitMs) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 12000)
    try {
      const res = await fetch(API_BASE + '/api/v1/health?ts=' + Date.now(), {
        method: 'GET',
        cache: 'no-store',
        signal: controller.signal,
      })
      clearTimeout(timer)
      if (res.ok) {
        const body = await res.json().catch(() => ({}))
        if (body?.ok) return true
      }
    } catch (e) {
      lastError = e
      clearTimeout(timer)
    }
    await new Promise(resolve => setTimeout(resolve, 1800))
  }
  throw lastError || new Error('Author Scout could not wake the secure login service. Please try again.')
}

function fmt(value) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString()
}
function formatDuration(seconds) {
  const s = Math.max(0, Number(seconds) || 0)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d) return d + 'd ' + h + 'h ' + m + 'm'
  if (h) return h + 'h ' + m + 'm'
  return m + 'm'
}


function short(text, n = 120) {
  const s = String(text || '')
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

function usePolling(callback, delay, active = true) {
  useEffect(() => {
    if (!active) return
    let cancelled = false
    let timer
    const run = async () => {
      try { await callback() } finally {
        if (!cancelled) timer = setTimeout(run, delay)
      }
    }
    run()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [callback, delay, active])
}

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  componentDidCatch(error, info) {
    console.error('AUTHOR_SCOUT_UI_ERROR', error, info)
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="login-shell">
        <div className="login-card">
          <div className="brand brand-login">
            <div className="brand-mark">AS</div>
            <div><strong>Author Scout</strong><span>Workspace recovery</span></div>
          </div>
          <h1>We hit a display problem.</h1>
          <p className="login-copy">Your login may already be valid. Refresh the page once. If this returns, send us the message below.</p>
          <div className="alert alert-error">{String(this.state.error?.message || this.state.error)}</div>
          <button className="button button-primary button-block" onClick={() => window.location.reload()}>Reload Author Scout</button>
        </div>
      </div>
    )
  }
}

function Status({ value }) {
  const cls = String(value || '').toLowerCase().replace(/[^a-z_]/g, '')
  return <span className={'status status-' + cls}>{value || 'unknown'}</span>
}

function Metric({ label, value, sub }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value ?? 0}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  )
}

function Empty({ title, body }) {
  return (
    <div className="empty">
      <div className="empty-mark">◎</div>
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  )
}

function Login({ onLegacyLogin, onGoogle, onEmail, busy, error, status }) {
  const [mode, setMode] = useState('signin')
  const [showLegacy, setShowLegacy] = useState(false)
  const [legacyKey, setLegacyKey] = useState('')
  const [form, setForm] = useState({ name:'', email:'', password:'' })
  const setField = (k,v) => setForm(prev => ({...prev,[k]:v}))
  const signup = mode === 'signup'

  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="brand brand-login">
          <div className="brand-mark">AS</div>
          <div><strong>Author Scout</strong><span>Research Intelligence</span></div>
        </div>
        <h1>{signup ? 'Create your account' : 'Welcome back'}</h1>
        <p className="login-copy">
          {signup
            ? 'Create a private Author Scout workspace with your email and password. Email verification is not required to start using the app.'
            : 'Sign in to your Author Scout workspace.'}
        </p>

        {error && <div className="alert alert-error">{error}</div>}

        <button className="button button-primary button-block google-login" onClick={onGoogle} disabled={busy}>
          <span className="google-g">G</span>{busy && status ? status : 'Continue with Google'}
        </button>

        <div className="auth-divider"><span>or</span></div>

        <form className="email-auth-form" onSubmit={(e) => { e.preventDefault(); onEmail(mode, form) }}>
          {signup && <div className="field">
            <label>Name</label>
            <input value={form.name} onChange={e => setField('name',e.target.value)} placeholder="Your name" autoComplete="name" required />
          </div>}
          <div className="field">
            <label>Email</label>
            <input type="email" value={form.email} onChange={e => setField('email',e.target.value)} placeholder="you@example.com" autoComplete="email" required />
          </div>
          <div className="field">
            <label>Password</label>
            <input type="password" value={form.password} onChange={e => setField('password',e.target.value)}
              placeholder={signup ? 'Create a secure password' : 'Your password'}
              autoComplete={signup ? 'new-password' : 'current-password'} minLength="8" required />
          </div>
          <button className="button button-auth-email button-block" disabled={busy}>
            {busy ? (status || 'Please wait…') : (signup ? 'Create account' : 'Sign in')}
          </button>
        </form>

        <button className="auth-switch" onClick={() => setMode(signup ? 'signin' : 'signup')} disabled={busy}>
          {signup ? 'Already have an account? Sign in' : 'New to Author Scout? Create account'}
        </button>

        <p className="login-note">
          {signup ? 'Your account works immediately whether the email is verified or not.' : 'You stay signed in on this device until you sign out or the session expires.'}
        </p>

        <button className="legacy-toggle" onClick={() => setShowLegacy(v => !v)}>
          {showLegacy ? 'Hide Telegram access key' : 'Older Telegram account? Use /webkey'}
        </button>
        {showLegacy && <form className="legacy-login" onSubmit={(e) => { e.preventDefault(); onLegacyLogin(legacyKey.trim()) }}>
          <label>Telegram web access key</label>
          <textarea rows="3" value={legacyKey} onChange={(e) => setLegacyKey(e.target.value)} placeholder="Paste your /webkey" />
          <button className="button button-quiet button-block" disabled={!legacyKey.trim() || busy}>Use Telegram key</button>
        </form>}
      </div>
    </div>
  )
}

function Dashboard({ keyValue, session, active }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [telegram, setTelegram] = useState(null)
  const [linking, setLinking] = useState(false)
  const load = useCallback(async () => {
    try { setData(await request('/api/v1/dashboard', keyValue)); setError('') }
    catch (e) { setError(e.message) }
  }, [keyValue])
  usePolling(load, 8000, active)

  const createTelegramLink = async () => {
    setLinking(true); setError('')
    try {
      const d = await request('/api/v1/telegram/link-code', keyValue, { method:'POST', body:'{}' })
      setTelegram(d)
    } catch(e) { setError(e.message) }
    finally { setLinking(false) }
  }

  const counts = data?.counts || {}
  const name = session?.account?.display_name || session?.user?.first_name || session?.user?.username || 'there'
  const telegramLinked = Boolean(session?.account?.telegram_linked || telegram?.linked)
  return (
    <section>
      <div className="page-head">
        <div><div className="eyebrow">Overview</div><h1>Hi, {name}</h1></div>
        <button className="button button-quiet" onClick={load}>Refresh</button>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="metric-grid">
        <Metric label="Authors" value={counts.authors} />
        <Metric label="Active Scouts" value={counts.jobs_queued} />
        <Metric label="Ready Messages" value={counts.messages_ready} />
        <Metric label="Sent" value={counts.messages_sent} />
      </div>

      <div className="panel telegram-link-card">
        <div>
          <div className="eyebrow">Telegram companion</div>
          <h2>{telegramLinked ? 'Telegram is connected' : 'Use Author Scout from Telegram too'}</h2>
          <p>{telegramLinked
            ? 'Your web app and Telegram companion use the same workspace.'
            : 'Telegram is optional. Link it once to receive Scout updates and use quick actions from @Authorscoutbot.'}</p>
        </div>
        {telegramLinked
          ? <span className="status status-completed">Connected</span>
          : telegram?.code
            ? <div className="telegram-link-code">
                <span>Send this to @Authorscoutbot</span>
                <code>{telegram.command}</code>
                <a className="button button-quiet" href="https://t.me/Authorscoutbot" target="_blank" rel="noreferrer">Open Telegram ↗</a>
              </div>
            : <button className="button button-quiet" onClick={createTelegramLink} disabled={linking}>
                {linking ? 'Creating code…' : 'Connect Telegram'}
              </button>}
      </div>
    </section>
  )
}

function Research({ keyValue, active }) {
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState({ name:'', country:'', genre:'', gender:'any', language:'', year:'' })
  const [showMoreFilters, setShowMoreFilters] = useState(false)
  const [duration, setDuration] = useState(10)
  const [jobs, setJobs] = useState([])
  const [selected, setSelected] = useState(null)
  const [creating, setCreating] = useState(false)
  const [stoppingId, setStoppingId] = useState(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const loadJobs = useCallback(async () => {
    try {
      const d = await request('/api/v1/research/jobs?limit=40', keyValue)
      setJobs(d.jobs || [])
      setError('')
      if (selected && d.jobs?.some(j => j.id === selected.job?.id)) {
        const detail = await request('/api/v1/research/jobs/' + selected.job.id, keyValue)
        setSelected(detail)
      }
    } catch (e) { setError(e.message) }
  }, [keyValue, selected?.job?.id])

  usePolling(loadJobs, 4000, active)

  const hasScoutCriteria = query.trim() || Object.entries(filters).some(([k,v]) => k !== 'gender' && String(v || '').trim()) || filters.gender !== 'any'
  const setFilter = (key, value) => setFilters(prev => ({ ...prev, [key]: value }))

  const create = async (e) => {
    e.preventDefault()
    if (!hasScoutCriteria) return
    setCreating(true); setError(''); setNotice('')
    try {
      const d = await request('/api/v1/research/jobs', keyValue, {
        method: 'POST',
        body: JSON.stringify({ query: query.trim(), filters, duration_minutes: Number(duration) || 10 })
      })
      setQuery('')
      await loadJobs()
      const detail = await request('/api/v1/research/jobs/' + d.job_id, keyValue)
      setSelected(detail)
    } catch (e) { setError(e.message) }
    finally { setCreating(false) }
  }

  const stopJob = async (id) => {
    if (!window.confirm('Stop this Scout? Authors already found will stay saved in My Authors.')) return
    setStoppingId(id); setError(''); setNotice('')
    try {
      const d = await request('/api/v1/research/jobs/' + id + '/stop', keyValue, { method: 'POST', body: '{}' })
      setNotice('Stop requested. Authors already found will remain saved.')
      setSelected(prev => prev?.job?.id === id ? { ...prev, job: d.job } : prev)
      await loadJobs()
    } catch (e) { setError(e.message) }
    finally { setStoppingId(null) }
  }

  const openJob = async (id) => {
    try { setSelected(await request('/api/v1/research/jobs/' + id, keyValue)) }
    catch (e) { setError(e.message) }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <div className="eyebrow">Discovery</div>
          <h1>Scout</h1>
          <p>Find authors with strict filters. Long Scouts keep running in the background.</p>
        </div>
      </div>

      <div className="panel research-compose">
        <form onSubmit={create}>
          <div className="filter-head">
            <div>
              <label>Scout filters</label>
              <p>Country is strict. Other filters narrow discovery.</p>
            </div>
            <span className="strict-badge">Strict country</span>
          </div>

          <div className="scout-filter-grid">
            <div className="field">
              <label>Country</label>
              <input list="scout-countries" value={filters.country} onChange={e => setFilter('country', e.target.value)} placeholder="Spain" />
              <datalist id="scout-countries">
                {['United States','United Kingdom','Canada','Australia','France','Germany','Austria','United Arab Emirates','New Zealand','Spain','Iceland','Saudi Arabia','Portugal','Italy','Netherlands','Belgium','Switzerland','Sweden','Norway','Denmark','Finland','Ireland','India','Japan','South Korea','Singapore','South Africa','Nigeria','Ghana','Kenya','Mexico','Brazil','Argentina','Chile','Colombia'].map(x => <option key={x} value={x} />)}
              </datalist>
            </div>
            <div className="field">
              <label>Genre</label>
              <input value={filters.genre} onChange={e => setFilter('genre', e.target.value)} placeholder="Historical fiction" />
            </div>
            <div className="field">
              <label>Gender</label>
              <select value={filters.gender} onChange={e => setFilter('gender', e.target.value)}>
                <option value="any">Any</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
              </select>
            </div>
          </div>

          <button type="button" className="filter-toggle" onClick={() => setShowMoreFilters(v => !v)}>
            {showMoreFilters ? 'Hide extra filters' : 'More filters'} <span>{showMoreFilters ? '−' : '+'}</span>
          </button>

          {showMoreFilters && <div className="scout-filter-grid extra">
            <div className="field">
              <label>Name contains</label>
              <input value={filters.name} onChange={e => setFilter('name', e.target.value)} placeholder="Optional author name" />
            </div>
            <div className="field">
              <label>Language</label>
              <input value={filters.language} onChange={e => setFilter('language', e.target.value)} placeholder="Spanish" />
            </div>
            <div className="field">
              <label>Activity year</label>
              <input value={filters.year} onChange={e => setFilter('year', e.target.value)} placeholder="2026" />
            </div>
          </div>}

          <div className="field scout-instructions">
            <label>Additional instructions <span>optional</span></label>
            <textarea
              rows="3"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Example: emerging or mid-list, active recently, avoid celebrity authors, low outreach saturation"
            />
          </div>
          <div className="compose-row">
            <div className="field-small">
              <label>Scout duration</label>
              <select value={duration} onChange={e => setDuration(Number(e.target.value))}>
                <option value="1">1 minute</option>
                <option value="3">3 minutes</option>
                <option value="5">5 minutes</option>
                <option value="10">10 minutes</option>
                <option value="15">15 minutes</option>
                <option value="30">30 minutes</option>
                <option value="60">1 hour</option>
                <option value="360">6 hours</option>
                <option value="720">12 hours</option>
                <option value="1440">1 day</option>
                <option value="4320">3 days</option>
                <option value="10080">7 days</option>
              </select>
            </div>
            <div className="compose-hint">Long Scouts continue in the background.</div>
            <button className="button button-primary" disabled={creating || !hasScoutCriteria}>
              {creating ? 'Starting…' : 'Start Scout'}
            </button>
          </div>
        </form>
      </div>

      {notice && <div className="alert alert-success">{notice}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      <div className="research-layout">
        <div className="panel jobs-panel">
          <div className="panel-head"><div><span className="kicker">Live queue</span><h2>Scout jobs</h2></div><button className="button button-quiet" onClick={loadJobs}>Refresh</button></div>
          {!jobs.length ? <Empty title="No Scout jobs" body="Start one above." /> :
            <div className="job-list">
              {jobs.map(job => (
                <button key={job.id} className={'job-row ' + (selected?.job?.id === job.id ? 'active' : '')} onClick={() => openJob(job.id)}>
                  <div className="job-top"><Status value={job.status} /><span>#{job.id}</span></div>
                  <strong>{short(job.query_text, 92)}</strong>
                  <div className="job-meta">
                    <span>{job.accepted || 0} saved</span>
                    <span>{formatDuration(job.remaining_seconds)} remaining</span>
                    <span>{fmt(job.created_at)}</span>
                  </div>
                  {['queued','starting','running'].includes(job.status) && <div className="progress"><i style={{width: Math.min(100, Math.max(3, Number(job.progress_percent || 0))) + '%'}} /></div>}
                </button>
              ))}
            </div>}
        </div>

        <div className="panel job-detail">
          {!selected ? <Empty title="Select a Scout job" body="Open a job to see progress and results." /> : (
            <>
              <div className="panel-head">
                <div><span className="kicker">Scout job #{selected.job.id}</span><h2>{short(selected.job.query_text, 78)}</h2></div>
                <div className="inline-actions">
                  <Status value={selected.job.status} />
                  {['queued','starting','running'].includes(selected.job.status) &&
                    <button className="button button-danger-quiet" disabled={stoppingId === selected.job.id} onClick={() => stopJob(selected.job.id)}>
                      {stoppingId === selected.job.id ? 'Stopping…' : 'Stop Scout'}
                    </button>}
                </div>
              </div>
              <div className="job-summary-grid">
                <Metric label="Saved" value={selected.job.accepted} />
                <Metric label="Elapsed" value={formatDuration(selected.job.elapsed_seconds)} />
                <Metric label="Remaining" value={formatDuration(selected.job.remaining_seconds)} />
              </div>
              <div className="progress-message">{selected.job.progress_text || 'Waiting for worker…'}</div>
              <div className="progress scout-time-progress"><i style={{width: Math.min(100, Math.max(0, Number(selected.job.progress_percent || 0))) + '%'}} /></div>
              {selected.job.error && <div className="alert alert-error">{selected.job.error}</div>}
              <div className="result-stack">
                {(selected.results || []).map(author => (
                  <div className="result-card" key={author.id}>
                    <div>
                      <strong>{author.name}</strong>
                      <span>{[author.country, author.genre].filter(Boolean).join(' · ') || 'Author'}</span>
                    </div>
                    <div className="result-contact">
                      {author.discovery_source_url && <a href={author.discovery_source_url} target="_blank" rel="noreferrer">{author.discovery_platform || author.discovery_source_type || 'Source'} ↗</a>}
                      {author.email && <a href={'mailto:' + author.email}>{author.email}</a>}
                      {author.website && <a href={author.website} target="_blank" rel="noreferrer">Website ↗</a>}
                    </div>
                  </div>
                ))}
              </div>
              {selected.job.status === 'completed' && !(selected.results || []).length &&
                <Empty title="No new authors claimed" body="The candidates found may already belong to other Author Scout users or the source market may be temporarily exhausted." />}
            </>
          )}
        </div>
      </div>
    </section>
  )
}

function Authors({ keyValue, active }) {
  const [authors, setAuthors] = useState([])
  const [search, setSearch] = useState('')
  const [selectedSeed, setSelectedSeed] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const downloadAuthors = async () => {
    setError(''); setNotice('')
    try {
      const res = await fetch(API_BASE + '/api/v1/authors/export.xlsx', {
        headers: { 'X-Author-Scout-Key': keyValue }
      })
      if (!res.ok) throw new Error('Could not download authors')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'Author_Scout_ChatGPT_Research_Pack.xlsx'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      setNotice('Research pack downloaded.')
    } catch (e) { setError(e.message) }
  }

  const load = useCallback(async () => {
    try {
      const q = search.trim() ? '&search=' + encodeURIComponent(search.trim()) : ''
      const d = await request('/api/v1/authors?limit=250' + q, keyValue)
      setAuthors(d.authors || []); setError('')
    } catch (e) { setError(e.message) }
  }, [keyValue, search])
  useEffect(() => { if (!active) return; const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load, active])

  const researchSeedText = (a) => [
    'AUTHOR RESEARCH SEED',
    'Name: ' + (a.name || ''),
    'Country/Market: ' + (a.country || ''),
    'Genre/Category: ' + (a.genre || ''),
    'Discovery platform: ' + (a.discovery_platform || ''),
    'Source type: ' + (a.discovery_source_type || ''),
    'Source URL: ' + (a.discovery_source_url || ''),
    'Discovery query: ' + (a.discovery_query || ''),
    'Discovery evidence: ' + (a.discovery_evidence || ''),
    'Identity confidence: ' + (a.discovery_confidence || 0) + '/100',
    'Claimed at: ' + (a.claimed_at || '')
  ].join('\n')

  const copySeed = async (a) => {
    try {
      await navigator.clipboard.writeText(researchSeedText(a))
      setNotice('Research seed copied.')
    } catch { setError('Could not copy the research seed.') }
  }

  const openMessage = async (author) => {
    if (!author.message_id) return
    const popup = window.open('about:blank', '_blank')
    if (popup) popup.opener = null
    setBusyId(author.id); setError(''); setNotice('')
    try {
      const d = await request('/api/v1/messages/' + author.message_id + '/compose-link', keyValue)
      if (!popup) throw new Error('Your browser blocked the Gmail tab. Allow pop-ups for Author Scout and try again.')
      popup.location.replace(d.url)
      setNotice('Gmail opened in a new tab. Author Scout will stay here.')
    } catch (e) {
      if (popup) popup.close()
      setError(e.message)
    } finally { setBusyId(null) }
  }

  return (
    <section>
      <div className="page-head">
        <div><div className="eyebrow">Library</div><h1>My Authors</h1></div>
        <div className="page-head-actions">
          <input className="search-box" placeholder="Search authors…" value={search} onChange={e => setSearch(e.target.value)} />
          <button className="button button-primary" onClick={downloadAuthors}>Download for ChatGPT</button>
        </div>
      </div>
      {notice && <div className="alert alert-success">{notice}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      <div className="panel table-panel">
        {!authors.length ? <Empty title="No authors" body="Run a Scout to start your library." /> :
        <div className="table-wrap">
          <table>
            <thead><tr><th>Author</th><th>Country</th><th>Genre</th><th>Source</th><th>Email</th><th>Message</th></tr></thead>
            <tbody>
              {authors.map(a => <tr key={a.id}>
                <td>
                  <strong>{a.name}</strong>
                  <small>#{a.id}{a.discovery_confidence ? ' · ' + a.discovery_confidence + '% confidence' : ''}</small>
                  <button className="seed-link" onClick={() => setSelectedSeed(a)}>Research Seed</button>
                </td>
                <td>{a.country || '—'}</td>
                <td>{a.genre || '—'}</td>
                <td>
                  {a.discovery_source_url
                    ? <a target="_blank" rel="noreferrer" href={a.discovery_source_url}>{a.discovery_platform || 'Source'} ↗</a>
                    : '—'}
                </td>
                <td>{a.email || a.message_recipient || '—'}</td>
                <td className="message-action-cell">
                  {a.message_status === 'ready' && a.message_id
                    ? <button className="button button-good button-compact" disabled={busyId === a.id} onClick={() => openMessage(a)}>
                        {busyId === a.id ? 'Opening…' : 'Message ↗'}
                      </button>
                    : a.message_status === 'sent'
                      ? <Status value={a.message_reply_status === 'replied' ? 'replied' : 'sent'} />
                      : '—'}
                </td>
              </tr>)}
            </tbody>
          </table>
        </div>}
      </div>

      {selectedSeed && <div className="panel research-seed-panel">
        <div className="panel-head">
          <div><span className="kicker">Research Seed</span><h2>{selectedSeed.name}</h2></div>
          <button className="button button-quiet" onClick={() => setSelectedSeed(null)}>Close</button>
        </div>
        <div className="seed-grid">
          <div><span>Country</span><strong>{selectedSeed.country || '—'}</strong></div>
          <div><span>Genre</span><strong>{selectedSeed.genre || '—'}</strong></div>
          <div><span>Platform</span><strong>{selectedSeed.discovery_platform || '—'}</strong></div>
          <div><span>Source type</span><strong>{(selectedSeed.discovery_source_type || 'web search').replaceAll('_',' ')}</strong></div>
          <div><span>Confidence</span><strong>{selectedSeed.discovery_confidence || 0}/100</strong></div>
          <div><span>Claimed</span><strong>{fmt(selectedSeed.claimed_at)}</strong></div>
        </div>
        <div className="seed-field"><span>Query</span><p>{selectedSeed.discovery_query || '—'}</p></div>
        <div className="seed-field"><span>Evidence</span><p>{selectedSeed.discovery_evidence || '—'}</p></div>
        <div className="seed-actions">
          {selectedSeed.discovery_source_url && <a className="button button-quiet" target="_blank" rel="noreferrer" href={selectedSeed.discovery_source_url}>Open source ↗</a>}
          <button className="button button-primary" onClick={() => copySeed(selectedSeed)}>Copy Seed</button>
        </div>
      </div>}
    </section>
  )
}


function Messages({ keyValue, active }) {
  const [items, setItems] = useState([])
  const [status, setStatus] = useState('ready')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null)
  const [gmail, setGmail] = useState({ connected: false, accounts: [] })
  const [busyId, setBusyId] = useState(null)
  const [importing, setImporting] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const q = search.trim() ? '&search=' + encodeURIComponent(search.trim()) : ''
      const d = await request('/api/v1/messages?status=' + encodeURIComponent(status) + '&limit=150' + q, keyValue)
      setItems(d.messages || [])
      setGmail(d.gmail || { connected: false, accounts: [] })
      setError('')
      if (selected) {
        const fresh = (d.messages || []).find(x => x.id === selected.id)
        if (fresh) setSelected(fresh)
      }
    } catch (e) { setError(e.message) }
  }, [keyValue, status, search, selected?.id])

  useEffect(() => {
    if (!active) return
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
  }, [load, active])
  usePolling(load, 9000, active)

  const importResults = async (file) => {
    if (!file) return
    setImporting(true); setError(''); setNotice('')
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(API_BASE + '/api/v1/messages/import', {
        method: 'POST',
        headers: { 'X-Author-Scout-Key': keyValue },
        body: form
      })
      let d = {}
      try { d = await res.json() } catch {}
      if (!res.ok) throw new Error(d.detail || 'Could not import this file')
      setStatus('ready')
      setNotice('Imported ' + (d.ready || 0) + ' ready messages. ' + (d.unmatched || 0) + ' unmatched, ' + (d.skipped || 0) + ' skipped.')
      await load()
    } catch (e) { setError(e.message) }
    finally { setImporting(false) }
  }

  const openGmail = async (id) => {
    const popup = window.open('about:blank', '_blank')
    if (popup) popup.opener = null
    setBusyId(id); setError(''); setNotice('')
    try {
      const d = await request('/api/v1/messages/' + id + '/compose-link', keyValue)
      if (!popup) throw new Error('Your browser blocked the Gmail tab. Allow pop-ups for Author Scout and try again.')
      popup.location.replace(d.url)
      setNotice('Gmail opened in a new tab. Author Scout will stay here.')
    } catch (e) {
      if (popup) popup.close()
      setError(e.message)
    } finally { setBusyId(null) }
  }

  const updateStatus = async (id, next) => {
    setBusyId(id); setError(''); setNotice('')
    try {
      await request('/api/v1/messages/' + id + '/status', keyValue, {
        method: 'POST',
        body: JSON.stringify({ status: next })
      })
      setNotice(next === 'replied' ? 'Marked replied.' : next === 'sent' ? 'Marked sent.' : 'Moved to Ready.')
      setSelected(null)
      await load()
    } catch (e) { setError(e.message) }
    finally { setBusyId(null) }
  }

  const sendNow = async (id) => {
    if (!window.confirm('Send this message now through your connected Gmail account?')) return
    setBusyId(id); setError(''); setNotice('')
    try {
      const d = await request('/api/v1/messages/' + id + '/send', keyValue, {
        method: 'POST',
        body: JSON.stringify({})
      })
      setNotice('Sent through ' + (d.sender_email || 'Gmail') + '.')
      setSelected(null)
      await load()
    } catch (e) { setError(e.message) }
    finally { setBusyId(null) }
  }

  const copyText = async (m) => {
    try {
      await navigator.clipboard.writeText((m.subject ? 'Subject: ' + m.subject + '\n\n' : '') + (m.body || ''))
      setNotice('Message copied.')
    } catch { setError('Copy failed.') }
  }

  return (
    <section>
      <div className="page-head">
        <div><div className="eyebrow">Outreach</div><h1>Messages</h1></div>
        <div className="message-toolbar">
          <label className={'button button-quiet file-button ' + (importing ? 'disabled' : '')}>
            {importing ? 'Importing…' : 'Import ChatGPT Results'}
            <input hidden disabled={importing} type="file" accept=".xlsx,.xlsm,.csv" onChange={e => {
              const file = e.target.files?.[0]
              e.target.value = ''
              importResults(file)
            }} />
          </label>
          <input className="search-box" placeholder="Search…" value={search} onChange={e => setSearch(e.target.value)} />
          <select className="select" value={status} onChange={e => { setStatus(e.target.value); setSelected(null) }}>
            <option value="ready">Ready</option>
            <option value="sent">Sent</option>
            <option value="replied">Replied</option>
            <option value="all">All</option>
          </select>
        </div>
      </div>

      <div className={'alert ' + (gmail.connected ? 'alert-success' : 'alert-error')}>
        {gmail.connected
          ? 'Gmail connected: ' + (gmail.accounts || []).map(a => a.email).join(', ')
          : 'Connect Gmail with /gmail in Telegram to enable direct sending.'}
      </div>
      {notice && <div className="alert alert-success">{notice}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      <div className="panel table-panel">
        {!items.length ? <Empty title={'No ' + status + ' messages'} body={status === 'ready' ? 'Import the finished ChatGPT workbook to add messages.' : 'No messages in this view.'} /> :
        <div className="table-wrap">
          <table>
            <thead><tr><th>Author</th><th>Recipient</th><th>Subject</th><th>Status</th><th>Sent</th><th>Actions</th></tr></thead>
            <tbody>
              {items.map(m => <tr key={m.id}>
                <td><strong>{m.author_name}</strong><small>{[m.author_country, m.author_genre].filter(Boolean).join(' · ') || '#' + m.id}</small></td>
                <td>{m.recipient || '—'}</td>
                <td title={m.subject}>{short(m.subject, 72) || '—'}</td>
                <td><Status value={m.reply_status === 'replied' ? 'replied' : m.status} /></td>
                <td>{fmt(m.sent_at)}</td>
                <td>
                  <div className="inline-actions">
                    <button className="button button-quiet" onClick={() => setSelected(m)}>Review</button>
                    {m.status !== 'sent' && <button className="button button-primary" disabled={busyId === m.id} onClick={() => openGmail(m.id)}>Message ↗</button>}
                    {m.status !== 'sent' && gmail.connected && <button className="button button-good" disabled={busyId === m.id} onClick={() => sendNow(m.id)}>Send now</button>}
                    {m.status !== 'sent' && <button className="button button-quiet" disabled={busyId === m.id} onClick={() => updateStatus(m.id, 'sent')}>Mark Sent</button>}
                    {m.status === 'sent' && m.reply_status !== 'replied' && <button className="button button-good" disabled={busyId === m.id} onClick={() => updateStatus(m.id, 'replied')}>Mark Replied</button>}
                  </div>
                </td>
              </tr>)}
            </tbody>
          </table>
        </div>}
      </div>

      {selected && <div className="panel message-review">
        <div className="panel-head">
          <div><span className="kicker">Message #{selected.id}</span><h2>{selected.author_name}</h2></div>
          <button className="button button-quiet" onClick={() => setSelected(null)}>Close</button>
        </div>
        <div className="message-review-meta">
          <div><span>To</span><strong>{selected.recipient || 'No recipient'}</strong></div>
          <div><span>Subject</span><strong>{selected.subject || 'No subject'}</strong></div>
        </div>
        <div className="message-body">{selected.body || 'No message body.'}</div>
        {selected.body_english && selected.body_english !== selected.body && <>
          <span className="kicker message-english-kicker">English version</span>
          <div className="message-body">{selected.body_english}</div>
        </>}
        <div className="connection-actions">
          <button className="button button-quiet" onClick={() => copyText(selected)}>Copy</button>
          {selected.status !== 'sent' && <button className="button button-primary" disabled={busyId === selected.id} onClick={() => openGmail(selected.id)}>Message ↗</button>}
          {selected.status !== 'sent' && gmail.connected && <button className="button button-good" disabled={busyId === selected.id} onClick={() => sendNow(selected.id)}>Send now</button>}
          {selected.status !== 'sent' && <button className="button button-quiet" disabled={busyId === selected.id} onClick={() => updateStatus(selected.id, 'sent')}>Mark Sent</button>}
          {selected.status === 'sent' && selected.reply_status !== 'replied' && <button className="button button-good" disabled={busyId === selected.id} onClick={() => updateStatus(selected.id, 'replied')}>Mark Replied</button>}
          {selected.status === 'sent' && <button className="button button-danger-quiet" disabled={busyId === selected.id} onClick={() => updateStatus(selected.id, 'ready')}>Move to Ready</button>}
        </div>
      </div>}
    </section>
  )
}

function Connections({ keyValue, active }) {
  const [items, setItems] = useState([])
  const [status, setStatus] = useState('ready')
  const [linkedin, setLinkedin] = useState('')
  const [focus, setFocus] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const d = await request('/api/v1/connections?status=' + encodeURIComponent(status) + '&limit=150', keyValue)
      setItems(d.connections || []); setError('')
    } catch (e) { setError(e.message) }
  }, [keyValue, status])
  usePolling(load, 7000, active)

  const setup = async e => {
    e.preventDefault(); setBusy(true); setError(''); setNotice('')
    try {
      await request('/api/v1/connections/setup', keyValue, {
        method:'POST', body: JSON.stringify({ linkedin_url: linkedin.trim(), focus: focus.trim() })
      })
      setNotice('Connection targeting updated.')
      setLinkedin('')
      await load()
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  const update = async (id, next) => {
    try {
      await request('/api/v1/connections/' + id + '/status', keyValue, {
        method:'POST', body: JSON.stringify({ status: next })
      })
      setItems(v => v.filter(x => x.assignment_id !== id))
    } catch (e) { setError(e.message) }
  }

  return (
    <section>
      <div className="page-head">
        <div><div className="eyebrow">LinkedIn</div><h1>Connections</h1></div>
        <select className="select" value={status} onChange={e => setStatus(e.target.value)}>
          <option value="ready">Ready / saved</option>
          <option value="connected">Connected</option>
          <option value="skipped">Skipped</option>
          <option value="not_relevant">Not relevant</option>
        </select>
      </div>

      <div className="panel connection-setup">
        <div><span className="kicker">Targeting</span><h2>Connection setup</h2></div>
        <form onSubmit={setup}>
          <input placeholder="https://www.linkedin.com/in/your-profile" value={linkedin} onChange={e => setLinkedin(e.target.value)} />
          <input placeholder="Optional focus: publishing founders, authors, literary agents…" value={focus} onChange={e => setFocus(e.target.value)} />
          <button className="button button-primary" disabled={busy || !linkedin.trim()}>{busy ? 'Setting up…' : 'Enable / update'}</button>
        </form>
      </div>
      {notice && <div className="alert alert-success">{notice}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {!items.length ? <div className="panel"><Empty title={status === 'ready' ? 'No ready profiles yet' : 'Nothing in this status'} body={status === 'ready' ? 'Connection profiles will appear here as they are found.' : 'No profiles in this status.'} /></div> :
      <div className="connection-grid">
        {items.map(p => (
          <div className="connection-card" key={p.assignment_id}>
            <div className="connection-score">{p.fit_score}</div>
            <div className="connection-main">
              <div className="connection-title"><div><strong>{p.name}</strong><span>{p.headline || p.company || 'LinkedIn professional'}</span></div><Status value={p.status} /></div>
              <div className="connection-meta"><span>{p.country || 'Location unavailable'}</span>{p.company && <span>{p.company}</span>}</div>
              <p>{p.fit_reason || 'Relevant professional fit based on your current connection criteria.'}</p>
              <div className="connection-actions">
                <a className="button button-quiet" href={p.profile_url} target="_blank" rel="noreferrer">Open LinkedIn ↗</a>
                {['ready','saved'].includes(p.status) && <>
                  <button className="button button-good" onClick={() => update(p.assignment_id,'connected')}>Mark connected</button>
                  <button className="button button-quiet" onClick={() => update(p.assignment_id,'save')}>Save</button>
                  <button className="button button-quiet" onClick={() => update(p.assignment_id,'skip')}>Skip</button>
                  <button className="button button-danger-quiet" onClick={() => update(p.assignment_id,'not_relevant')}>Not relevant</button>
                </>}
              </div>
            </div>
          </div>
        ))}
      </div>}
    </section>
  )
}

const NAV = [
  ['dashboard','Overview','⌂'],
  ['research','Scout','⌕'],
  ['authors','Authors','A'],
  ['messages','Messages','✉'],
  ['connections','Connections','↗'],
]

function AppCore() {
  const [keyValue, setKeyValue] = useState(() => localStorage.getItem('authorScoutSession') || '')
  const [session, setSession] = useState(null)
  const [checking, setChecking] = useState(Boolean(keyValue))
  const [loginError, setLoginError] = useState('')
  const [loginStatus, setLoginStatus] = useState('')
  const [tab, setTab] = useState('dashboard')

  const verify = useCallback(async (key) => {
    setChecking(true); setLoginError('')
    try {
      const s = await request('/api/v1/session', key)
      localStorage.setItem('authorScoutSession', key)
      setKeyValue(key)
      setChecking(false)
      setSession(s)
    } catch(e) {
      localStorage.removeItem('authorScoutSession')
      setKeyValue(''); setSession(null); setLoginError(e.message)
    } finally { setChecking(false) }
  }, [])
  const exchangeManagedAuth = useCallback(async (authResult = null) => {
    setChecking(true)
    setLoginError('')
    setLoginStatus('Opening your workspace…')
    try {
      let token=sessionTokenFrom(authResult)
      if (!token) {
        const current=await authClient.getSession()
        if (current?.error) throw new Error(current.error.message || 'Could not read your session')
        token=sessionTokenFrom(current)
      }
      if (!token) throw new Error('Signed in, but no secure session token was returned. Please try again.')
      const d=await request('/api/v1/auth/neon-session','',{
        method:'POST',
        body:JSON.stringify({ session_token: token })
      })
      localStorage.setItem('authorScoutSession',d.session)
      setKeyValue(d.session)
      const s=await request('/api/v1/session',d.session)
      setSession(s)
      setLoginStatus('')
      return s
    } catch(e) {
      setLoginError(e?.message || 'Could not open your workspace.')
      setLoginStatus('')
      throw e
    } finally {
      setChecking(false)
    }
  }, [])

  const startEmailAuth = useCallback(async (mode, form) => {
    setChecking(true)
    setLoginError('')
    setLoginStatus(mode === 'signup' ? 'Creating account…' : 'Signing in…')
    try {
      const email=String(form.email || '').trim().toLowerCase()
      const password=String(form.password || '')
      const result=mode === 'signup'
        ? await authClient.signUp.email({ email, password, name:String(form.name || '').trim() || email.split('@')[0] })
        : await authClient.signIn.email({ email, password })
      if (result?.error) throw new Error(result.error.message || 'Authentication failed')
      await exchangeManagedAuth(result)
    } catch(e) {
      setLoginError(e?.message || 'Authentication failed.')
      setLoginStatus('')
      setChecking(false)
    }
  }, [exchangeManagedAuth])

  const startManagedGoogle = useCallback(async () => {
    setChecking(true)
    setLoginError('')
    setLoginStatus('Opening Google…')
    try {
      const result=await authClient.signIn.social({
        provider:'google',
        callbackURL:window.location.origin
      })
      if (result?.error) throw new Error(result.error.message || 'Google sign-in failed')
      // Most social sign-ins redirect. If Neon returns a session directly, handle it too.
      if (sessionTokenFrom(result)) await exchangeManagedAuth(result)
    } catch(e) {
      setLoginError(e?.message || 'Google sign-in failed.')
      setLoginStatus('')
      setChecking(false)
    }
  }, [exchangeManagedAuth])


  useEffect(() => {
    let cancelled=false
    const boot=async () => {
      const params = new URLSearchParams(window.location.search)
      const incoming = params.get('session')
      const authError = params.get('auth_error')
      if (incoming) {
        localStorage.setItem('authorScoutSession', incoming)
        setKeyValue(incoming)
        window.history.replaceState({}, document.title, window.location.pathname)
        await verify(incoming)
        return
      }
      if (authError) {
        setLoginError('Sign-in was cancelled or could not be completed.')
        window.history.replaceState({}, document.title, window.location.pathname)
        return
      }
      if (keyValue && !session) {
        await verify(keyValue)
        return
      }
      // Handles return from managed Google Auth, or an existing Neon Auth browser session.
      try {
        const current=await authClient.getSession()
        if (!cancelled && !current?.error && sessionTokenFrom(current)) {
          await exchangeManagedAuth(current)
        }
      } catch {}
    }
    boot()
    return () => { cancelled=true }
  }, [])

  const logout = async () => {
    localStorage.removeItem('authorScoutSession')
    try { await authClient.signOut() } catch {}
    setKeyValue(''); setSession(null); setTab('dashboard')
  }

  if (!session) return <Login onLegacyLogin={verify} onGoogle={startManagedGoogle} onEmail={startEmailAuth} busy={checking} error={loginError} status={loginStatus} />

  const displayName = session.user?.first_name || session.user?.username || 'User'
  const initials = String(displayName || 'AS').trim().split(/\s+/).slice(0,2).map(x => x[0]).join('').toUpperCase()

  return (
    <div className="app-frame">
      <div className="app-shell">
        <header className="topbar">
          <button className="logo-pill" onClick={() => setTab('dashboard')}>Author Scout</button>

          <nav className="topnav" aria-label="Primary navigation">
            {NAV.map(([id,label]) => (
              <button key={id} onClick={() => setTab(id)} className={tab === id ? 'active' : ''}>
                {label}
              </button>
            ))}
          </nav>

          <div className="top-actions">
            <div className="workspace-summary">
              <span>{displayName}</span>
              <small>Author Scout</small>
            </div>
            <button className="avatar-button" onClick={logout} title="Sign out">{initials}</button>
          </div>
        </header>

        <div className="mobile-nav">
          <select value={tab} onChange={e => setTab(e.target.value)}>
            {NAV.map(([id,label]) => <option key={id} value={id}>{label}</option>)}
          </select>
          <button className="button button-quiet" onClick={logout}>Sign out</button>
        </div>

        <main>
          <div className={tab === 'dashboard' ? 'page-view active' : 'page-view'} aria-hidden={tab !== 'dashboard'}>
            <Dashboard keyValue={keyValue} session={session} active={tab === 'dashboard'} />
          </div>
          <div className={tab === 'research' ? 'page-view active' : 'page-view'} aria-hidden={tab !== 'research'}>
            <Research keyValue={keyValue} active={tab === 'research'} />
          </div>
          <div className={tab === 'authors' ? 'page-view active' : 'page-view'} aria-hidden={tab !== 'authors'}>
            <Authors keyValue={keyValue} active={tab === 'authors'} />
          </div>
          <div className={tab === 'messages' ? 'page-view active' : 'page-view'} aria-hidden={tab !== 'messages'}>
            <Messages keyValue={keyValue} active={tab === 'messages'} />
          </div>
          <div className={tab === 'connections' ? 'page-view active' : 'page-view'} aria-hidden={tab !== 'connections'}>
            <Connections keyValue={keyValue} active={tab === 'connections'} />
          </div>
        </main>
      </div>
    </div>
  )
}


export default function App() {
  return (
    <AppErrorBoundary>
      <AppCore />
    </AppErrorBoundary>
  )
}
