import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { useState } from 'react'
import { PageHead } from '../../components/ui'
import { ApiError, api, download } from '../../services/api'
import { useAuth } from '../auth/AuthContext'

interface Report {
  title: string; period: string; truncated: boolean; summary: Record<string, number | string>
  columns: { key: string; label: string }[]; rows: Record<string, string | number>[]
}

export function ReportsPage() {
  const { user } = useAuth()
  const { data: catalog } = useQuery({ queryKey: ['reports', 'catalog'], queryFn: () => api<{ items: { key: string; title: string; description: string }[] }>('/reports').then((r) => r.items) })
  const { data: vendors } = useQuery({ queryKey: ['vendors', 'all'], enabled: user!.role === 'super_admin', queryFn: () => api<{ items: { id: number; name: string }[] }>('/vendors?limit=200').then((r) => r.items) })
  const [key, setKey] = useState('trips')
  const [f, setF] = useState<Record<string, string>>({ range: 'this_month' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (k: string) => (v: string) => setF((s) => ({ ...s, [k]: v }))

  const qs = new URLSearchParams()
  Object.entries(f).forEach(([k, v]) => v && qs.set(k, v))
  const ready = f.range !== 'custom' || (!!f.date_from && !!f.date_to)
  const { data, isLoading, isError, error: loadErr } = useQuery({
    queryKey: ['report', key, qs.toString()], enabled: ready,
    queryFn: () => api<Report>(`/reports/${key}?${qs}`),
  })

  const exportXlsx = async () => {
    setBusy(true); setError('')
    try { await download(`/reports/${key}?${qs}&format=xlsx`, `yaan-${key}.xlsx`) }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Download failed') }
    finally { setBusy(false) }
  }

  return (
    <>
      <PageHead title="Reports" subtitle="Review on screen, or download as an Excel (.xlsx) file."
        actions={<button className="btn btn-primary" onClick={exportXlsx} disabled={busy || !data}><Download size={16} /> {busy ? 'Preparing…' : 'Download Excel'}</button>} />
      <div className="filters" role="group" aria-label="Report filters">
        <select className="input" aria-label="Report" value={key} onChange={(e) => setKey(e.target.value)} style={{ minWidth: 220 }}>
          {catalog?.map((r) => <option key={r.key} value={r.key}>{r.title}</option>)}
        </select>
        <select className="input" aria-label="Period" value={f.range} onChange={(e) => set('range')(e.target.value)}>
          <option value="today">Today</option><option value="tomorrow">Tomorrow</option><option value="this_week">This week</option>
          <option value="this_month">This month</option><option value="custom">Custom range</option>
        </select>
        {f.range === 'custom' && <>
          <input className="input" type="date" aria-label="From" value={f.date_from ?? ''} onChange={(e) => set('date_from')(e.target.value)} />
          <input className="input" type="date" aria-label="To" value={f.date_to ?? ''} onChange={(e) => set('date_to')(e.target.value)} />
        </>}
        {user!.role === 'super_admin' && (
          <select className="input" aria-label="Vendor" value={f.vendor_id ?? ''} onChange={(e) => set('vendor_id')(e.target.value)}>
            <option value="">All vendors</option>{vendors?.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        )}
      </div>
      {catalog && <p className="muted" style={{ marginTop: -6 }}>{catalog.find((r) => r.key === key)?.description}</p>}
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {!ready && <div className="alert alert-warning">Choose a start and end date for the custom range.</div>}
      {isError && <div className="alert alert-danger" role="alert">{loadErr instanceof ApiError ? loadErr.message : 'Could not load the report.'}</div>}
      {isLoading && <p className="muted">Loading…</p>}
      {data && (
        <div className="card">
          <div className="chart-head"><div><h2>{data.title}</h2><div className="sub muted">{data.period}</div></div></div>
          <div className="kpis" style={{ marginBottom: 12 }}>
            {Object.entries(data.summary).map(([k, v]) => <div className="kpi" key={k}><div className="label">{k}</div><div className="value" style={{ fontSize: 22 }}>{v}</div></div>)}
          </div>
          {data.truncated && <div className="alert alert-warning">Showing the first 5,000 rows. Narrow the period to see the rest.</div>}
          <div className="table-wrap">
            <table className="table">
              <thead><tr>{data.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
              <tbody>
                {data.rows.map((r, i) => <tr key={i}>{data.columns.map((c) => <td key={c.key}>{r[c.key] ?? ''}</td>)}</tr>)}
                {!data.rows.length && <tr><td colSpan={data.columns.length} className="muted" style={{ textAlign: 'center', padding: 32 }}>No data for this period.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}
