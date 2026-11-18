import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { PageHead } from '../../components/ui'
import { api } from '../../services/api'
import { EmailTable, SmsTable, type EmailRow, type SmsRow } from './SmsComponents'

/** Everything YAAN has sent for trips, by SMS and by Email. OTPs are always masked here. */
export function SmsLogsPage() {
  const [channel, setChannel] = useState<'sms' | 'email'>('sms')
  const [status, setStatus] = useState('')
  const [type, setType] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(0)
  const limit = 20
  const params = new URLSearchParams({ limit: String(limit), offset: String(page * limit) })
  if (status) params.set('status', status)
  if (type) params.set('recipient_type', type)
  if (q) params.set('q', q)
  const path = channel === 'sms' ? 'sms-logs' : 'email-logs'
  const { data, isLoading, isError } = useQuery({
    queryKey: [channel, params.toString()], refetchInterval: 15_000,
    queryFn: () => api<{ total: number; items: (SmsRow | EmailRow)[] }>(`/${path}?${params}`),
  })
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / limit))
  const reset = () => setPage(0)
  return (
    <>
      <PageHead title="Notifications" subtitle="Every trip message YAAN sends, with its delivery status. OTPs are never shown here." />
      <div className="card">
        <div className="seg-tabs" role="tablist" style={{ marginBottom: 14 }}>
          {(['sms', 'email'] as const).map((c) => (
            <button key={c} role="tab" aria-selected={channel === c} className={channel === c ? 'on' : ''} onClick={() => { setChannel(c); setStatus(''); reset() }}>{c === 'sms' ? 'SMS' : 'Email'}</button>
          ))}
        </div>
        <div className="toolbar">
          <input className="input" style={{ flex: 1 }} placeholder={channel === 'sms' ? 'Search name or phone' : 'Search name or email'} aria-label="Search" value={q} onChange={(e) => { setQ(e.target.value); reset() }} />
          <select className="input" aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); reset() }}>
            <option value="">Any status</option><option value="pending">Pending</option><option value="sent">Sent</option>
            {channel === 'sms' && <option value="delivered">Delivered</option>}<option value="failed">Failed</option>
          </select>
          <select className="input" aria-label="Recipient" value={type} onChange={(e) => { setType(e.target.value); reset() }}>
            <option value="">Everyone</option><option value="driver">Drivers</option><option value="employee">Passengers</option>
          </select>
        </div>
        {isLoading ? <p className="muted">Loading…</p> : isError ? <div className="alert alert-danger">Could not load messages.</div>
          : channel === 'sms' ? <SmsTable rows={data!.items as SmsRow[]} showTrip /> : <EmailTable rows={data!.items as EmailRow[]} showTrip />}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14, flexWrap: 'wrap', gap: 8 }}>
          <span className="muted">{data?.total ?? 0} messages</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="muted">Page {page + 1} of {pages}</span>
            <button className="btn" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </div>
      </div>
    </>
  )
}
