import React, { useCallback, useEffect, useMemo, useState } from 'react'

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

function fmt(value) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString()
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

function Login({ onLogin, busy, error }) {
  const [key, setKey] = useState('')
  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="brand brand-login">
          <div className="brand-mark">AS</div>
          <div>
            <strong>Author Scout</strong>
            <span>Research Intelligence</span>
          </div>
        </div>
        <h1>Open your workspace</h1>
        <p className="login-copy">
          In Telegram, send <code>/webkey</code>, copy the signed key, then paste it here.
          Your Render secret is never exposed to the browser.
        </p>
        <form onSubmit={(e) => { e.preventDefault(); onLogin(key.trim()) }}>
          <label>Web access key</label>
          <textarea
            rows="4"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Paste the key from /webkey"
            autoFocus
          />
          {error && <div className="alert alert-error">{error}</div>}
          <button className="button button-primary button-block" disabled={!key.trim() || busy}>
            {busy ? 'Checking workspace…' : 'Enter Author Scout'}
          </button>
        </form>
        <div className="login-foot">
          <span>Backend</span>
          <code>{API_BASE.replace('https://', '')}</code>
        </div>
      </div>
    </div>
  )
}

function Dashboard({ keyValue, session }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    try { setData(await request('/api/v1/dashboard', keyValue)); setError('') }
    catch (e) { setError(e.message) }
  }, [keyValue])
  usePolling(load, 8000)

  const c = data?.counts || {}
  const pool = data?.pool || {}
  return (
    <section>
      <div className="page-head">
        <div>
          <div className="eyebrow">{session?.team?.name || 'Author Scout'} workspace</div>
          <h1>Welcome in, {session?.user?.first_name || session?.user?.username || 'there'}</h1>
          <p>Your author research, outreach and relationship pipeline in one place.</p>
        </div>
        <button className="button button-quiet" onClick={load}>Refresh</button>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="metric-grid">
        <Metric label="Authors" value={c.authors} sub="Qualified and saved" />
        <Metric label="Research" value={c.jobs_queued} sub="Running now" />
        <Metric label="Connections" value={c.connections_ready} sub="Ready to review" />
        <Metric label="Messages" value={c.messages_ready} sub="Ready for outreach" />
      </div>
      <div className="two-col">
        <div className="panel">
          <div className="panel-head">
            <div><span className="kicker">Research engine</span><h2>Pipeline health</h2></div>
          </div>
          <div className="stat-list">
            <div><span>Completed research jobs</span><strong>{c.jobs_completed || 0}</strong></div>
            <div><span>Candidate reservoir</span><strong>{pool.candidates || 0}</strong></div>
            <div><span>Pre-verified candidates</span><strong>{pool.verified || 0}</strong></div>
            <div><span>Indexed sources</span><strong>{pool.sources || 0}</strong></div>
          </div>
        </div>
        <div className="panel">
          <div className="panel-head">
            <div><span className="kicker">Activity</span><h2>Acquisition status</h2></div>
          </div>
          <div className="stat-list">
            <div><span>Connections completed</span><strong>{c.connections_done || 0}</strong></div>
            <div><span>Messages sent</span><strong>{c.messages_sent || 0}</strong></div>
            <div><span>Messages ready</span><strong>{c.messages_ready || 0}</strong></div>
            <div><span>Background connection research</span><strong>On</strong></div>
          </div>
        </div>
      </div>
      <div className="panel callout">
        <div>
          <span className="kicker">Research flow</span>
          <h2>Research keeps moving while you work.</h2>
          <p>Start a search, leave it running, and come back to qualified authors when they are ready.</p>
        </div>
        <div className="flow">
          <span>Query</span><b>→</b><span>Queue</span><b>→</b><span>Workers</span><b>→</b><span>Verify</span><b>→</b><span>Ready</span>
        </div>
      </div>
    </section>
  )
}

function Research({ keyValue }) {
  const [query, setQuery] = useState('')
  const [count, setCount] = useState(25)
  const [jobs, setJobs] = useState([])
  const [selected, setSelected] = useState(null)
  const [creating, setCreating] = useState(false)
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

  usePolling(loadJobs, 4000)

  const create = async (e) => {
    e.preventDefault()
    if (!query.trim()) return
    setCreating(true); setError('')
    try {
      const d = await request('/api/v1/research/jobs', keyValue, {
        method: 'POST',
        body: JSON.stringify({ query: query.trim(), count: Number(count) || 25 })
      })
      setQuery('')
      await loadJobs()
      const detail = await request('/api/v1/research/jobs/' + d.job_id, keyValue)
      setSelected(detail)
    } catch (e) { setError(e.message) }
    finally { setCreating(false) }
  }

  const openJob = async (id) => {
    try { setSelected(await request('/api/v1/research/jobs/' + id, keyValue)) }
    catch (e) { setError(e.message) }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <div className="eyebrow">Author discovery</div>
          <h1>Research</h1>
          <p>Give the engine a real target. Nothing searches until you submit a query.</p>
        </div>
      </div>

      <div className="panel research-compose">
        <form onSubmit={create}>
          <label>What authors do you want to find?</label>
          <textarea
            rows="4"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Example: emerging male fantasy authors in Canada, active in 2026, with official website and verified public professional email"
          />
          <div className="compose-row">
            <div className="field-small">
              <label>Target results</label>
              <input type="number" min="1" max="50" value={count} onChange={e => setCount(e.target.value)} />
            </div>
            <div className="compose-hint">The engine filters duplicates, generic contacts, junk identities and high-saturation authors before saving results.</div>
            <button className="button button-primary" disabled={creating || !query.trim()}>
              {creating ? 'Queuing…' : 'Start research'}
            </button>
          </div>
        </form>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="research-layout">
        <div className="panel jobs-panel">
          <div className="panel-head"><div><span className="kicker">Live queue</span><h2>Research jobs</h2></div><button className="button button-quiet" onClick={loadJobs}>Refresh</button></div>
          {!jobs.length ? <Empty title="No research jobs yet" body="Submit your first specific author search above." /> :
            <div className="job-list">
              {jobs.map(job => (
                <button key={job.id} className={'job-row ' + (selected?.job?.id === job.id ? 'active' : '')} onClick={() => openJob(job.id)}>
                  <div className="job-top"><Status value={job.status} /><span>#{job.id}</span></div>
                  <strong>{short(job.query_text, 92)}</strong>
                  <div className="job-meta">
                    <span>{job.accepted || 0}/{job.requested_count} saved</span>
                    <span>{job.checked || 0} checked</span>
                    <span>{fmt(job.created_at)}</span>
                  </div>
                  {['queued','starting','running'].includes(job.status) && <div className="progress"><i style={{width: Math.min(92, Math.max(8, ((job.accepted || 0) / Math.max(1, job.requested_count)) * 100)) + '%'}} /></div>}
                </button>
              ))}
            </div>}
        </div>

        <div className="panel job-detail">
          {!selected ? <Empty title="Select a research job" body="Open a job to watch progress and inspect the qualified authors it produced." /> : (
            <>
              <div className="panel-head">
                <div><span className="kicker">Research job #{selected.job.id}</span><h2>{short(selected.job.query_text, 78)}</h2></div>
                <Status value={selected.job.status} />
              </div>
              <div className="job-summary-grid">
                <Metric label="Requested" value={selected.job.requested_count} />
                <Metric label="Saved" value={selected.job.accepted} />
                <Metric label="Checked" value={selected.job.checked} />
                <Metric label="Duplicates" value={selected.job.duplicates} />
              </div>
              <div className="progress-message">{selected.job.progress_text || 'Waiting for worker…'}</div>
              {selected.job.error && <div className="alert alert-error">{selected.job.error}</div>}
              <div className="result-stack">
                {(selected.results || []).map(author => (
                  <div className="result-card" key={author.id}>
                    <div>
                      <strong>{author.name}</strong>
                      <span>{[author.country, author.genre].filter(Boolean).join(' · ') || 'Author'}</span>
                    </div>
                    <div className="result-contact">
                      {author.email && <a href={'mailto:' + author.email}>{author.email}</a>}
                      {author.website && <a href={author.website} target="_blank" rel="noreferrer">Website ↗</a>}
                    </div>
                  </div>
                ))}
              </div>
              {selected.job.status === 'completed' && !(selected.results || []).length &&
                <Empty title="No new authors saved" body="Candidates may have failed verification or already existed in the shared database." />}
            </>
          )}
        </div>
      </div>
    </section>
  )
}

function Authors({ keyValue }) {
  const [authors, setAuthors] = useState([])
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    try {
      const q = search.trim() ? '&search=' + encodeURIComponent(search.trim()) : ''
      const d = await request('/api/v1/authors?limit=250' + q, keyValue)
      setAuthors(d.authors || []); setError('')
    } catch (e) { setError(e.message) }
  }, [keyValue, search])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])

  return (
    <section>
      <div className="page-head">
        <div><div className="eyebrow">Verified database</div><h1>Authors</h1><p>Qualified authors already claimed by your workspace.</p></div>
        <input className="search-box" placeholder="Search authors…" value={search} onChange={e => setSearch(e.target.value)} />
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="panel table-panel">
        {!authors.length ? <Empty title="No matching authors" body="Run a research job to build your verified author database." /> :
        <div className="table-wrap">
          <table>
            <thead><tr><th>Author</th><th>Country</th><th>Genre</th><th>Public email</th><th>Website</th><th>Activity</th></tr></thead>
            <tbody>
              {authors.map(a => <tr key={a.id}>
                <td><strong>{a.name}</strong><small>#{a.id}</small></td>
                <td>{a.country || '—'}</td>
                <td>{a.genre || '—'}</td>
                <td>{a.email ? <a href={'mailto:' + a.email}>{a.email}</a> : '—'}</td>
                <td>{a.website ? <a target="_blank" rel="noreferrer" href={a.website}>Open ↗</a> : '—'}</td>
                <td title={a.recent_activity}>{short(a.recent_activity, 90) || '—'}</td>
              </tr>)}
            </tbody>
          </table>
        </div>}
      </div>
    </section>
  )
}


function Messages({ keyValue }) {
  const [items, setItems] = useState([])
  const [status, setStatus] = useState('ready')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null)
  const [gmail, setGmail] = useState({ connected: false, accounts: [] })
  const [busyId, setBusyId] = useState(null)
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
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
  }, [load])

  usePolling(load, 9000)

  const openGmail = async (id) => {
    setBusyId(id); setError(''); setNotice('')
    try {
      const d = await request('/api/v1/messages/' + id + '/compose-link', keyValue)
      window.open(d.url, '_blank', 'noopener,noreferrer')
    } catch (e) { setError(e.message) }
    finally { setBusyId(null) }
  }

  const updateStatus = async (id, next) => {
    setBusyId(id); setError(''); setNotice('')
    try {
      await request('/api/v1/messages/' + id + '/status', keyValue, {
        method: 'POST',
        body: JSON.stringify({ status: next })
      })
      setNotice(next === 'replied' ? 'Message marked as replied.' : next === 'sent' ? 'Message marked as sent.' : 'Message moved back to ready.')
      setSelected(null)
      await load()
    } catch (e) { setError(e.message) }
    finally { setBusyId(null) }
  }

  const autoSend = async (id) => {
    if (!window.confirm('Send this message now through your connected Gmail account?')) return
    setBusyId(id); setError(''); setNotice('')
    try {
      const d = await request('/api/v1/messages/' + id + '/send', keyValue, {
        method: 'POST',
        body: JSON.stringify({})
      })
      setNotice('Sent through ' + (d.sender_email || 'your connected Gmail') + '.')
      setSelected(null)
      await load()
    } catch (e) { setError(e.message) }
    finally { setBusyId(null) }
  }

  const copyText = async (m) => {
    try {
      await navigator.clipboard.writeText((m.subject ? 'Subject: ' + m.subject + '\n\n' : '') + (m.body || ''))
      setNotice('Subject and message copied.')
    } catch {
      setError('Copy failed. Select the message text manually.')
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <div className="eyebrow">Author outreach</div>
          <h1>Messages</h1>
          <p>Review approved outreach, open it in Gmail, send through your connected account, and track replies.</p>
        </div>
        <div className="message-toolbar">
          <input className="search-box" placeholder="Search author, email or subject…" value={search} onChange={e => setSearch(e.target.value)} />
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
          ? 'Gmail connected: ' + (gmail.accounts || []).map(a => a.email).join(', ') + '. Auto Send is available.'
          : 'Gmail Auto Send is locked. In Telegram, use /gmail to connect an account. You can still use Open Gmail and Mark Sent.'}
      </div>
      {notice && <div className="alert alert-success">{notice}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      <div className="panel table-panel">
        {!items.length ? <Empty title={'No ' + status + ' messages'} body={status === 'ready' ? 'Import a completed outreach workbook in Telegram. Ready messages will appear here automatically.' : 'No messages match this view yet.'} /> :
        <div className="table-wrap">
          <table>
            <thead><tr><th>Author</th><th>Recipient</th><th>Subject</th><th>Status</th><th>Sent</th><th>Actions</th></tr></thead>
            <tbody>
              {items.map(m => <tr key={m.id}>
                <td><strong>{m.author_name}</strong><small>{[m.author_country, m.author_genre].filter(Boolean).join(' · ') || '#' + m.id}</small></td>
                <td>{m.recipient ? <a href={'mailto:' + m.recipient}>{m.recipient}</a> : '—'}</td>
                <td title={m.subject}>{short(m.subject, 72) || '—'}</td>
                <td><Status value={m.reply_status === 'replied' ? 'replied' : m.status} /></td>
                <td>{fmt(m.sent_at)}</td>
                <td>
                  <div className="inline-actions">
                    <button className="button button-quiet" onClick={() => setSelected(m)}>Review</button>
                    {m.status !== 'sent' && <button className="button button-quiet" disabled={busyId === m.id} onClick={() => openGmail(m.id)}>Open Gmail</button>}
                    {m.status !== 'sent' && gmail.connected && <button className="button button-good" disabled={busyId === m.id} onClick={() => autoSend(m.id)}>Auto Send</button>}
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
          {selected.status !== 'sent' && <button className="button button-quiet" disabled={busyId === selected.id} onClick={() => openGmail(selected.id)}>Open Gmail</button>}
          {selected.status !== 'sent' && gmail.connected && <button className="button button-good" disabled={busyId === selected.id} onClick={() => autoSend(selected.id)}>Auto Send</button>}
          {selected.status !== 'sent' && <button className="button button-quiet" disabled={busyId === selected.id} onClick={() => updateStatus(selected.id, 'sent')}>Mark Sent</button>}
          {selected.status === 'sent' && selected.reply_status !== 'replied' && <button className="button button-good" disabled={busyId === selected.id} onClick={() => updateStatus(selected.id, 'replied')}>Mark Replied</button>}
          {selected.status === 'sent' && <button className="button button-danger-quiet" disabled={busyId === selected.id} onClick={() => updateStatus(selected.id, 'ready')}>Move to Ready</button>}
        </div>
      </div>}
    </section>
  )
}

function Connections({ keyValue }) {
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
  usePolling(load, 7000)

  const setup = async e => {
    e.preventDefault(); setBusy(true); setError(''); setNotice('')
    try {
      await request('/api/v1/connections/setup', keyValue, {
        method:'POST', body: JSON.stringify({ linkedin_url: linkedin.trim(), focus: focus.trim() })
      })
      setNotice('Connection Intelligence is active. Background research will begin filling your queue.')
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
        <div><div className="eyebrow">LinkedIn network intelligence</div><h1>Connections</h1><p>Background-researched profiles, scored before they enter your queue.</p></div>
        <select className="select" value={status} onChange={e => setStatus(e.target.value)}>
          <option value="ready">Ready / saved</option>
          <option value="connected">Connected</option>
          <option value="skipped">Skipped</option>
          <option value="not_relevant">Not relevant</option>
        </select>
      </div>

      <div className="panel connection-setup">
        <div><span className="kicker">Set your targeting profile</span><h2>Connection Intelligence setup</h2><p>Public location evidence in Nigeria is excluded by default. The system does not infer nationality from names or photos.</p></div>
        <form onSubmit={setup}>
          <input placeholder="https://www.linkedin.com/in/your-profile" value={linkedin} onChange={e => setLinkedin(e.target.value)} />
          <input placeholder="Optional focus: publishing founders, authors, literary agents…" value={focus} onChange={e => setFocus(e.target.value)} />
          <button className="button button-primary" disabled={busy || !linkedin.trim()}>{busy ? 'Setting up…' : 'Enable / update'}</button>
        </form>
      </div>
      {notice && <div className="alert alert-success">{notice}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {!items.length ? <div className="panel"><Empty title={status === 'ready' ? 'No ready profiles yet' : 'Nothing in this status'} body={status === 'ready' ? 'Once Connection Intelligence is configured, Render keeps researching and replenishing this queue in the background.' : 'Profiles will appear here as their status changes.'} /></div> :
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

function System({ keyValue }) {
  const [source, setSource] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    try {
      const [a,b] = await Promise.all([
        request('/api/v1/source-status', keyValue),
        request('/api/v1/health', '')
      ])
      setSource(a); setHealth(b); setError('')
    } catch(e){ setError(e.message) }
  }, [keyValue])
  usePolling(load, 10000)

  return (
    <section>
      <div className="page-head">
        <div><div className="eyebrow">Infrastructure</div><h1>System</h1><p>What the background research engine is actually doing.</p></div>
        <button className="button button-quiet" onClick={load}>Refresh</button>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="metric-grid">
        <Metric label="API" value={health?.ok ? 'Online' : 'Checking'} sub={'v' + (health?.version || '…')} />
        <Metric label="Active demands" value={source?.demands || 0} sub="Created by real queries" />
        <Metric label="Indexed sources" value={source?.sources || 0} sub="Reusable source pages" />
        <Metric label="Pre-verified" value={source?.verified || 0} sub="Ready reservoir candidates" />
      </div>
      <div className="panel">
        <span className="kicker">Architecture</span>
        <h2>Vercel is the interface. Render does the long-running work.</h2>
        <div className="architecture">
          <div><strong>Vercel</strong><span>Dashboard UI</span></div><b>→</b>
          <div><strong>Render API</strong><span>Queue + workers</span></div><b>→</b>
          <div><strong>Neon</strong><span>Shared database</span></div>
        </div>
        <p className="muted">Telegram stays connected to the same backend as a lightweight mobile companion. Authors and connections seen here are the same records used by the bot.</p>
      </div>
    </section>
  )
}

const NAV = [
  ['dashboard','Overview','⌂'],
  ['research','Research','⌕'],
  ['authors','Authors','A'],
  ['messages','Messages','✉'],
  ['connections','Connections','↗'],
  ['system','System','⚙'],
]

function AppCore() {
  const [keyValue, setKeyValue] = useState(() => sessionStorage.getItem('authorScoutKey') || '')
  const [session, setSession] = useState(null)
  const [checking, setChecking] = useState(Boolean(keyValue))
  const [loginError, setLoginError] = useState('')
  const [tab, setTab] = useState('dashboard')

  const verify = useCallback(async (key) => {
    setChecking(true); setLoginError('')
    try {
      const s = await request('/api/v1/session', key)
      sessionStorage.setItem('authorScoutKey', key)
      setKeyValue(key)
      setChecking(false)
      setSession(s)
    } catch(e) {
      sessionStorage.removeItem('authorScoutKey')
      setKeyValue(''); setSession(null); setLoginError(e.message)
    } finally { setChecking(false) }
  }, [])

  useEffect(() => { if (keyValue && !session) verify(keyValue) }, [])

  const logout = () => {
    sessionStorage.removeItem('authorScoutKey')
    setKeyValue(''); setSession(null); setTab('dashboard')
  }

  if (!session) return <Login onLogin={verify} busy={checking} error={loginError} />

  const displayName = session.user?.first_name || session.user?.username || 'Team member'
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
              <span>{session.team?.name || 'Workspace'}</span>
              <small>{displayName}</small>
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
          {tab === 'dashboard' && <Dashboard keyValue={keyValue} session={session} />}
          {tab === 'research' && <Research keyValue={keyValue} />}
          {tab === 'authors' && <Authors keyValue={keyValue} />}
          {tab === 'messages' && <Messages keyValue={keyValue} />}
          {tab === 'connections' && <Connections keyValue={keyValue} />}
          {tab === 'system' && <System keyValue={keyValue} />}
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
