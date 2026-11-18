import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownRight, ArrowUpRight, Ban, Download, Pencil, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Badge, Field, Modal, PageHead, SelectInput, TextInput } from '../../components/ui'
import { ApiError, api, download } from '../../services/api'
import { inr, inrShort, periodDates, todayStr } from '../../services/format'
import { ROLE_LABELS, type Role } from '../../types'
import { useAuth } from '../auth/AuthContext'
import { BarList, ChartCard, Columns, Trend } from '../dashboard/charts'

interface Expense {
  id: number; code: string; vendor_id: number; vendor_name: string | null; expense_date: string; category_id: number; category: string
  amount: number; payment_method: string; payment_method_label: string; description: string | null
  vehicle_id: number | null; vehicle_number: string | null; driver_id: number | null; driver_name: string | null
  entered_by: string; entered_by_role: Role; created_at: string; status: 'recorded' | 'voided'
  void_reason: string | null; voided_by: string | null; can_edit: boolean; can_void: boolean
}
interface Options {
  categories: { id: number; label: string }[]; payment_methods: { value: string; label: string }[]
  vehicles: { id: number; label: string }[]; drivers: { id: number; label: string }[]; own_driver_id: number | null
}
interface Summary {
  range_label: string; total: number; count: number; average: number; previous_total: number; change_pct: number | null; voided_count: number
  by_category: Row[]; by_vehicle: Row[]; by_payment: Row[]; by_person: (Row & { role: Role })[]; by_vendor: Row[]
  trend: { label: string; amount: number }[]; trend_unit: 'day' | 'month'; without_vehicle: number
}
type Row = { name: string; amount: number; count: number }

const PERIODS = [['this_month', 'This month'], ['last_month', 'Last month'], ['this_week', 'This week'], ['today', 'Today'], ['this_year', 'This year'], ['custom', 'Custom range']] as const
const fmtDay = (d: string) => new Date(d + 'T00:00:00').toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })

export function ExpensesPage() {
  const { user } = useAuth()
  const isAdmin = user!.role === 'super_admin' || user!.role === 'vendor_admin'
  const isSuper = user!.role === 'super_admin'
  const qc = useQueryClient()
  const [tab, setTab] = useState<'summary' | 'list'>(isAdmin ? 'summary' : 'list')
  const [range, setRange] = useState(isAdmin ? 'this_month' : 'all')
  const [dates, setDates] = useState({ from: '', to: '' })
  const [vendor, setVendor] = useState('')
  const [f, setF] = useState<Record<string, string>>({})
  const [page, setPage] = useState(0)
  const [editing, setEditing] = useState<Expense | 'new' | null>(null)
  const [voiding, setVoiding] = useState<Expense | null>(null)
  const [exportError, setExportError] = useState('')
  const [busy, setBusy] = useState(false)
  const limit = 15

  const { data: vendors } = useQuery({ queryKey: ['vendors', 'all'], enabled: isSuper, queryFn: () => api<{ items: { id: number; name: string }[] }>('/vendors?limit=200').then((r) => r.items) })
  const { data: opts } = useQuery({ queryKey: ['expense-options', vendor], queryFn: () => api<Options>(`/expenses/options${vendor ? `?vendor_id=${vendor}` : ''}`) })

  const effRange = tab === 'summary' && range === 'all' ? 'this_month' : range
  const per = periodDates(effRange, dates.from, dates.to)
  const summaryQs = new URLSearchParams({ range: effRange })
  if (effRange === 'custom') { summaryQs.set('date_from', dates.from); summaryQs.set('date_to', dates.to) }
  if (vendor) summaryQs.set('vendor_id', vendor)
  const customReady = effRange !== 'custom' || (!!dates.from && !!dates.to)

  const summary = useQuery({ queryKey: ['expenses', 'summary', summaryQs.toString()], enabled: isAdmin && tab === 'summary' && customReady, queryFn: () => api<Summary>(`/expenses/summary?${summaryQs}`) })

  const listQs = new URLSearchParams({ limit: String(limit), offset: String(page * limit) })
  if (per.first) listQs.set('date_from', per.first)
  if (per.last) listQs.set('date_to', per.last)
  if (vendor) listQs.set('vendor_id', vendor)
  Object.entries(f).forEach(([k, v]) => v && listQs.set(k, v))
  const list = useQuery({ queryKey: ['expenses', 'list', listQs.toString()], enabled: tab === 'list', queryFn: () => api<{ total: number; total_amount: number; items: Expense[] }>(`/expenses?${listQs}`) })

  const exportXlsx = async () => {
    setBusy(true); setExportError('')
    const q = new URLSearchParams({ range: effRange === 'last_month' || effRange === 'this_year' ? 'custom' : effRange, format: 'xlsx' })
    if (q.get('range') === 'custom') { q.set('date_from', per.first ?? dates.from); q.set('date_to', per.last ?? dates.to) }
    if (vendor) q.set('vendor_id', vendor)
    try { await download(`/reports/expenses?${q}`, 'yaan-expenses.xlsx') } catch (e) { setExportError(e instanceof ApiError ? e.message : 'Download failed') } finally { setBusy(false) }
  }
  const refresh = () => qc.invalidateQueries({ queryKey: ['expenses'] })
  const set = (k: string) => (v: string) => { setF((s) => ({ ...s, [k]: v })); setPage(0) }
  const s = summary.data
  const pages = Math.max(1, Math.ceil((list.data?.total ?? 0) / limit))
  const money = (rows: Row[]) => rows.map((r) => ({ label: r.name, value: r.amount, hint: `${r.name}: ${inr(r.amount)} · ${r.count} entr${r.count === 1 ? 'y' : 'ies'}` }))

  return (
    <>
      <PageHead title={isAdmin ? 'Expenses' : 'My expenses'}
        subtitle={isSuper ? 'Everything recorded across all vendors.' : isAdmin ? 'Expenses recorded in your vendor.' : 'Record vehicle, fuel and maintenance costs. You see only what you entered.'}
        actions={<>
          {isAdmin && <button className="btn" onClick={exportXlsx} disabled={busy || !customReady}><Download size={16} /> {busy ? 'Preparing…' : 'Export Excel'}</button>}
          <button className="btn btn-primary" onClick={() => setEditing('new')}><Plus size={16} /> Add expense</button>
        </>} />
      {exportError && <div className="alert alert-danger" role="alert">{exportError}</div>}

      {isAdmin && (
        <div className="seg-tabs" role="tablist" style={{ marginBottom: 16 }}>
          <button role="tab" aria-selected={tab === 'summary'} className={tab === 'summary' ? 'on' : ''} onClick={() => setTab('summary')}>Summary</button>
          <button role="tab" aria-selected={tab === 'list'} className={tab === 'list' ? 'on' : ''} onClick={() => setTab('list')}>All expenses</button>
        </div>
      )}

      <div className="filters" role="group" aria-label="Period">
        <select className="input" aria-label="Period" value={effRange} onChange={(e) => { setRange(e.target.value); setPage(0) }}>
          {tab === 'list' && <option value="all">All time</option>}
          {PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        {effRange === 'custom' && <>
          <input className="input" type="date" aria-label="From" value={dates.from} max={todayStr()} onChange={(e) => { setDates({ ...dates, from: e.target.value }); setPage(0) }} />
          <input className="input" type="date" aria-label="To" value={dates.to} max={todayStr()} onChange={(e) => { setDates({ ...dates, to: e.target.value }); setPage(0) }} />
        </>}
        {isSuper && (
          <select className="input" aria-label="Vendor" value={vendor} onChange={(e) => { setVendor(e.target.value); setPage(0) }}>
            <option value="">All vendors</option>{vendors?.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        )}
      </div>
      {!customReady && <div className="alert alert-warning">Choose a start and end date for the custom range.</div>}

      {tab === 'summary' && isAdmin && (
        <>
          {summary.isError && <div className="alert alert-danger" role="alert">Could not load the summary.</div>}
          <div className="kpis">
            <div className="kpi"><div className="label">Total spent</div><div className="value">{s ? inr(s.total) : '–'}</div><div className="sub">{s?.range_label}</div></div>
            <div className="kpi"><div className="label">Entries</div><div className="value">{s?.count ?? '–'}</div>{!!s?.voided_count && <div className="sub">{s.voided_count} voided (not counted)</div>}</div>
            <div className="kpi"><div className="label">Average per entry</div><div className="value">{s ? inr(s.average) : '–'}</div></div>
            <div className="kpi">
              <div className="label">Versus previous period</div>
              <div className="value" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {s?.change_pct == null ? '–' : <>{s.change_pct > 0 ? <ArrowUpRight size={22} aria-hidden /> : <ArrowDownRight size={22} aria-hidden />}{Math.abs(s.change_pct)}%</>}
              </div>
              <div className="sub">{s ? (s.change_pct == null ? 'No spend in the previous period' : `${s.change_pct > 0 ? 'Up' : s.change_pct < 0 ? 'Down' : 'Same'} from ${inr(s.previous_total)}`) : ''}</div>
            </div>
            <div className="kpi"><div className="label">Not tied to a vehicle</div><div className="value">{s ? inr(s.without_vehicle) : '–'}</div></div>
          </div>
          <div className="chart-grid">
            {isSuper && !vendor && <ChartCard title="Spend by vendor" valueLabel="Amount" format={inr} data={money(s?.by_vendor ?? [])}><BarList format={inrShort} data={money(s?.by_vendor ?? [])} /></ChartCard>}
            <ChartCard title="Spend by category" valueLabel="Amount" format={inr} data={money(s?.by_category ?? [])}><BarList format={inrShort} data={money(s?.by_category ?? [])} /></ChartCard>
            <ChartCard title={`Spend per ${s?.trend_unit ?? 'day'}`} valueLabel="Amount" format={inr} data={(s?.trend ?? []).map((t) => ({ label: t.label, value: t.amount }))}>
              {(s?.trend.length ?? 0) > 1 && s?.trend_unit === 'day' ? <Trend format={inr} data={s.trend.map((t) => ({ label: t.label, value: t.amount }))} />
                : <Columns format={inr} data={(s?.trend ?? []).map((t) => ({ label: t.label, value: t.amount }))} />}
            </ChartCard>
            <ChartCard title="Spend by vehicle" subtitle="Top 8" valueLabel="Amount" format={inr} data={money(s?.by_vehicle ?? [])}><BarList format={inrShort} data={money(s?.by_vehicle ?? [])} /></ChartCard>
            <ChartCard title="Payment method" valueLabel="Amount" format={inr} data={money(s?.by_payment ?? [])}><BarList format={inrShort} data={money(s?.by_payment ?? [])} /></ChartCard>
            <ChartCard title="Entered by" subtitle="Top 8 people" valueLabel="Amount" format={inr}
              data={(s?.by_person ?? []).map((p) => ({ label: `${p.name} (${ROLE_LABELS[p.role]})`, value: p.amount }))}>
              <BarList format={inrShort} data={(s?.by_person ?? []).map((p) => ({ label: `${p.name} · ${ROLE_LABELS[p.role]}`, value: p.amount, hint: `${p.name}: ${inr(p.amount)} · ${p.count} entries` }))} />
            </ChartCard>
          </div>
        </>
      )}

      {tab === 'list' && (
        <div className="card">
          <div className="toolbar">
            <input className="input" style={{ flex: 1 }} placeholder="Search description or ID" aria-label="Search" value={f.q ?? ''} onChange={(e) => set('q')(e.target.value)} />
            <select className="input" aria-label="Category" value={f.category_id ?? ''} onChange={(e) => set('category_id')(e.target.value)}>
              <option value="">All categories</option>{opts?.categories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
            <select className="input" aria-label="Payment method" value={f.payment_method ?? ''} onChange={(e) => set('payment_method')(e.target.value)}>
              <option value="">Any payment</option>{opts?.payment_methods.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
            <select className="input" aria-label="Status" value={f.status ?? ''} onChange={(e) => set('status')(e.target.value)}>
              <option value="">Recorded and voided</option><option value="recorded">Recorded</option><option value="voided">Voided</option>
            </select>
          </div>
          {list.isLoading ? <p className="muted">Loading…</p> : list.isError ? <div className="alert alert-danger">Could not load expenses.</div> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Date</th><th>ID</th><th>Category</th><th style={{ textAlign: 'right' }}>Amount</th><th>Vehicle</th><th>Driver</th><th>Payment</th><th>Entered by</th><th>Description</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {list.data!.items.map((e) => (
                    <tr key={e.id} style={e.status === 'voided' ? { opacity: 0.6 } : undefined}>
                      <td style={{ whiteSpace: 'nowrap' }}>{fmtDay(e.expense_date)}</td><td>{e.code}</td><td>{e.category}</td>
                      <td style={{ textAlign: 'right', whiteSpace: 'nowrap', textDecoration: e.status === 'voided' ? 'line-through' : undefined }}><strong>{inr(e.amount)}</strong></td>
                      <td>{e.vehicle_number ?? '—'}</td><td>{e.driver_name ?? '—'}</td><td>{e.payment_method_label}</td>
                      <td>{e.entered_by}<div className="muted" style={{ fontSize: 12 }}>{ROLE_LABELS[e.entered_by_role]}{isSuper && e.vendor_name ? ` · ${e.vendor_name}` : ''}</div></td>
                      <td style={{ maxWidth: 240, fontSize: 13 }}>{e.description ?? '—'}</td>
                      <td>{e.status === 'voided' ? <><Badge tone="neutral">Voided</Badge><div className="reason" title={e.void_reason ?? ''} style={{ maxWidth: 160 }}>{e.void_reason}</div></> : <Badge tone="success">Recorded</Badge>}</td>
                      <td style={{ whiteSpace: 'nowrap', display: 'flex', gap: 6 }}>
                        {e.can_edit && <button className="btn" aria-label={`Edit ${e.code}`} title="Edit" onClick={() => setEditing(e)}><Pencil size={15} /></button>}
                        {e.can_void && <button className="btn" aria-label={`Void ${e.code}`} title="Void (keeps history)" onClick={() => setVoiding(e)}><Ban size={15} /></button>}
                      </td>
                    </tr>
                  ))}
                  {!list.data!.items.length && <tr><td colSpan={11} className="muted" style={{ textAlign: 'center', padding: 32 }}>No expenses found.</td></tr>}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14, flexWrap: 'wrap', gap: 8 }}>
            <span className="muted">{list.data?.total ?? 0} entries · <strong>{inr(list.data?.total_amount ?? 0)}</strong> total (voided excluded)</span>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
              <span className="muted">Page {page + 1} of {pages}</span>
              <button className="btn" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          </div>
        </div>
      )}

      {editing && <ExpenseModal expense={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh() }} />}
      {voiding && <VoidModal expense={voiding} onClose={() => setVoiding(null)} onDone={() => { setVoiding(null); refresh() }} />}
    </>
  )
}

function ExpenseModal({ expense, onClose, onSaved }: { expense: Expense | null; onClose: () => void; onSaved: () => void }) {
  const { user } = useAuth()
  const isSuper = user!.role === 'super_admin'
  const isDriver = user!.role === 'driver'
  const [f, setF] = useState({
    vendor_id: '', expense_date: expense?.expense_date ?? todayStr(), category_id: expense ? String(expense.category_id) : '',
    amount: expense ? String(expense.amount) : '', payment_method: expense?.payment_method ?? '', vehicle_id: expense?.vehicle_id ? String(expense.vehicle_id) : '',
    driver_id: expense?.driver_id ? String(expense.driver_id) : '', description: expense?.description ?? '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)
  const vendorForOptions = expense ? String(expense.vendor_id) : f.vendor_id
  const { data: vendors } = useQuery({ queryKey: ['vendors', 'active'], enabled: isSuper && !expense, queryFn: () => api<{ items: { id: number; name: string }[] }>('/vendors?status=active&limit=200').then((r) => r.items) })
  const { data: opts } = useQuery({
    queryKey: ['expense-options', 'form', vendorForOptions], enabled: !isSuper || !!vendorForOptions,
    queryFn: () => api<Options>(`/expenses/options${isSuper ? `?vendor_id=${vendorForOptions}` : ''}`),
  })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value, ...(k === 'vendor_id' ? { vehicle_id: '', driver_id: '' } : {}) }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setErrors({}); setFormError('')
    const n = (v: string) => (v ? Number(v) : null)
    const body = {
      ...(isSuper && !expense ? { vendor_id: n(f.vendor_id) } : {}), expense_date: f.expense_date, category_id: n(f.category_id), amount: f.amount,
      payment_method: f.payment_method, vehicle_id: n(f.vehicle_id), driver_id: isDriver ? null : n(f.driver_id), description: f.description.trim() || null,
    }
    try {
      await api(expense ? `/expenses/${expense.id}` : '/expenses', { method: expense ? 'PUT' : 'POST', body: JSON.stringify(body) })
      onSaved()
    } catch (err) {
      if (err instanceof ApiError) { setErrors(err.fieldErrors); if (!Object.keys(err.fieldErrors).length) setFormError(err.message) } else setFormError('Something went wrong.')
    } finally { setBusy(false) }
  }

  return (
    <Modal title={expense ? `Edit ${expense.code}` : 'Add expense'} onClose={onClose} wide>
      <form onSubmit={submit}>
        {formError && <div className="alert alert-danger" role="alert">{formError}</div>}
        <div className="form-grid">
          {isSuper && !expense && (
            <Field label="Vendor *" error={errors.vendor_id}>
              <SelectInput value={f.vendor_id} onChange={set('vendor_id')} required><option value="">Select vendor</option>{vendors?.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</SelectInput>
            </Field>
          )}
          <Field label="Date *" error={errors.expense_date}><TextInput type="date" value={f.expense_date} max={todayStr()} onChange={set('expense_date')} required /></Field>
          <Field label="Category *" error={errors.category_id}>
            <SelectInput value={f.category_id} onChange={set('category_id')} required><option value="">Select category</option>{opts?.categories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}</SelectInput>
          </Field>
          <Field label="Amount (₹) *" error={errors.amount}><TextInput type="number" inputMode="decimal" min="0.01" step="0.01" value={f.amount} onChange={set('amount')} required /></Field>
          <Field label="Paid by *" error={errors.payment_method}>
            <SelectInput value={f.payment_method} onChange={set('payment_method')} required><option value="">Select payment method</option>{opts?.payment_methods.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}</SelectInput>
          </Field>
          <Field label="Vehicle" error={errors.vehicle_id} hint={isSuper && !f.vendor_id && !expense ? 'Select a vendor first' : 'Optional'}>
            <SelectInput value={f.vehicle_id} onChange={set('vehicle_id')}><option value="">Not tied to a vehicle</option>{opts?.vehicles.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}</SelectInput>
          </Field>
          {isDriver ? <p className="muted" style={{ alignSelf: 'center', margin: 0 }}>This expense is recorded against you.</p> : (
            <Field label="Driver" error={errors.driver_id} hint="Optional">
              <SelectInput value={f.driver_id} onChange={set('driver_id')}><option value="">No specific driver</option>{opts?.drivers.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}</SelectInput>
            </Field>
          )}
        </div>
        <Field label="Description" error={errors.description} hint="What was it for? e.g. “Diesel – 40 L at HP pump, Baner”">
          <textarea className="input" style={{ height: 70, padding: 10 }} maxLength={1000} value={f.description} onChange={set('description')} />
        </Field>
        <p className="muted" style={{ fontSize: 13 }}>Your name is saved with this expense. You can edit or void it for 24 hours; after that ask a Vendor Admin. Nothing is ever deleted.</p>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save expense'}</button>
        </div>
      </form>
    </Modal>
  )
}

function VoidModal({ expense, onClose, onDone }: { expense: Expense; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setError('')
    try { await api(`/expenses/${expense.id}/void`, { method: 'POST', body: JSON.stringify({ reason }) }); onDone() }
    catch (err) { setError(err instanceof ApiError ? err.fieldErrors.reason ?? err.message : 'Could not void') } finally { setBusy(false) }
  }
  return (
    <Modal title={`Void ${expense.code}?`} onClose={onClose}>
      <form onSubmit={submit}>
        <p className="muted" style={{ marginTop: 0 }}>{inr(expense.amount)} · {expense.category}. The entry stays in history but is left out of all totals. This can't be undone.</p>
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        <Field label="Reason *"><textarea className="input" style={{ height: 70, padding: 10 }} value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} autoFocus /></Field>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>Keep expense</button>
          <button className="btn btn-danger" disabled={busy || reason.trim().length < 3}>{busy ? 'Voiding…' : 'Void expense'}</button>
        </div>
      </form>
    </Modal>
  )
}
