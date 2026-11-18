import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Clock, Download, Pencil, Plus, Undo2, Archive } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Badge, Field, Modal, PageHead, SelectInput, TextInput } from '../../components/ui'
import { ApiError, api, download } from '../../services/api'
import { lookupOptions, useLookups } from '../../services/lookups'
import { useAuth } from '../auth/AuthContext'

type State = 'valid' | 'expiring' | 'expired'
interface Item {
  id: number; subject_type: 'driver' | 'vehicle'; subject_id: number; subject_name: string; doc_type_id: number; doc_type: string
  title: string | null; reference_number: string | null; issue_date: string | null; expiry_date: string; days_left: number
  compliance: State; notes: string | null; status: 'active' | 'inactive'
}
interface Subject { id: number; name: string; state: 'compliant' | 'expiring' | 'non_compliant' | 'no_documents'; documents: number; expired: number; expiring: number }
interface Resp {
  summary: { documents: Record<'total' | 'valid' | 'expiring' | 'expired', number>; subjects: Record<'total' | 'compliant' | 'expiring' | 'non_compliant' | 'no_documents', number> }
  subjects: Subject[]; total: number; items: Item[]
}

const fmt = (d: string) => new Date(d + 'T00:00:00').toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })
// Colour is never the only signal: every state also has an icon and a word.
export function StateBadge({ state, days }: { state: State; days?: number }) {
  if (state === 'expired') return <Badge tone="danger"><AlertCircle size={12} style={{ marginRight: 4 }} />Expired</Badge>
  if (state === 'expiring') return <Badge tone="warning"><Clock size={12} style={{ marginRight: 4 }} />{days === 0 ? 'Expires today' : 'About to expire'}</Badge>
  return <Badge tone="success"><CheckCircle2 size={12} style={{ marginRight: 4 }} />Valid</Badge>
}
const SUBJECT_TONE = { compliant: 'success', expiring: 'warning', non_compliant: 'danger', no_documents: 'neutral' } as const
const SUBJECT_LABEL = { compliant: 'Compliant', expiring: 'Expiring soon', non_compliant: 'Non-compliant', no_documents: 'No documents' } as const

export function CompliancePage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'super_admin' || user?.role === 'vendor_admin'
  const isDriver = user?.role === 'driver'
  const [kind, setKind] = useState<'drivers' | 'vehicles'>('drivers')
  const [f, setF] = useState<Record<string, string>>({})
  const [page, setPage] = useState(0)
  const [editing, setEditing] = useState<Item | 'new' | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const qc = useQueryClient()
  const limit = 15
  const set = (k: string) => (v: string) => { setF({ ...f, [k]: v }); setPage(0) }
  const params = new URLSearchParams({ limit: String(limit), offset: String(page * limit) })
  Object.entries(f).forEach(([k, v]) => v && params.set(k, v))
  const { data, isLoading, isError } = useQuery({ queryKey: ['compliance', kind, params.toString()], queryFn: () => api<Resp>(`/compliance/${kind}?${params}`) })
  const { data: lk } = useLookups()
  const { data: vendors } = useQuery({ queryKey: ['vendors', 'all'], enabled: user?.role === 'super_admin', queryFn: () => api<{ items: { id: number; name: string }[] }>('/vendors?limit=200').then((r) => r.items) })
  const retire = useMutation({
    mutationFn: (i: Item) => api(`/compliance/items/${i.id}/status`, { method: 'PATCH', body: JSON.stringify({ status: i.status === 'active' ? 'inactive' : 'active' }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['compliance'] }),
  })
  const exportXlsx = async () => {
    setBusy(true); setError('')
    try { await download(`/reports/compliance-${kind}?format=xlsx${f.vendor_id ? `&vendor_id=${f.vendor_id}` : ''}`, `yaan-compliance-${kind}.xlsx`) }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Download failed') } finally { setBusy(false) }
  }

  const s = data?.summary
  const attention = data?.subjects.filter((x) => x.state === 'non_compliant' || x.state === 'no_documents') ?? []
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / limit))
  const types = lookupOptions(lk, kind === 'drivers' ? 'driver_doc_type' : 'vehicle_doc_type')
  return (
    <>
      <PageHead title="Compliance" subtitle={isDriver ? 'Your documents and their expiry dates.' : 'Track document expiry for drivers and vehicles.'}
        actions={<>
          {!isDriver && <button className="btn" onClick={exportXlsx} disabled={busy}><Download size={16} /> {busy ? 'Preparing…' : 'Export Excel'}</button>}
          {canWrite && <button className="btn btn-primary" onClick={() => setEditing('new')}><Plus size={16} /> Add document</button>}
        </>} />
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {!isDriver && (
        <div className="seg-tabs" role="tablist" style={{ marginBottom: 16 }}>
          {(['drivers', 'vehicles'] as const).map((k) => <button key={k} role="tab" aria-selected={kind === k} className={kind === k ? 'on' : ''} onClick={() => { setKind(k); setF({}); setPage(0) }}>{k === 'drivers' ? 'Drivers' : 'Vehicles'}</button>)}
        </div>
      )}

      <div className="kpis">
        <div className="kpi"><div className="label">{kind === 'drivers' ? 'Compliant drivers' : 'Compliant vehicles'}</div><div className="value">{s?.subjects.compliant ?? '–'}</div><div className="sub">of {s?.subjects.total ?? '–'} active</div></div>
        <div className={`kpi ${s?.subjects.non_compliant ? 'warn' : ''}`}><div className="label">Non-compliant</div><div className="value">{s?.subjects.non_compliant ?? '–'}</div><div className="sub">have an expired document</div></div>
        <div className="kpi"><div className="label">Expiring soon</div><div className="value">{s?.subjects.expiring ?? '–'}</div><div className="sub">{s?.documents.expiring ?? 0} document(s)</div></div>
        <div className="kpi"><div className="label">No documents</div><div className="value">{s?.subjects.no_documents ?? '–'}</div><div className="sub">nothing recorded yet</div></div>
      </div>

      {attention.length > 0 && !isDriver && (
        <div className="card section">
          <h2>Needs attention</h2>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {attention.map((a) => (
              <button key={a.id} className="chip" onClick={() => set('subject_id')(String(a.id))} title="Show this item's documents">
                {a.name} <Badge tone={SUBJECT_TONE[a.state]}>{SUBJECT_LABEL[a.state]}</Badge>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <div className="toolbar">
          <input className="input" style={{ flex: 1 }} placeholder="Search name, reference or document" aria-label="Search" value={f.q ?? ''} onChange={(e) => set('q')(e.target.value)} />
          <select className="input" aria-label="Status" value={f.status ?? ''} onChange={(e) => set('status')(e.target.value)}>
            <option value="">Any status</option><option value="valid">Valid</option><option value="expiring">About to expire</option><option value="expired">Expired</option>
          </select>
          <select className="input" aria-label="Document type" value={f.doc_type_id ?? ''} onChange={(e) => set('doc_type_id')(e.target.value)}>
            <option value="">All document types</option>{types.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          {user?.role === 'super_admin' && (
            <select className="input" aria-label="Vendor" value={f.vendor_id ?? ''} onChange={(e) => set('vendor_id')(e.target.value)}>
              <option value="">All vendors</option>{vendors?.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          )}
          {canWrite && <label className="chip"><input type="checkbox" checked={f.include_retired === 'true'} onChange={(e) => set('include_retired')(e.target.checked ? 'true' : '')} /> Show retired</label>}
          {f.subject_id && <button className="btn" onClick={() => set('subject_id')('')}>Clear selection</button>}
        </div>
        {isLoading ? <p className="muted">Loading…</p> : isError ? <div className="alert alert-danger">Could not load compliance data.</div> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>{kind === 'drivers' ? 'Driver' : 'Vehicle'}</th><th>Document</th><th>Reference</th><th>Issued</th><th>Expires</th><th>Status</th>{canWrite && <th>Actions</th>}</tr></thead>
              <tbody>
                {data!.items.map((i) => (
                  <tr key={i.id} style={i.status === 'inactive' ? { opacity: 0.55 } : undefined}>
                    <td><strong>{i.subject_name}</strong></td>
                    <td>{i.doc_type}{i.title ? ` — ${i.title}` : ''}{i.status === 'inactive' && <span className="muted"> (retired)</span>}</td>
                    <td>{i.reference_number ?? '—'}</td><td>{i.issue_date ? fmt(i.issue_date) : '—'}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{fmt(i.expiry_date)}<div className="muted" style={{ fontSize: 12 }}>{i.days_left < 0 ? `${-i.days_left} days ago` : i.days_left === 0 ? 'today' : `in ${i.days_left} days`}</div></td>
                    <td>{i.status === 'active' ? <StateBadge state={i.compliance} days={i.days_left} /> : <Badge tone="neutral">Retired</Badge>}</td>
                    {canWrite && (
                      <td style={{ whiteSpace: 'nowrap', display: 'flex', gap: 6 }}>
                        <button className="btn" aria-label="Edit document" title="Edit / renew" onClick={() => setEditing(i)}><Pencil size={15} /></button>
                        <button className="btn" aria-label={i.status === 'active' ? 'Retire document' : 'Restore document'} title={i.status === 'active' ? 'Retire (keeps history)' : 'Restore'}
                          onClick={() => retire.mutate(i)}>{i.status === 'active' ? <Archive size={15} /> : <Undo2 size={15} />}</button>
                      </td>
                    )}
                  </tr>
                ))}
                {!data!.items.length && <tr><td colSpan={7} className="muted" style={{ textAlign: 'center', padding: 32 }}>No documents found.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14, flexWrap: 'wrap', gap: 8 }}>
          <span className="muted">{data?.total ?? 0} documents</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="muted">Page {page + 1} of {pages}</span>
            <button className="btn" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </div>
      </div>
      {editing && <ItemModal kind={kind} item={editing === 'new' ? null : editing} typeOptions={types} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); qc.invalidateQueries({ queryKey: ['compliance'] }) }} />}
    </>
  )
}

function ItemModal({ kind, item, typeOptions, onClose, onSaved }: { kind: 'drivers' | 'vehicles'; item: Item | null; typeOptions: { value: string | number; label: string }[]; onClose: () => void; onSaved: () => void }) {
  const one = kind === 'drivers' ? 'driver' : 'vehicle'
  const { data: subjects } = useQuery({
    queryKey: ['subjects', kind], enabled: !item,
    queryFn: () => api<{ items: Record<string, string | number>[] }>(`/${kind}?status=active&limit=200`).then((r) => r.items.map((x) => ({ id: x.id as number, label: kind === 'drivers' ? `${x.first_name} ${x.last_name} (${x.code})` : `${x.vehicle_number} (${x.model})` }))),
  })
  const [f, setF] = useState({
    subject_id: item ? String(item.subject_id) : '', doc_type_id: item ? String(item.doc_type_id) : '', title: item?.title ?? '',
    reference_number: item?.reference_number ?? '', issue_date: item?.issue_date ?? '', expiry_date: item?.expiry_date ?? '', notes: item?.notes ?? '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const isOther = typeOptions.find((t) => String(t.value) === f.doc_type_id)?.label === 'Other'

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setErrors({}); setFormError('')
    const n = (v: string) => (v.trim() ? v.trim() : null)
    const body = {
      subject_type: one, ...(item ? {} : { [`${one}_id`]: Number(f.subject_id) }), doc_type_id: Number(f.doc_type_id),
      title: isOther ? n(f.title) : null, reference_number: n(f.reference_number), issue_date: n(f.issue_date), expiry_date: f.expiry_date || null, notes: n(f.notes),
    }
    try {
      await api(item ? `/compliance/items/${item.id}` : '/compliance/items', { method: item ? 'PUT' : 'POST', body: JSON.stringify(body) })
      onSaved()
    } catch (err) {
      if (err instanceof ApiError) { setErrors(err.fieldErrors); if (!Object.keys(err.fieldErrors).length) setFormError(err.message) } else setFormError('Something went wrong.')
    } finally { setBusy(false) }
  }
  return (
    <Modal title={item ? 'Edit document' : 'Add document'} onClose={onClose}>
      <form onSubmit={submit}>
        {formError && <div className="alert alert-danger" role="alert">{formError}</div>}
        {item ? <p><strong>{item.subject_name}</strong> <span className="muted">· to record a renewal, update the dates (or retire this and add a new one)</span></p> : (
          <Field label={`${kind === 'drivers' ? 'Driver' : 'Vehicle'} *`} error={errors[`${one}_id`] ?? errors.subject_type}>
            <SelectInput value={f.subject_id} onChange={set('subject_id')} required>
              <option value="">Select {one}</option>{subjects?.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </SelectInput>
          </Field>
        )}
        <div className="form-grid">
          <Field label="Document type *" error={errors.doc_type_id}>
            <SelectInput value={f.doc_type_id} onChange={set('doc_type_id')} required>
              <option value="">Select type</option>{typeOptions.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </SelectInput>
          </Field>
          {isOther ? <Field label="Title" error={errors.title}><TextInput value={f.title} onChange={set('title')} /></Field> : <Field label="Reference / number" error={errors.reference_number}><TextInput value={f.reference_number} onChange={set('reference_number')} /></Field>}
          <Field label="Issue date" error={errors.issue_date}><TextInput type="date" value={f.issue_date} onChange={set('issue_date')} /></Field>
          <Field label="Expiry date *" error={errors.expiry_date ?? errors.body} hint="Valid through this date"><TextInput type="date" value={f.expiry_date} onChange={set('expiry_date')} required /></Field>
        </div>
        {isOther && <Field label="Reference / number"><TextInput value={f.reference_number} onChange={set('reference_number')} /></Field>}
        <Field label="Notes"><textarea className="input" style={{ height: 64, padding: 10 }} value={f.notes} onChange={set('notes')} /></Field>
        <p className="muted" style={{ fontSize: 13 }}>Only the details and dates are recorded — no files are uploaded.</p>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Modal>
  )
}
