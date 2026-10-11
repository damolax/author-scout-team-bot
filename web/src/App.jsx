import React, { useCallback, useEffect, useState } from 'react'
import { authClient, sessionTokenFrom } from './auth.js'
import Letterdesk from './Letterdesk.jsx'

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

function Login({ onLegacyLogin, onGoogle, onEmail, onForgot, busy, error, status }) {
  const [mode, setMode] = useState('signin')
  const [showLegacy, setShowLegacy] = useState(false)
  const [legacyKey, setLegacyKey] = useState('')
  const [forgotSent, setForgotSent] = useState(false)
  const [form, setForm] = useState({ name:'', email:'', password:'' })
  const setField = (k,v) => setForm(prev => ({...prev,[k]:v}))
  const signup = mode === 'signup'
  const forgot = mode === 'forgot'

  const submitForgot = async (e) => {
    e.preventDefault()
    const ok = await onForgot(form.email)
    if (ok) setForgotSent(true)
  }

  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="brand brand-login">
          <div className="brand-mark">AS</div>
          <div><strong>Author Scout</strong><span>Research Intelligence</span></div>
        </div>

        {forgot ? <>
          <h1>Reset your password</h1>
          <p className="login-copy">
            Enter the email address for your Author Scout account. We’ll send you a secure reset link.
          </p>
          {error && <div className="alert alert-error">{error}</div>}
          {forgotSent ? <div className="forgot-success">
            <div className="forgot-success-icon">✓</div>
            <h3>Check your email</h3>
            <p>If an account exists for <strong>{form.email}</strong>, a password reset link has been sent.</p>
            <button className="button button-auth-email button-block" onClick={() => { setMode('signin'); setForgotSent(false) }}>
              Back to sign in
            </button>
          </div> : <form className="email-auth-form" onSubmit={submitForgot}>
            <div className="field">
              <label>Email</label>
              <input type="email" value={form.email} onChange={e => setField('email',e.target.value)}
                placeholder="you@example.com" autoComplete="email" required />
            </div>
            <button className="button button-auth-email button-block" disabled={busy}>
              {busy ? (status || 'Sending reset link…') : 'Send reset link'}
            </button>
            <button type="button" className="auth-switch" onClick={() => setMode('signin')} disabled={busy}>
              Back to sign in
            </button>
          </form>}
        </> : <>
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
              <div className="label-row">
                <label>Password</label>
                {!signup && <button type="button" className="forgot-link" onClick={() => setMode('forgot')}>Forgot password?</button>}
              </div>
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
        </>}
      </div>
    </div>
  )
}

function ResetPasswordScreen({ token, errorCode, onDone }) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(errorCode ? 'This reset link is invalid or has expired. Request a new one.' : '')
  const [done, setDone] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (password.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (password !== confirm) { setError('The passwords do not match.'); return }
    if (!token) { setError('This reset link is invalid or has expired.'); return }
    setBusy(true); setError('')
    try {
      const result = await authClient.resetPassword({ newPassword: password, token })
      if (result?.error) throw new Error(result.error.message || 'Could not reset password')
      setDone(true)
    } catch(e) {
      setError(e?.message || 'Could not reset password. Please request a new reset link.')
    } finally { setBusy(false) }
  }

  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="brand brand-login">
          <div className="brand-mark">AS</div>
          <div><strong>Author Scout</strong><span>Research Intelligence</span></div>
        </div>
        {done ? <>
          <div className="forgot-success">
            <div className="forgot-success-icon">✓</div>
            <h1>Password updated</h1>
            <p>Your new password is ready. You can sign in to Author Scout now.</p>
            <button className="button button-auth-email button-block" onClick={onDone}>Continue to sign in</button>
          </div>
        </> : <>
          <h1>Choose a new password</h1>
          <p className="login-copy">Enter a new password for your Author Scout account.</p>
          {error && <div className="alert alert-error">{error}</div>}
          <form className="email-auth-form" onSubmit={submit}>
            <div className="field">
              <label>New password</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                minLength="8" autoComplete="new-password" placeholder="At least 8 characters" required />
            </div>
            <div className="field">
              <label>Confirm new password</label>
              <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)}
                minLength="8" autoComplete="new-password" placeholder="Repeat your new password" required />
            </div>
            <button className="button button-auth-email button-block" disabled={busy || !token}>
              {busy ? 'Updating password…' : 'Set new password'}
            </button>
          </form>
          <button className="auth-switch" onClick={onDone}>Back to sign in</button>
        </>}
      </div>
    </div>
  )
}

function Dashboard({ keyValue, session, active }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [telegram, setTelegram] = useState(null)
  const [linking, setLinking] = useState(false)
  const [authMethods, setAuthMethods] = useState([])
  const [authMethodsError, setAuthMethodsError] = useState('')
  const [googleLinking, setGoogleLinking] = useState(false)
  const load = useCallback(async () => {
    try { setData(await request('/api/v1/dashboard', keyValue)); setError('') }
    catch (e) { setError(e.message) }
  }, [keyValue])
  usePolling(load, 8000, active)

  const loadAuthMethods = useCallback(async () => {
    try {
      const result=await authClient.listAccounts()
      if (result?.error) throw new Error(result.error.message || 'Could not read sign-in methods')
      setAuthMethods(Array.isArray(result?.data) ? result.data : [])
      setAuthMethodsError('')
    } catch(e) {
      // Older /webkey-only sessions may not have an active managed-auth cookie.
      setAuthMethods([])
      setAuthMethodsError('')
    }
  }, [])

  useEffect(() => {
    if (active) loadAuthMethods()
  }, [active, loadAuthMethods])

  const linkGoogle = async () => {
    setGoogleLinking(true)
    setAuthMethodsError('')
    try {
      const result=await authClient.linkSocial({
        provider:'google',
        callbackURL:window.location.origin
      })
      if (result?.error) throw new Error(result.error.message || 'Could not connect Google')
      if (result?.data && !result.data.url) await loadAuthMethods()
    } catch(e) {
      setAuthMethodsError(e?.message || 'Could not connect Google. Use the same email address as your Author Scout account.')
      setGoogleLinking(false)
    }
  }

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

      <div className="panel account-access-card">
        <div>
          <div className="eyebrow">Sign-in methods</div>
          <h2>Use email/password or Google</h2>
          <p>Both methods can open the same Author Scout workspace. Google linking only accepts the matching account email.</p>
        </div>
        <div className="auth-methods">
          <div className="auth-method-row">
            <span className="auth-method-icon">@</span>
            <div><strong>Email & password</strong><small>Available for this account</small></div>
            <span className="status status-completed">Enabled</span>
          </div>
          <div className="auth-method-row">
            <span className="auth-method-icon">G</span>
            <div><strong>Google</strong><small>{authMethods.some(a => a.providerId === 'google') ? 'Connected to this account' : 'Optional sign-in method'}</small></div>
            {authMethods.some(a => a.providerId === 'google')
              ? <span className="status status-completed">Connected</span>
              : <button className="button button-quiet" onClick={linkGoogle} disabled={googleLinking}>
                  {googleLinking ? 'Connecting…' : 'Connect Google'}
                </button>}
          </div>
          {authMethodsError && <div className="alert alert-error">{authMethodsError}</div>}
        </div>
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

const COUNTRY_SUGGESTIONS = [
  'United States','United Kingdom','Canada','Australia','France','Germany','Austria','United Arab Emirates',
  'New Zealand','Spain','Iceland','Saudi Arabia','Portugal','Italy','Netherlands','Belgium','Switzerland',
  'Sweden','Norway','Denmark','Finland','Ireland','India','Japan','South Korea','Singapore','South Africa',
  'Nigeria','Ghana','Kenya','Mexico','Brazil','Argentina','Chile','Colombia','Poland','Czech Republic',
  'Greece','Romania','Hungary','Croatia','Serbia','Turkey','Israel','Egypt','Morocco','Qatar'
]

const GENRE_SUGGESTIONS = [
  'Literary Fiction','Contemporary Fiction','Historical Fiction','Commercial Fiction','Upmarket Fiction',
  'Women’s Fiction','Family Saga','Coming of Age','Romance','Contemporary Romance','Historical Romance',
  'Romantic Comedy','Romantic Suspense','Paranormal Romance','Fantasy Romance','Romantasy','Dark Romance',
  'Inspirational Romance','Mystery','Cozy Mystery','Historical Mystery','Police Procedural','Detective Fiction',
  'Crime Fiction','Psychological Thriller','Domestic Thriller','Legal Thriller','Political Thriller',
  'Techno Thriller','Medical Thriller','Espionage Thriller','Action Thriller','Suspense','Horror',
  'Gothic Horror','Psychological Horror','Supernatural Horror','Folk Horror','Dark Fiction','Fantasy',
  'Epic Fantasy','High Fantasy','Low Fantasy','Urban Fantasy','Dark Fantasy','Portal Fantasy','Sword and Sorcery',
  'Mythic Fantasy','Fairy Tale Retelling','Science Fiction','Hard Science Fiction','Soft Science Fiction',
  'Space Opera','Cyberpunk','Solarpunk','Climate Fiction','Dystopian Fiction','Post Apocalyptic Fiction',
  'Alternate History','Time Travel Fiction','Speculative Fiction','Magical Realism','Adventure Fiction','Western',
  'Satire','Humor Fiction','Absurdist Fiction','Experimental Fiction','Short Stories','Flash Fiction','Novella',
  'Poetry','Contemporary Poetry','Spoken Word Poetry','Narrative Poetry','Haiku','Christian Fiction',
  'Inspirational Fiction','Faith Based Fiction','LGBTQ+ Fiction','African Fiction','Caribbean Fiction',
  'Diaspora Fiction','Indigenous Fiction','Young Adult','YA Fantasy','YA Romance','YA Thriller','YA Contemporary',
  'Middle Grade','Middle Grade Fantasy','Middle Grade Adventure','Children’s Fiction','Picture Books',
  'Early Reader','Chapter Books','Graphic Novel','Comics','Manga','Memoir','Autobiography','Biography',
  'Personal Essay','Narrative Nonfiction','True Crime','History','Military History','Cultural History',
  'Art History','Politics and Current Affairs','Journalism','Social Commentary','Psychology','Philosophy',
  'Religion and Spirituality','Christian Nonfiction','Self Help','Personal Development','Productivity',
  'Business','Entrepreneurship','Leadership','Management','Marketing','Sales','Career Development',
  'Personal Finance','Investing','Economics','Technology','Artificial Intelligence','Computer Science',
  'Popular Science','Nature Writing','Environment','Travel Writing','Food Writing','Cookbook','Health and Wellness',
  'Fitness','Parenting','Relationships','Education','Academic Writing','Reference','How To','Craft and Hobbies',
  'Sports','Music','Film and Media','Photography','Architecture','Design','Humor Nonfiction'
]

const POSITION_SUGGESTIONS = [
  'debut author','emerging author','early career author','mid-list author','established non-celebrity author',
  'independent author','self-published author','traditionally published author','hybrid author','small press author',
  'novelist','poet','memoirist','essayist','children’s author','young adult author','academic author',
  'business author','thought leadership author','genre specialist','award-listed emerging author'
]

const LANGUAGE_SUGGESTIONS = [
  'English','Spanish','French','German','Arabic','Portuguese','Italian','Dutch','Catalan','Swedish',
  'Norwegian','Danish','Finnish','Icelandic','Polish','Turkish','Hebrew','Hindi','Japanese','Korean'
]

const ACTIVITY_OPTIONS = [
  'active 2026','recent release','current work in progress','newsletter activity','event activity',
  'publisher announcement','award or shortlist','media/interview activity','book launch'
]

const PUBLISHING_OPTIONS = [
  'self-published','independent press','traditional publisher','hybrid published','small press','unagented'
]

const SOURCE_OPTIONS = [
  'general','official websites','writers associations','literature centers','publishers','independent presses',
  'literary agencies','festivals','book fairs','directories','newsletters','interviews','awards','universities','libraries'
]

function TagPicker({ label, values, onChange, suggestions=[], placeholder='', helper='', max=100, allowAll=false }) {
  const [draft, setDraft] = useState('')
  const listId = 'tag-' + label.toLowerCase().replace(/[^a-z0-9]+/g,'-')
  const add = (raw) => {
    const incoming=String(raw || '').split(/[,;\n|]+/).map(x => x.trim()).filter(Boolean)
    if (!incoming.length) return
    const seen=new Set(values.map(v => String(v).toLowerCase()))
    const next=[...values]
    for (const item of incoming) {
      if (next.length >= max) break
      const key=item.toLowerCase()
      if (!seen.has(key)) { seen.add(key); next.push(item) }
    }
    onChange(next)
    setDraft('')
  }
  const remove = (value) => onChange(values.filter(v => v !== value))
  return (
    <div className="field tag-picker">
      <div className="tag-label-row">
        <label>{label}</label>
        {allowAll && suggestions.length > 0 && <button type="button" className="mini-link" onClick={() => onChange(suggestions.slice(0,max))}>
          Use all {Math.min(max,suggestions.length)}
        </button>}
      </div>
      {!!values.length && <div className="tag-list">
        {values.map(v => <button key={v} type="button" className="tag-chip" onClick={() => remove(v)} title="Remove">
          {v}<span>×</span>
        </button>)}
      </div>}
      <div className="tag-input-row">
        <input
          list={listId}
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault()
              add(draft)
            }
          }}
          onBlur={() => { if (draft.trim()) add(draft) }}
          placeholder={placeholder}
        />
        <button type="button" className="button button-quiet tag-add" onMouseDown={e => e.preventDefault()} onClick={() => add(draft)}>Add</button>
      </div>
      <datalist id={listId}>{suggestions.map(x => <option key={x} value={x} />)}</datalist>
      {helper && <small className="field-helper">{helper}</small>}
    </div>
  )
}

function TogglePills({ label, values, selected, onChange, helper='' }) {
  const toggle = (value) => onChange(selected.includes(value) ? selected.filter(x => x !== value) : [...selected,value])
  return (
    <div className="field toggle-field">
      <label>{label}</label>
      <div className="toggle-pills">
        {values.map(value => <button key={value} type="button"
          className={selected.includes(value) ? 'toggle-pill active' : 'toggle-pill'}
          onClick={() => toggle(value)}>{value}</button>)}
      </div>
      {helper && <small className="field-helper">{helper}</small>}
    </div>
  )
}

function Research({ keyValue, active }) {
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState({ name:'', year:'' })
  const [presearch, setPresearch] = useState({
    countries:[],
    genres:[],
    genders:['any'],
    positions:[],
    languages:[],
    activity_signals:['active 2026'],
    publishing_paths:[],
    source_types:['general'],
    saturation:'low saturation emerging mid-list non-celebrity',
    require_website:false,
    require_public_email:false,
  })
  const [showMoreFilters, setShowMoreFilters] = useState(true)
  const [duration, setDuration] = useState(10)
  const [jobs, setJobs] = useState([])
  const [selected, setSelected] = useState(null)
  const [creating, setCreating] = useState(false)
  const [stoppingId, setStoppingId] = useState(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const setPre = (key,value) => setPresearch(prev => ({...prev,[key]:value}))
  const setFilter = (key,value) => setFilters(prev => ({...prev,[key]:value}))

  const genderRouteCount = presearch.genders.includes('any') || !presearch.genders.length ? 1 : presearch.genders.length
  const dimensionCount = [
    presearch.countries.length || 1,
    presearch.genres.length || 1,
    genderRouteCount,
    presearch.positions.length || 1,
    presearch.languages.length || 1,
    presearch.activity_signals.length || 1,
    presearch.publishing_paths.length || 1,
    presearch.source_types.length || 1,
  ].reduce((a,b) => a*b,1)
  const potentialRoutes = dimensionCount * 4
  const routesUsed = Math.min(5000,potentialRoutes)

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

  const hasScoutCriteria = query.trim()
    || String(filters.name || '').trim()
    || String(filters.year || '').trim()
    || presearch.countries.length
    || presearch.genres.length
    || presearch.positions.length
    || presearch.languages.length
    || presearch.activity_signals.length
    || presearch.publishing_paths.length
    || presearch.source_types.some(x => x !== 'general')
    || presearch.genders.some(x => x !== 'any')

  const setGenderMode = (value) => {
    if (value === 'any') { setPre('genders',['any']); return }
    const current=presearch.genders.filter(x => x !== 'any')
    const next=current.includes(value) ? current.filter(x => x !== value) : [...current,value]
    setPre('genders',next.length ? next : ['any'])
  }

  const create = async (e) => {
    e.preventDefault()
    if (!hasScoutCriteria) return
    setCreating(true); setError(''); setNotice('')
    try {
      const d = await request('/api/v1/research/jobs', keyValue, {
        method: 'POST',
        body: JSON.stringify({ query: query.trim(), filters, presearch, duration_minutes: Number(duration) || 10 })
      })
      setNotice('Scout queued with ' + Number(d.search_plan_total || potentialRoutes).toLocaleString() + ' possible search routes.')
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
          <p>Build a diversified search plan before the Scout starts. The worker rotates through combinations instead of repeating one query.</p>
        </div>
      </div>

      <div className="panel research-compose">
        <form onSubmit={create}>
          <div className="filter-head">
            <div>
              <label>Pre-search builder</label>
              <p>Combine multiple countries, genres, genders, positions and discovery signals.</p>
            </div>
            <div className="route-counter">
              <strong>{potentialRoutes.toLocaleString()}</strong>
              <span>possible search prompts</span>
              {potentialRoutes > 5000 && <small>First 5,000 diversified routes used per Scout</small>}
            </div>
          </div>

          <div className="presearch-grid">
            <TagPicker
              label="Countries"
              values={presearch.countries}
              onChange={v => setPre('countries',v)}
              suggestions={COUNTRY_SUGGESTIONS}
              placeholder="Add country, then Enter"
              helper="Add one or many. Country remains a strict market filter."
              max={40}
            />
            <TagPicker
              label="Genres"
              values={presearch.genres}
              onChange={v => setPre('genres',v)}
              suggestions={GENRE_SUGGESTIONS}
              placeholder="Add genre, then Enter"
              helper={GENRE_SUGGESTIONS.length + ' genre suggestions are available. You can also type your own.'}
              max={100}
              allowAll
            />
            <TagPicker
              label="Position / career stage"
              values={presearch.positions}
              onChange={v => setPre('positions',v)}
              suggestions={POSITION_SUGGESTIONS}
              placeholder="e.g. debut author, mid-list author"
              helper="Free input is supported, so you can define any author position you want."
              max={30}
            />
            <TagPicker
              label="Languages"
              values={presearch.languages}
              onChange={v => setPre('languages',v)}
              suggestions={LANGUAGE_SUGGESTIONS}
              placeholder="English, Spanish, French…"
              max={30}
            />
          </div>

          <div className="gender-builder">
            <label>Gender routes</label>
            <div className="toggle-pills">
              <button type="button" className={presearch.genders.includes('any') ? 'toggle-pill active' : 'toggle-pill'} onClick={() => setGenderMode('any')}>Any</button>
              <button type="button" className={presearch.genders.includes('male') ? 'toggle-pill active' : 'toggle-pill'} onClick={() => setGenderMode('male')}>Male</button>
              <button type="button" className={presearch.genders.includes('female') ? 'toggle-pill active' : 'toggle-pill'} onClick={() => setGenderMode('female')}>Female</button>
            </div>
            <small className="field-helper">Select Male + Female to generate separate search routes for each.</small>
          </div>

          <button type="button" className="filter-toggle" onClick={() => setShowMoreFilters(v => !v)}>
            {showMoreFilters ? 'Hide route expansion filters' : 'More route expansion filters'} <span>{showMoreFilters ? '−' : '+'}</span>
          </button>

          {showMoreFilters && <div className="route-expansion">
            <TogglePills label="Current activity signals" values={ACTIVITY_OPTIONS}
              selected={presearch.activity_signals} onChange={v => setPre('activity_signals',v)}
              helper="Each selected activity signal creates additional search combinations." />
            <TogglePills label="Publishing path" values={PUBLISHING_OPTIONS}
              selected={presearch.publishing_paths} onChange={v => setPre('publishing_paths',v)} />
            <TogglePills label="Discovery source routes" values={SOURCE_OPTIONS}
              selected={presearch.source_types} onChange={v => setPre('source_types',v)}
              helper="This helps the Scout move beyond generic web results into associations, presses, festivals, directories and other source types." />

            <div className="scout-filter-grid extra">
              <div className="field">
                <label>Name contains</label>
                <input value={filters.name} onChange={e => setFilter('name', e.target.value)} placeholder="Optional author name" />
              </div>
              <div className="field">
                <label>Activity year</label>
                <input value={filters.year} onChange={e => setFilter('year', e.target.value)} placeholder="2026" />
              </div>
              <div className="field">
                <label>Saturation / market position</label>
                <input value={presearch.saturation} onChange={e => setPre('saturation',e.target.value)}
                  placeholder="low saturation emerging mid-list non-celebrity" />
              </div>
            </div>

            <div className="requirement-row">
              <label className="check-card">
                <input type="checkbox" checked={presearch.require_website} onChange={e => setPre('require_website',e.target.checked)} />
                <span><strong>Website route signal</strong><small>Add official-website language to discovery prompts.</small></span>
              </label>
              <label className="check-card">
                <input type="checkbox" checked={presearch.require_public_email} onChange={e => setPre('require_public_email',e.target.checked)} />
                <span><strong>Public email route signal</strong><small>Add public professional contact language to discovery prompts.</small></span>
              </label>
            </div>
          </div>}

          <div className="search-plan-preview">
            <div>
              <span className="kicker">Generated search plan</span>
              <strong>{routesUsed.toLocaleString()} diversified routes ready</strong>
              <small>
                {Math.max(1,presearch.countries.length)} country × {Math.max(1,presearch.genres.length)} genre × {genderRouteCount} gender × {Math.max(1,presearch.positions.length)} position × {Math.max(1,presearch.activity_signals.length)} activity × 4 phrasing patterns
              </small>
            </div>
            <div className="route-example">
              <span>Example route</span>
              <code>{[
                presearch.countries[0] || 'Canada',
                presearch.genres[0] || 'Historical Fiction',
                presearch.genders.includes('any') ? '' : (presearch.genders[0] || ''),
                presearch.positions[0] || 'emerging author',
                presearch.activity_signals[0] || 'active 2026',
                presearch.source_types[0] || 'writers associations'
              ].filter(Boolean).join(' · ')}</code>
            </div>
          </div>

          <div className="field scout-instructions">
            <label>Additional instructions <span>optional</span></label>
            <textarea
              rows="3"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Example: avoid celebrity authors, prefer authors with a current book or project, exclude publisher-only contacts"
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
            <div className="compose-hint">Routes are rotated, deduplicated and reused intelligently during the Scout.</div>
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
          {!jobs.length ? <Empty title="No Scout jobs" body="Build a search plan and start one above." /> :
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
  ['messages','Letterdesk','✉'],
  ['connections','Connections','↗'],
]

function AppCore() {
  const [keyValue, setKeyValue] = useState(() => localStorage.getItem('authorScoutSession') || '')
  const [session, setSession] = useState(null)
  const [checking, setChecking] = useState(Boolean(keyValue))
  const [loginError, setLoginError] = useState('')
  const [loginStatus, setLoginStatus] = useState('')
  const [tab, setTab] = useState(() => new URLSearchParams(window.location.search).get('tab') === 'messages' ? 'messages' : 'dashboard')

  const verify = useCallback(async (rawKey) => {
    const key=String(rawKey || '').replace(/\s+/g,'').trim()
    if (!key) {
      setLoginError('Paste a valid Author Scout access key.')
      return
    }
    setChecking(true); setLoginError(''); setLoginStatus('Opening your workspace…')
    try {
      const s = await request('/api/v1/session', key)
      localStorage.setItem('authorScoutSession', key)
      setKeyValue(key)
      setSession(s)
      setLoginStatus('')
    } catch(e) {
      localStorage.removeItem('authorScoutSession')
      setKeyValue('')
      setSession(null)
      setLoginError(e?.message || 'That access key could not be verified.')
      setLoginStatus('')
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
      setLoginStatus('Starting your Author Scout workspace…')
      await waitForBackend()
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
      // Clear only the old Author Scout app session. Better Auth will establish the new Google identity.
      localStorage.removeItem('authorScoutSession')
      setKeyValue('')
      const result=await authClient.signIn.social({
        provider:'google',
        callbackURL:window.location.origin
      })
      if (result?.error) throw new Error(result.error.message || 'Google sign-in failed')
      // Most social sign-ins redirect. If a session is returned directly, exchange it now.
      if (sessionTokenFrom(result)) await exchangeManagedAuth(result)
    } catch(e) {
      setLoginError(e?.message || 'Google sign-in failed.')
      setLoginStatus('')
      setChecking(false)
    }
  }, [exchangeManagedAuth])

  const startForgotPassword = useCallback(async (emailValue) => {
    const email=String(emailValue || '').trim().toLowerCase()
    if (!email) { setLoginError('Enter your email address.'); return false }
    setChecking(true)
    setLoginError('')
    setLoginStatus('Sending reset link…')
    try {
      const result=await authClient.requestPasswordReset({
        email,
        redirectTo: window.location.origin + '/reset-password'
      })
      if (result?.error) throw new Error(result.error.message || 'Could not send reset link')
      return true
    } catch(e) {
      setLoginError(e?.message || 'Could not send reset link. Please try again.')
      return false
    } finally {
      setChecking(false)
      setLoginStatus('')
    }
  }, [])


  useEffect(() => {
    let cancelled=false
    const boot=async () => {
      const params=new URLSearchParams(window.location.search)
      const incoming=params.get('session')
      const authError=params.get('auth_error')

      // Backend Google login returns a fresh signed Author Scout session.
      if (incoming) {
        window.history.replaceState({},document.title,window.location.pathname)
        await verify(incoming)
        return
      }
      if (authError) {
        localStorage.removeItem('authorScoutSession')
        setKeyValue('')
        setLoginError('Google sign-in was cancelled or could not be completed.')
        window.history.replaceState({},document.title,window.location.pathname)
        return
      }

      // Email/password login may leave a valid managed Neon Auth session.
      // Prefer that fresh identity before any stale Author Scout local session.
      try {
        const current=await authClient.getSession()
        if (!cancelled && !current?.error && sessionTokenFrom(current)) {
          try {
            await exchangeManagedAuth(current)
            return
          } catch {
            // Continue to stored Author Scout session if managed exchange fails.
          }
        }
      } catch {}

      const stored=localStorage.getItem('authorScoutSession') || ''
      if (!cancelled && stored) {
        await verify(stored)
      } else if (!cancelled) {
        setChecking(false)
      }
    }
    boot()
    return () => { cancelled=true }
  }, [])

  const logout = async () => {
    localStorage.removeItem('authorScoutSession')
    try { await authClient.signOut() } catch {}
    setKeyValue(''); setSession(null); setTab('dashboard')
  }

  const resetParams = new URLSearchParams(window.location.search)
  const isResetPage = window.location.pathname === '/reset-password' || Boolean(resetParams.get('token')) || Boolean(resetParams.get('error'))
  if (!session && isResetPage) return <ResetPasswordScreen
    token={resetParams.get('token') || ''}
    errorCode={resetParams.get('error') || ''}
    onDone={() => {
      window.history.replaceState({}, document.title, '/')
      setLoginError('')
      setLoginStatus('')
      setKeyValue('')
      setSession(null)
    }}
  />

  if (!session) return <Login
    onLegacyLogin={verify}
    onGoogle={startManagedGoogle}
    onEmail={startEmailAuth}
    onForgot={startForgotPassword}
    busy={checking}
    error={loginError}
    status={loginStatus}
  />

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
            <Letterdesk keyValue={keyValue} active={tab === 'messages'} request={request} apiBase={API_BASE} />
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
