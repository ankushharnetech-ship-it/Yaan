import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, PageHead } from '../../components/ui'
import { api } from '../../services/api'
import { lookupOptions, useLookups } from '../../services/lookups'
import { useAuth } from '../auth/AuthContext'
import { fmtDate, fmtTime, TripStatusBadge, type Trip } from '../trips/shared'
import { BarList, ChartCard, Columns, Meter, Trend } from './charts'

const RANGES = [['today', 'Today'], ['tomorrow', 'Tomorrow'], ['this_week', 'This week'], ['this_month', 'This month'], ['custom', 'Custom range']] as const
const STATUS_LABEL: Record<string, string> = { scheduled: 'Awaiting assignment', assigned: 'Assigned', accepted: 'Accepted', started: 'Ongoing', completed: 'Completed', cancelled: 'Cancelled' }
const REASON: Record<string, string> = {
  not_started: 'Not started', running_late: 'Running late', awaiting_acceptance: 'Awaiting acceptance', unassigned: 'Needs assignment', not_dropped: 'Employee not dropped',
  driver_inactive: 'Driver inactive', vehicle_inactive: 'Vehicle inactive', capacity_conflict: 'Capacity conflict', sms_failed: 'SMS failed',
}

interface Summary {
  range_label: string
  cards: Record<'total_trips' | 'upcoming' | 'assigned' | 'pending_assignment' | 'accepted' | 'ongoing' | 'completed' | 'cancelled' | 'total_passengers' | 'capacity_utilization' | 'escort_trips' | 'sms_sent' | 'sms_failed' | 'sms_pending', number>
  resources_now: Record<'drivers_active' | 'drivers_available' | 'drivers_in_use' | 'vehicles_active' | 'vehicles_available' | 'vehicles_in_use', number>
}
interface Breakdown {
  status: { status: string; count: number }[]; hourly: { hour: number; count: number }[]; daily: { date: string; count: number }[]
  by_shift: { name: string; count: number }[]; by_customer: { name: string; count: number }[]; by_vendor: { name: string; count: number }[]
  completed_vs_planned: { planned: number; completed: number; completion_rate: number }
  punctuality: { started: number; late: number; on_time: number; avg_delay_minutes: number; grace_minutes: number; on_time_rate: number }
}

function Kpi({ label, value, sub, to, warn }: { label: string; value: string | number; sub?: string; to?: string; warn?: boolean }) {
  const body = <><div className="label">{label}</div><div className="value">{value}</div>{sub && <div className="sub">{sub}</div>}</>
  return to ? <Link to={to} className={`kpi link ${warn ? 'warn' : ''}`}>{body}</Link> : <div className={`kpi ${warn ? 'warn' : ''}`}>{body}</div>
}

export function DashboardPage() {
  const { user } = useAuth()
  const { data: lk } = useLookups()
  const [f, setF] = useState<Record<string, string>>({ range: 'today' })
  const [tab, setTab] = useState<'awaiting_assignment' | 'upcoming' | 'ongoing' | 'awaiting_acceptance' | 'recently_completed'>(user!.role === 'operator' ? 'upcoming' : 'awaiting_assignment')
  const set = (k: string) => (v: string) => setF((s) => ({ ...s, [k]: v, ...(k === 'customer_id' ? { site_id: '', shift_id: '' } : {}), ...(k === 'vendor_id' ? { customer_id: '', site_id: '', shift_id: '' } : {}) }))

  const qs = new URLSearchParams()
  Object.entries(f).forEach(([k, v]) => v && qs.set(k, v))
  const ready = f.range !== 'custom' || (!!f.date_from && !!f.date_to)
  const live = { enabled: ready, refetchInterval: 30_000 }
  const q = qs.toString()
  const summary = useQuery({ queryKey: ['dash', 'summary', q], queryFn: () => api<Summary>(`/dashboard/summary?${q}`), ...live })
  const breakdown = useQuery({ queryKey: ['dash', 'breakdown', q], queryFn: () => api<Breakdown>(`/dashboard/status-breakdown?${q}`), ...live })
  const util = useQuery({ queryKey: ['dash', 'util', q], queryFn: () => api<{ drivers: { name: string; trips: number; booked_hours: number }[]; vehicles: { vehicle_number: string; trips: number; seat_utilization: number; capacity: number }[] }>(`/dashboard/resource-utilization?${q}`), ...live })
  const lists = useQuery({ queryKey: ['dash', 'lists', q], queryFn: () => api<Record<typeof tab, Trip[]>>(`/dashboard/upcoming?${q}`), ...live })
  const exc = useQuery({ queryKey: ['dash', 'exc', q], queryFn: () => api<{ items: { trip_id: number; code: string; reason: string; message: string }[] }>(`/dashboard/exceptions?${q}`), ...live })
  const sms = useQuery({ queryKey: ['dash', 'sms', q], queryFn: () => api<{ total: number; by_status: Record<string, number>; success_rate: number }>(`/dashboard/notifications?${q}`), ...live })

  const { data: vendors } = useQuery({ queryKey: ['vendors', 'all'], enabled: user!.role === 'super_admin', queryFn: () => api<{ items: { id: number; name: string }[] }>('/vendors?limit=200').then((r) => r.items) })
  const cq = f.vendor_id ? `&vendor_id=${f.vendor_id}` : ''
  const { data: customers } = useQuery({ queryKey: ['customers', 'dash', f.vendor_id], queryFn: () => api<{ items: { id: number; name: string }[] }>(`/customers?limit=200${cq}`).then((r) => r.items) })
  const { data: sites } = useQuery({ queryKey: ['sites', 'dash', f.customer_id], enabled: !!f.customer_id, queryFn: () => api<{ items: { id: number; name: string }[] }>(`/sites?customer_id=${f.customer_id}`).then((r) => r.items) })
  const { data: shifts } = useQuery({ queryKey: ['shifts', 'dash', f.customer_id], enabled: !!f.customer_id, queryFn: () => api<{ items: { id: number; name: string }[] }>(`/shifts?customer_id=${f.customer_id}`).then((r) => r.items) })

  const c = summary.data?.cards
  const r = summary.data?.resources_now
  const nExc = exc.data?.items.length ?? 0
  const sel = (label: string, key: string, opts?: { value: string | number; label: string }[], disabled = false) => (
    <select className="input" aria-label={label} value={f[key] ?? ''} onChange={(e) => set(key)(e.target.value)} disabled={disabled}>
      <option value="">{label}</option>{opts?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
  const tabs = [['awaiting_assignment', 'Awaiting assignment'], ['upcoming', 'Upcoming'], ['ongoing', 'Ongoing'], ['awaiting_acceptance', 'Awaiting acceptance'], ['recently_completed', 'Recently completed']] as const
  const rows = lists.data?.[tab] ?? []

  return (
    <>
      <PageHead title="Dashboard" subtitle={summary.data ? `Showing trips for ${summary.data.range_label}` : 'Operational overview'}
        actions={<button className="btn" onClick={() => { summary.refetch(); breakdown.refetch(); util.refetch(); lists.refetch(); exc.refetch(); sms.refetch() }} aria-label="Refresh"><RefreshCw size={15} /> Refresh</button>} />

      <div className="filters" role="group" aria-label="Dashboard filters">
        <select className="input" aria-label="Date range" value={f.range} onChange={(e) => set('range')(e.target.value)}>{RANGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        {f.range === 'custom' && <>
          <input className="input" type="date" aria-label="From" value={f.date_from ?? ''} onChange={(e) => set('date_from')(e.target.value)} />
          <input className="input" type="date" aria-label="To" value={f.date_to ?? ''} onChange={(e) => set('date_to')(e.target.value)} />
        </>}
        {user!.role === 'super_admin' && sel('All vendors', 'vendor_id', vendors?.map((v) => ({ value: v.id, label: v.name })))}
        {sel('All customers', 'customer_id', customers?.map((v) => ({ value: v.id, label: v.name })))}
        {sel('All sites', 'site_id', sites?.map((v) => ({ value: v.id, label: v.name })), !f.customer_id)}
        {sel('All shifts', 'shift_id', shifts?.map((v) => ({ value: v.id, label: v.name })), !f.customer_id)}
        {sel('Any trip type', 'trip_type_id', lookupOptions(lk, 'trip_type'))}
        {sel('Any status', 'status', Object.entries(STATUS_LABEL).filter(([k]) => k !== 'scheduled').map(([value, label]) => ({ value, label })))}
      </div>

      {!ready && <div className="alert alert-warning">Choose a start and end date for the custom range.</div>}
      {summary.isError && <div className="alert alert-danger" role="alert">Could not load the dashboard. {(summary.error as Error)?.message}</div>}

      {/* Most actionable first */}
      <div className="kpis">
        <Kpi label="Awaiting assignment" value={c?.pending_assignment ?? '–'} to="/trips?view=awaiting" warn={!!c?.pending_assignment}
          sub={c?.pending_assignment ? (user!.role === 'operator' ? 'Waiting for a Vendor Admin' : 'Requests need a driver & vehicle') : 'No requests waiting'} />
        <Kpi label="Ongoing trips" value={c?.ongoing ?? '–'} to="/trips?view=ongoing" />
        <Kpi label="Needs attention" value={exc.data ? nExc : '–'} sub={nExc ? 'See exceptions below' : 'All clear'} warn={nExc > 0} />
        <Kpi label="Assigned, not yet accepted" value={c?.assigned ?? '–'} to="/trips?view=assigned" />
        <Kpi label="Upcoming" value={c?.upcoming ?? '–'} to="/trips?view=upcoming" />
        <Kpi label="Accepted" value={c?.accepted ?? '–'} to="/trips?view=accepted" />
        <Kpi label="Completed" value={c?.completed ?? '–'} to="/trips?view=completed" />
        <Kpi label="Cancelled" value={c?.cancelled ?? '–'} to="/trips?view=cancelled" />
        <Kpi label="Total trips" value={c?.total_trips ?? '–'} to="/trips?view=all" />
        <Kpi label="Total passengers" value={c?.total_passengers ?? '–'} />
        <Kpi label="Capacity utilization" value={c ? `${c.capacity_utilization}%` : '–'} sub="Seats used incl. escort" />
        <Kpi label="Escort seat trips" value={c?.escort_trips ?? '–'} sub="Female passenger on board" />
        <Kpi label="SMS sent" value={c?.sms_sent ?? '–'} sub={c?.sms_pending ? `${c.sms_pending} pending` : undefined} />
        <Kpi label="SMS failed" value={c?.sms_failed ?? '–'} to={c?.sms_failed ? '/notifications' : undefined} warn={!!c?.sms_failed} />
      </div>

      <h2 style={{ margin: '4px 0 10px' }}>Fleet right now</h2>
      <div className="kpis">
        <Kpi label="Available drivers" value={r ? `${r.drivers_available}` : '–'} sub={r ? `of ${r.drivers_active} active` : undefined} />
        <Kpi label="Drivers in use" value={r?.drivers_in_use ?? '–'} />
        <Kpi label="Available vehicles" value={r ? `${r.vehicles_available}` : '–'} sub={r ? `of ${r.vehicles_active} active` : undefined} />
        <Kpi label="Vehicles in use" value={r?.vehicles_in_use ?? '–'} />
      </div>

      <div className="card section">
        <div className="chart-head"><h2>Exceptions</h2><Badge tone={nExc ? 'danger' : 'success'}>{nExc ? `${nExc} to review` : 'None'}</Badge></div>
        {!exc.data?.items.length ? <p className="muted" style={{ margin: 0 }}>Nothing needs attention in this view.</p> : exc.data.items.map((e, i) => (
          <div className="exc" key={i}>
            <AlertTriangle size={16} aria-hidden style={{ color: 'var(--danger)', flexShrink: 0, marginTop: 2 }} />
            <div><Badge tone="warning">{REASON[e.reason] ?? e.reason}</Badge> <Link to={`/trips/${e.trip_id}`}>{e.message}</Link></div>
          </div>
        ))}
      </div>

      <div className="chart-grid">
        <ChartCard title="Trips by status" data={(breakdown.data?.status ?? []).map((s) => ({ label: STATUS_LABEL[s.status] ?? s.status, value: s.count }))}>
          <BarList data={(breakdown.data?.status ?? []).map((s) => ({ label: STATUS_LABEL[s.status] ?? s.status, value: s.count }))} />
        </ChartCard>
        <ChartCard title="Trip volume by hour" subtitle="Scheduled start, local time" data={(breakdown.data?.hourly ?? []).map((h) => ({ label: `${String(h.hour).padStart(2, '0')}:00`, value: h.count }))}>
          <Columns data={(breakdown.data?.hourly ?? []).map((h) => ({ label: `${String(h.hour).padStart(2, '0')}:00`, value: h.count }))} every={3} />
        </ChartCard>
        {(breakdown.data?.daily.length ?? 0) > 1 && (
          <ChartCard title="Trips per day" data={breakdown.data!.daily.map((d) => ({ label: d.date, value: d.count }))}>
            <Trend data={breakdown.data!.daily.map((d) => ({ label: d.date, value: d.count }))} />
          </ChartCard>
        )}
        <ChartCard title="Completed vs planned" subtitle="Cancelled trips excluded" data={[{ label: 'Planned', value: breakdown.data?.completed_vs_planned.planned ?? 0 }, { label: 'Completed', value: breakdown.data?.completed_vs_planned.completed ?? 0 }]}>
          <div style={{ fontSize: 34, fontWeight: 650, marginBottom: 8 }}>{breakdown.data?.completed_vs_planned.completion_rate}%</div>
          <Meter value={breakdown.data?.completed_vs_planned.completion_rate ?? 0} label="Completion rate" />
          <p className="muted" style={{ marginBottom: 0 }}>{breakdown.data?.completed_vs_planned.completed} of {breakdown.data?.completed_vs_planned.planned} planned trips completed</p>
        </ChartCard>
        <ChartCard title="On-time performance" subtitle={`Started within ${breakdown.data?.punctuality.grace_minutes ?? 5} min of schedule`} data={[{ label: 'On time', value: breakdown.data?.punctuality.on_time ?? 0 }, { label: 'Late', value: breakdown.data?.punctuality.late ?? 0 }]}>
          <div style={{ fontSize: 34, fontWeight: 650, marginBottom: 8 }}>{breakdown.data?.punctuality.on_time_rate}%</div>
          <Meter value={breakdown.data?.punctuality.on_time_rate ?? 0} label="On-time rate" />
          <p className="muted" style={{ marginBottom: 0 }}>{breakdown.data?.punctuality.late} late of {breakdown.data?.punctuality.started} started{breakdown.data?.punctuality.late ? ` · avg ${breakdown.data.punctuality.avg_delay_minutes} min late` : ''}</p>
        </ChartCard>
        <ChartCard title="Customer-wise trips" data={(breakdown.data?.by_customer ?? []).map((x) => ({ label: x.name, value: x.count }))}>
          <BarList data={(breakdown.data?.by_customer ?? []).map((x) => ({ label: x.name, value: x.count }))} />
        </ChartCard>
        <ChartCard title="Shift-wise trips" data={(breakdown.data?.by_shift ?? []).map((x) => ({ label: x.name, value: x.count }))}>
          <BarList data={(breakdown.data?.by_shift ?? []).map((x) => ({ label: x.name, value: x.count }))} />
        </ChartCard>
        {user!.role === 'super_admin' && (
          <ChartCard title="Vendor-wise trips" data={(breakdown.data?.by_vendor ?? []).map((x) => ({ label: x.name, value: x.count }))}>
            <BarList data={(breakdown.data?.by_vendor ?? []).map((x) => ({ label: x.name, value: x.count }))} />
          </ChartCard>
        )}
        <ChartCard title="Driver utilization" subtitle="Trips in period" data={(util.data?.drivers ?? []).map((d) => ({ label: d.name, value: d.trips }))}>
          <BarList data={(util.data?.drivers ?? []).map((d) => ({ label: d.name, value: d.trips, hint: `${d.name}: ${d.trips} trips, ${d.booked_hours} h booked` }))} />
        </ChartCard>
        <ChartCard title="Vehicle utilization" subtitle="Trips in period" data={(util.data?.vehicles ?? []).map((v) => ({ label: v.vehicle_number, value: v.trips }))}>
          <BarList data={(util.data?.vehicles ?? []).map((v) => ({ label: v.vehicle_number, value: v.trips, hint: `${v.vehicle_number}: ${v.trips} trips, ${v.seat_utilization}% of ${v.capacity} seats used` }))} />
        </ChartCard>
        <ChartCard title="Vehicle seat utilization" subtitle="Seats used incl. escort seat" valueLabel="% of seats" data={(util.data?.vehicles ?? []).filter((v) => v.trips).map((v) => ({ label: v.vehicle_number, value: v.seat_utilization }))}>
          <BarList format={(n) => `${n}%`} data={(util.data?.vehicles ?? []).filter((v) => v.trips).map((v) => ({ label: v.vehicle_number, value: v.seat_utilization }))} />
        </ChartCard>
        <ChartCard title="SMS delivery" subtitle={sms.data ? `${sms.data.success_rate}% successful` : undefined} valueLabel="Messages"
          data={Object.entries(sms.data?.by_status ?? {}).map(([k, v]) => ({ label: k[0].toUpperCase() + k.slice(1), value: v }))}>
          <BarList data={Object.entries(sms.data?.by_status ?? {}).map(([k, v]) => ({ label: k[0].toUpperCase() + k.slice(1), value: v }))} />
        </ChartCard>
      </div>

      <div className="card section">
        <div className="chart-head">
          <h2>Trips</h2>
          <div className="seg-tabs" role="tablist">{tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Trip ID</th><th>Date</th><th>Time</th><th>Customer</th><th>Driver</th><th>Vehicle</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  <td><Link to={`/trips/${t.id}`}><strong>{t.code}</strong></Link></td><td>{fmtDate(t.scheduled_start)}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>{fmtTime(t.scheduled_start)} – {fmtTime(t.scheduled_end)}</td>
                  <td>{t.customer_name}</td><td>{t.driver_name ?? <span className="muted">—</span>}</td><td>{t.vehicle_number ?? <span className="muted">—</span>}</td><td><TripStatusBadge status={t.status} /></td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={7} className="muted" style={{ textAlign: 'center', padding: 28 }}>No trips in this list.</td></tr>}
            </tbody>
          </table>
        </div>
        {tab === 'upcoming' && <p className="muted" style={{ marginBottom: 0, fontSize: 12.5 }}>Upcoming shows the next 24 hours from now, whatever date range is selected above.</p>}
      </div>
    </>
  )
}
