import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { PageHead } from '../../components/ui'
import { ApiError, api } from '../../services/api'
import { useAuth } from '../auth/AuthContext'

type Values = {
  notify_sms_enabled: boolean; notify_email_enabled: boolean
  sms_on_cancellation: boolean; sms_on_reassignment: boolean; compliance_expiry_warning_days: number
}
type Flag = 'notify_sms_enabled' | 'notify_email_enabled' | 'sms_on_cancellation' | 'sms_on_reassignment'

const CHANNELS: { key: Flag; title: string; help: string }[] = [
  { key: 'notify_sms_enabled', title: 'SMS', help: 'Text messages to employees and drivers.' },
  { key: 'notify_email_enabled', title: 'Email', help: 'Emails to employees and drivers (employees must have an email; drivers use their own email or their login email).' },
]
const EVENTS: { key: Flag; title: string; help: string }[] = [
  { key: 'sms_on_cancellation', title: 'When an assigned trip is cancelled', help: 'Notify the driver and every employee.' },
  { key: 'sms_on_reassignment', title: 'When the driver or vehicle changes', help: 'Notify the new and previous driver, and the employees.' },
]

function Toggle({ checked, disabled, onChange, title, help }: { checked: boolean; disabled: boolean; onChange: (v: boolean) => void; title: string; help: ReactNode }) {
  return (
    <label style={{ display: 'flex', gap: 12, alignItems: 'flex-start', padding: '12px 0', borderTop: '1px solid var(--border)', cursor: 'pointer' }}>
      <input type="checkbox" style={{ marginTop: 4, width: 18, height: 18, accentColor: 'var(--brand-600)' }} checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span><strong>{title}</strong><br /><span className="muted">{help}</span></span>
    </label>
  )
}

function WarningDays({ value, disabled, onSave }: { value?: number; disabled: boolean; onSave: (n: number) => void }) {
  const [v, setV] = useState(String(value ?? 30))
  const n = Number(v)
  const valid = Number.isInteger(n) && n >= 1 && n <= 365
  return (
    <div className="field" style={{ marginBottom: 0 }}>
      <label htmlFor="warn-days">"About to expire" window (days)</label>
      <div style={{ display: 'flex', gap: 8 }}>
        <input id="warn-days" className="input" type="number" min={1} max={365} value={v} onChange={(e) => setV(e.target.value)} style={{ maxWidth: 140 }} />
        <button className="btn btn-primary" disabled={disabled || !valid || n === value} onClick={() => onSave(n)}>Save</button>
      </div>
      <span className="muted" style={{ fontSize: 12.5 }}>Documents expiring within this many days are flagged. Default 30.</span>
      {!valid && <span className="error-text" role="alert">Enter a whole number from 1 to 365</span>}
    </div>
  )
}

export function SettingsPage() {
  const { user } = useAuth()
  const isSuper = user?.role === 'super_admin'
  const qc = useQueryClient()
  const [vendor, setVendor] = useState('') // Super Admin: '' = global default
  const [error, setError] = useState('')
  const qs = vendor ? `?vendor_id=${vendor}` : ''
  const { data } = useQuery({ queryKey: ['settings', vendor], queryFn: () => api<{ values: Values }>(`/settings${qs}`) })
  const { data: vendors } = useQuery({ queryKey: ['vendors', 'all'], enabled: isSuper, queryFn: () => api<{ items: { id: number; name: string }[] }>('/vendors?limit=200').then((r) => r.items) })
  const save = useMutation({
    mutationFn: (patch: Partial<Values>) => api('/settings', { method: 'PUT', body: JSON.stringify({ ...patch, vendor_id: vendor ? Number(vendor) : null }) }),
    onSuccess: () => { setError(''); qc.invalidateQueries({ queryKey: ['settings'] }) },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Could not save'),
  })
  const sms = Boolean(data?.values.notify_sms_enabled)
  const email = Boolean(data?.values.notify_email_enabled)
  const summary = !data ? '' : sms && email ? 'by SMS and by Email' : sms ? 'by SMS only' : email ? 'by Email only' : 'by nobody'
  return (
    <>
      <PageHead title="Settings" subtitle={isSuper ? 'Platform defaults, with optional per-vendor overrides.' : 'Settings for your vendor.'} />
      {isSuper && (
        <div className="field" style={{ maxWidth: 680 }}>
          <label htmlFor="scope">Applies to</label>
          <select id="scope" className="input" value={vendor} onChange={(e) => setVendor(e.target.value)}>
            <option value="">All vendors (default)</option>{vendors?.map((v) => <option key={v.id} value={v.id}>{v.name} only</option>)}
          </select>
        </div>
      )}
      {error && <div className="alert alert-danger" role="alert" style={{ maxWidth: 680 }}>{error}</div>}

      <div className="card" style={{ maxWidth: 680 }}>
        <h2 style={{ marginBottom: 4 }}>How employees and drivers are notified</h2>
        <p className="muted" style={{ marginTop: 0 }}>Switch on SMS, Email, or both. Both on: everyone is notified both ways. One on: only that one is used.</p>
        {CHANNELS.map((o) => (
          <Toggle key={o.key} title={o.title} help={o.help} checked={Boolean(data?.values[o.key])} disabled={!data || save.isPending} onChange={(v) => save.mutate({ [o.key]: v })} />
        ))}
        {data && (
          <div className={`alert ${!sms && !email ? 'alert-warning' : 'alert-success'}`} style={{ marginTop: 8, marginBottom: 0 }} role="status">
            {!sms && !email
              ? <><strong>Both are off.</strong> No one will be notified about trips, so employees will not receive their OTP. The Operator who requested a trip can still read OTPs out to them.</>
              : <>Trip notifications currently go out <strong>{summary}</strong>.</>}
          </div>
        )}
        <p className="muted" style={{ marginBottom: 0, fontSize: 12.5, marginTop: 10 }}>Account emails (new user, password reset) are always sent and are not affected by these switches.</p>
      </div>

      <div className="card" style={{ maxWidth: 680, marginTop: 16 }}>
        <h2 style={{ marginBottom: 4 }}>When to notify</h2>
        <p className="muted" style={{ marginTop: 0 }}>Uses the channels switched on above. The confirmation when a trip is assigned (with each employee's OTP) is always sent.</p>
        {EVENTS.map((o) => (
          <Toggle key={o.key} title={o.title} help={o.help} checked={Boolean(data?.values[o.key])} disabled={!data || save.isPending} onChange={(v) => save.mutate({ [o.key]: v })} />
        ))}
      </div>

      <div className="card" style={{ maxWidth: 680, marginTop: 16 }}>
        <h2 style={{ marginBottom: 12 }}>Compliance</h2>
        <WarningDays key={`${vendor}-${data?.values.compliance_expiry_warning_days}`} value={data?.values.compliance_expiry_warning_days} disabled={!data || save.isPending}
          onSave={(n) => save.mutate({ compliance_expiry_warning_days: n })} />
      </div>
    </>
  )
}
