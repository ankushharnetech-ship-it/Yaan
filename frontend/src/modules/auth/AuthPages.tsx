import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Brand } from '../../components/AppLayout'
import { Field, TextInput } from '../../components/ui'
import { ApiError, api } from '../../services/api'
import { homeFor, useAuth, type Me } from './AuthContext'

const POINTS: [string, string][] = [
  ['Always the right driver and vehicle', 'Availability checks keep a 30-minute gap between trips and match seats to passengers.'],
  ['Safer rides, planned in', 'An escort seat is reserved automatically whenever a female employee travels.'],
  ['Everyone stays informed', 'Drivers and employees get an SMS the moment a trip is booked, changed or cancelled.'],
]

function AuthShell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="auth-wrap">
      <div className="auth-split">
        <aside className="auth-hero" aria-hidden>
          <Brand />
          <h2>Move your people, <span>on time, every time.</span></h2>
          <p>One place to plan trips, assign drivers and vehicles, and keep every journey on track.</p>
          <ul className="auth-points">
            {POINTS.map(([t, d]) => (
              <li key={t}><span className="dot"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5L20 7" /></svg></span><span><strong style={{ color: '#fff' }}>{t}</strong><br />{d}</span></li>
            ))}
          </ul>
        </aside>
        <main className="auth-panel">
          <div className="card auth-card">
            <div className="auth-strip"><Brand /></div>
            <h1>{title}</h1>
            {subtitle && <p className="muted" style={{ marginTop: 4 }}>{subtitle}</p>}
            <div style={{ marginTop: 20 }}>{children}</div>
          </div>
        </main>
      </div>
    </div>
  )
}

function useSubmit<T>(fn: () => Promise<T>) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [fields, setFields] = useState<Record<string, string>>({})
  const run = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setError(''); setFields({})
    try { return await fn() } catch (err) {
      if (err instanceof ApiError) {
        setFields(err.fieldErrors)
        if (!Object.keys(err.fieldErrors).length) setError(err.message)
      } else setError('Something went wrong. Please try again.')
    } finally { setBusy(false) }
  }
  return { busy, error, fields, run }
}

export function LoginPage() {
  const { user, login } = useAuth()
  const nav = useNavigate()
  const loc = useLocation() as { state?: { from?: string } }
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const { busy, error, run } = useSubmit(async () => {
    const u: Me = await login(username, password)
    nav(u.must_change_password ? '/change-password' : loc.state?.from ?? homeFor(u.role), { replace: true })
  })
  if (user && !user.must_change_password) return <Navigate to={homeFor(user.role)} replace />
  return (
    <AuthShell title="Welcome back" subtitle="Sign in to manage employee transport.">
      <form onSubmit={run}>
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        <Field label="Username"><TextInput value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required /></Field>
        <Field label="Password"><TextInput type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></Field>
        <button className="btn btn-primary" style={{ width: '100%' }} disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <p style={{ textAlign: 'center', marginBottom: 0 }}><Link to="/forgot-password">Forgot password?</Link></p>
      </form>
    </AuthShell>
  )
}

export function ForgotPasswordPage() {
  const [identifier, setIdentifier] = useState('')
  const [done, setDone] = useState(false)
  const { busy, error, run } = useSubmit(async () => {
    await api('/auth/forgot-password', { method: 'POST', body: JSON.stringify({ identifier }) })
    setDone(true)
  })
  return (
    <AuthShell title="Reset your password" subtitle="Enter your username or email and we'll send a reset link.">
      {done ? (
        <>
          <div className="alert alert-success">If an account matches, a reset link has been emailed. It expires in 60 minutes.</div>
          <Link to="/login">Back to sign in</Link>
        </>
      ) : (
        <form onSubmit={run}>
          {error && <div className="alert alert-danger" role="alert">{error}</div>}
          <Field label="Username or email"><TextInput value={identifier} onChange={(e) => setIdentifier(e.target.value)} autoFocus required /></Field>
          <button className="btn btn-primary" style={{ width: '100%' }} disabled={busy}>{busy ? 'Sending…' : 'Send reset link'}</button>
          <p style={{ textAlign: 'center', marginBottom: 0 }}><Link to="/login">Back to sign in</Link></p>
        </form>
      )}
    </AuthShell>
  )
}

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [done, setDone] = useState(false)
  const [mismatch, setMismatch] = useState('')
  const { busy, error, fields, run } = useSubmit(async () => {
    if (pw !== pw2) { setMismatch('Passwords do not match'); return }
    setMismatch('')
    await api('/auth/reset-password', { method: 'POST', body: JSON.stringify({ token, new_password: pw }) })
    setDone(true)
  })
  if (!token) return <AuthShell title="Link not valid"><p>This link is missing its token. Request a new one.</p><Link to="/forgot-password">Forgot password</Link></AuthShell>
  return (
    <AuthShell title="Set your password" subtitle="Use at least 10 characters with letters and numbers.">
      {done ? (
        <>
          <div className="alert alert-success">Password saved. You can now sign in.</div>
          <Link className="btn btn-primary" to="/login" style={{ width: '100%' }}>Go to sign in</Link>
        </>
      ) : (
        <form onSubmit={run}>
          {error && <div className="alert alert-danger" role="alert">{error} <Link to="/forgot-password">Request a new link</Link></div>}
          <Field label="New password" error={fields.new_password}><TextInput type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" required /></Field>
          <Field label="Confirm password" error={mismatch}><TextInput type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" required /></Field>
          <button className="btn btn-primary" style={{ width: '100%' }} disabled={busy}>{busy ? 'Saving…' : 'Save password'}</button>
        </form>
      )}
    </AuthShell>
  )
}

export function ChangePasswordPage() {
  const { user, applySession, logout } = useAuth()
  const nav = useNavigate()
  const [cur, setCur] = useState('')
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [mismatch, setMismatch] = useState('')
  const { busy, error, fields, run } = useSubmit(async () => {
    if (pw !== pw2) { setMismatch('Passwords do not match'); return }
    setMismatch('')
    const r = await api<{ access_token: string; user: Me }>('/auth/change-password', {
      method: 'POST', body: JSON.stringify({ current_password: cur, new_password: pw }),
    })
    applySession(r)
    nav(homeFor(r.user.role), { replace: true })
  })
  if (!user) return <Navigate to="/login" replace />
  return (
    <AuthShell
      title={user.must_change_password ? 'Choose a new password' : 'Change password'}
      subtitle={user.must_change_password ? 'Your temporary password must be replaced before you continue.' : undefined}
    >
      <form onSubmit={run}>
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        <Field label={user.must_change_password ? 'Temporary password' : 'Current password'} error={fields.current_password}>
          <TextInput type="password" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" required />
        </Field>
        <Field label="New password" error={fields.new_password} hint="At least 10 characters, with letters and numbers">
          <TextInput type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" required />
        </Field>
        <Field label="Confirm new password" error={mismatch}>
          <TextInput type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" required />
        </Field>
        <button className="btn btn-primary" style={{ width: '100%' }} disabled={busy}>{busy ? 'Saving…' : 'Update password'}</button>
        <p style={{ textAlign: 'center', marginBottom: 0 }}><a href="#" onClick={(e) => { e.preventDefault(); logout() }}>Sign out</a></p>
      </form>
    </AuthShell>
  )
}
