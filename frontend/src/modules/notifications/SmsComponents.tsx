import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '../../components/ui'
import { ApiError, api } from '../../services/api'
import { useAuth } from '../auth/AuthContext'
import { fmtDateTime } from '../trips/shared'

export interface SmsRow {
  id: number; trip_id: number | null; recipient_type: 'driver' | 'employee'; recipient_name: string | null; phone: string
  template: string; body: string; status: 'pending' | 'sent' | 'delivered' | 'failed'; failure_reason: string | null
  attempts: number; created_at: string; sent_at: string | null; delivered_at: string | null
}

const TONE = { pending: 'neutral', sent: 'info', delivered: 'success', failed: 'danger' } as const
const LABEL = { pending: 'Pending', sent: 'Sent', delivered: 'Delivered', failed: 'Failed' } as const

export const SmsBadge = ({ status }: { status: string | null | undefined }) =>
  status ? <Badge tone={TONE[status as keyof typeof TONE] ?? 'neutral'}>{LABEL[status as keyof typeof LABEL] ?? status}</Badge> : <span className="muted">—</span>

/** Table of SMS messages with a Retry button for failed ones. Used on the trip page and the SMS Logs page. */
export function SmsTable({ rows, showTrip }: { rows: SmsRow[]; showTrip?: boolean }) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const canRetry = user?.role !== 'driver'
  const retry = useMutation({
    mutationFn: (id: number) => api(`/sms-logs/${id}/retry`, { method: 'POST' }),
    onSuccess: () => { setError(''); setTimeout(() => qc.invalidateQueries({ queryKey: ['sms'] }), 800) },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Could not retry'),
  })
  return (
    <>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Time</th>{showTrip && <th>Trip</th>}<th>To</th><th>Phone</th><th>Message</th><th>Status</th>{canRetry && <th />}</tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td style={{ whiteSpace: 'nowrap' }}>{fmtDateTime(r.created_at)}</td>
                {showTrip && <td>{r.trip_id ?? '—'}</td>}
                <td>{r.recipient_name}<div className="muted" style={{ fontSize: 12 }}>{r.recipient_type === 'driver' ? 'Driver' : 'Passenger'}</div></td>
                <td style={{ whiteSpace: 'nowrap' }}>{r.phone}</td>
                <td style={{ maxWidth: 380, fontSize: 13 }}>{r.body}</td>
                <td><SmsBadge status={r.status} />{r.failure_reason && <div className="reason" style={{ maxWidth: 220 }}>{r.failure_reason}</div>}</td>
                {canRetry && <td>{r.status === 'failed' && <button className="btn" onClick={() => retry.mutate(r.id)} disabled={retry.isPending} aria-label="Retry SMS"><RotateCcw size={14} /> Retry</button>}</td>}
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={7} className="muted" style={{ textAlign: 'center', padding: 28 }}>No messages.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  )
}

export interface EmailRow {
  id: number; trip_id: number | null; recipient_type: 'driver' | 'employee'; recipient_name: string | null; email: string; subject: string | null
  body: string | null; status: 'pending' | 'sent' | 'failed'; failure_reason: string | null; attempts: number; created_at: string; sent_at: string | null
}

export function EmailTable({ rows, showTrip }: { rows: EmailRow[]; showTrip?: boolean }) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const canRetry = user?.role !== 'driver'
  const retry = useMutation({
    mutationFn: (id: number) => api(`/email-logs/${id}/retry`, { method: 'POST' }),
    onSuccess: () => { setError(''); setTimeout(() => qc.invalidateQueries({ queryKey: ['email'] }), 800) },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Could not retry'),
  })
  return (
    <>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Time</th>{showTrip && <th>Trip</th>}<th>To</th><th>Email</th><th>Subject &amp; message</th><th>Status</th>{canRetry && <th />}</tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td style={{ whiteSpace: 'nowrap' }}>{fmtDateTime(r.created_at)}</td>
                {showTrip && <td>{r.trip_id ?? '—'}</td>}
                <td>{r.recipient_name}<div className="muted" style={{ fontSize: 12 }}>{r.recipient_type === 'driver' ? 'Driver' : 'Passenger'}</div></td>
                <td style={{ whiteSpace: 'nowrap' }}>{r.email}</td>
                <td style={{ maxWidth: 380, fontSize: 13 }}><strong>{r.subject}</strong><div>{r.body}</div></td>
                <td><SmsBadge status={r.status} />{r.failure_reason && <div className="reason" style={{ maxWidth: 220 }}>{r.failure_reason}</div>}</td>
                {canRetry && <td>{r.status === 'failed' && <button className="btn" onClick={() => retry.mutate(r.id)} disabled={retry.isPending} aria-label="Retry email"><RotateCcw size={14} /> Retry</button>}</td>}
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={7} className="muted" style={{ textAlign: 'center', padding: 28 }}>No emails.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  )
}

/** Everything sent about one trip, over whichever channels are switched on (the Email part appears only if any were sent). */
export function TripNotifications({ tripId }: { tripId: number }) {
  const sms = useQuery({ queryKey: ['sms', 'trip', tripId], queryFn: () => api<{ items: SmsRow[] }>(`/sms-logs?trip_id=${tripId}&limit=100`) })
  const mail = useQuery({ queryKey: ['email', 'trip', tripId], queryFn: () => api<{ items: EmailRow[] }>(`/email-logs?trip_id=${tripId}&limit=100`) })
  const s = sms.data?.items ?? []
  const e = mail.data?.items ?? []
  if (!s.length && !e.length) return <p className="muted" style={{ margin: 0 }}>Nothing has been sent for this trip. Notifications may be switched off in Settings.</p>
  return (
    <div style={{ display: 'grid', gap: 18 }}>
      {s.length > 0 && <div><h3 style={{ fontSize: 14, margin: '0 0 8px' }}>SMS</h3><SmsTable rows={s} /></div>}
      {e.length > 0 && <div><h3 style={{ fontSize: 14, margin: '0 0 8px' }}>Email</h3><EmailTable rows={e} /></div>}
    </div>
  )
}
