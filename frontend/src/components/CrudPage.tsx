import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Power } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useAuth } from '../modules/auth/AuthContext'
import { ApiError, api } from '../services/api'
import { Badge, Field, Modal, PageHead, SelectInput, TextInput } from './ui'

type Opt = { value: string | number; label: string }
type Row = Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
type Form = Record<string, string | string[]>

export type FieldDef =
  | { type: 'section'; label: string }
  | {
      key: string; label: string
      type?: 'text' | 'email' | 'tel' | 'number' | 'date' | 'time' | 'textarea' | 'select' | 'multi'
      required?: boolean; hint?: string; wide?: boolean; numeric?: boolean
      options?: Opt[]
      /** options loaded from the API; return null path to disable until dependencies are chosen */
      remote?: { path: (form: Form) => string | null; value: (r: Row) => string | number; label: (r: Row) => string }
      createOnly?: boolean // locked after creation (e.g. customer of an employee)
    }

export interface FilterDef { key: string; label: string; options?: Opt[]; remotePath?: string; remoteLabel?: (r: Row) => string }
export interface Column { header: string; cell: (r: Row) => ReactNode }

interface Props {
  title: string
  noun: string
  subtitle?: string
  endpoint: string
  columns: Column[]
  fields: FieldDef[]
  filters?: FilterDef[]
  canWrite: boolean
  vendorScoped?: boolean // Super Admin picks the vendor on create and can filter by it
  statusToggle?: boolean
  fixedQuery?: Record<string, string>
  fixedBody?: Record<string, unknown>
  embedded?: boolean
  rowExtra?: (r: Row) => ReactNode
  wideForm?: boolean
  /** form values that are decided for the user (e.g. an Operator's own customer): not shown as fields, always submitted */
  fixedFields?: Record<string, string>
  /** appended to the Add dialog heading, e.g. "for Acme" */
  titleFor?: string
}

const empty = (v: unknown) => v === null || v === undefined

export function CrudPage(p: Props) {
  const { user } = useAuth()
  const isSuper = user?.role === 'super_admin'
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [vendor, setVendor] = useState('')
  const [extra, setExtra] = useState<Record<string, string>>({})
  const [page, setPage] = useState(0)
  const [editing, setEditing] = useState<Row | 'new' | null>(null)
  const limit = 15

  const params = new URLSearchParams({ limit: String(limit), offset: String(page * limit), ...p.fixedQuery })
  if (q) params.set('q', q)
  if (status) params.set('status', status)
  if (vendor) params.set('vendor_id', vendor)
  Object.entries(extra).forEach(([k, v]) => v && params.set(k, v))

  const { data, isLoading, isError } = useQuery({
    queryKey: [p.endpoint, params.toString()],
    queryFn: () => api<{ total: number; items: Row[] }>(`${p.endpoint}?${params}`),
  })
  const toggle = useMutation({
    mutationFn: (r: Row) => api(`${p.endpoint}/${r.id}/status`, { method: 'PATCH', body: JSON.stringify({ status: r.status === 'active' ? 'inactive' : 'active' }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [p.endpoint] }),
  })
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / limit))
  const showVendorCol = p.vendorScoped && isSuper
  const colSpan = p.columns.length + 3

  const body = (
    <div className="card">
      <div className="toolbar">
        <input className="input" style={{ flex: 1 }} placeholder={`Search ${p.noun}s`} aria-label={`Search ${p.noun}s`} value={q} onChange={(e) => { setQ(e.target.value); setPage(0) }} />
        {showVendorCol && !p.embedded && <RemoteFilter label="All vendors" path="/vendors" value={vendor} onChange={(v) => { setVendor(v); setPage(0) }} />}
        {p.filters?.map((f) => f.remotePath
          ? <RemoteFilter key={f.key} label={f.label} path={f.remotePath} labelOf={f.remoteLabel} value={extra[f.key] ?? ''} onChange={(v) => { setExtra({ ...extra, [f.key]: v }); setPage(0) }} />
          : (
            <select key={f.key} className="input" aria-label={f.label} value={extra[f.key] ?? ''} onChange={(e) => { setExtra({ ...extra, [f.key]: e.target.value }); setPage(0) }}>
              <option value="">{f.label}</option>{f.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          ))}
        <select className="input" aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0) }}>
          <option value="">Any status</option><option value="active">Active</option><option value="inactive">Inactive</option>
        </select>
      </div>
      {isLoading ? <p className="muted">Loading…</p> : isError ? <div className="alert alert-danger">Could not load {p.noun}s.</div> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr>
              {p.columns.map((c) => <th key={c.header}>{c.header}</th>)}
              {showVendorCol && !p.embedded && <th>Vendor</th>}
              <th>Status</th>{(p.canWrite || p.rowExtra) && <th>Actions</th>}
            </tr></thead>
            <tbody>
              {data!.items.map((r) => (
                <tr key={r.id}>
                  {p.columns.map((c) => <td key={c.header}>{c.cell(r)}</td>)}
                  {showVendorCol && !p.embedded && <td>{r.vendor_name ?? '—'}</td>}
                  <td><Badge tone={r.status === 'active' ? 'success' : 'neutral'}>{r.status === 'active' ? 'Active' : 'Inactive'}</Badge></td>
                  {(p.canWrite || p.rowExtra) && (
                    <td style={{ whiteSpace: 'nowrap', display: 'flex', gap: 6 }}>
                      {p.rowExtra?.(r)}
                      {p.canWrite && <button className="btn" title="Edit" aria-label={`Edit ${p.noun}`} onClick={() => setEditing(r)}><Pencil size={15} /></button>}
                      {p.canWrite && p.statusToggle !== false && (
                        <button className="btn" title={r.status === 'active' ? 'Deactivate' : 'Activate'} aria-label={r.status === 'active' ? `Deactivate ${p.noun}` : `Activate ${p.noun}`}
                          onClick={() => (r.status !== 'active' || window.confirm(`Deactivate this ${p.noun}? It stays in history but can't be used for new work.`)) && toggle.mutate(r)}><Power size={15} /></button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
              {!data!.items.length && <tr><td colSpan={colSpan} className="muted" style={{ textAlign: 'center', padding: 32 }}>No {p.noun}s found.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14, flexWrap: 'wrap', gap: 8 }}>
        <span className="muted">{data?.total ?? 0} {p.noun}s</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="muted">Page {page + 1} of {pages}</span>
          <button className="btn" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      </div>
      {editing && <EditModal p={p} row={editing === 'new' ? null : editing} isSuper={!!isSuper} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); qc.invalidateQueries({ queryKey: [p.endpoint] }); qc.invalidateQueries({ queryKey: ['/customers'] }) }} />}
    </div>
  )

  const addBtn = p.canWrite && <button className="btn btn-primary" onClick={() => setEditing('new')}><Plus size={16} /> Add {p.noun}</button>
  if (p.embedded) return <>{<div style={{ marginBottom: 12, display: 'flex', justifyContent: 'flex-end' }}>{addBtn}</div>}{body}</>
  return <><PageHead title={p.title} subtitle={p.subtitle} actions={addBtn} />{body}</>
}

function RemoteFilter({ label, path, value, onChange, labelOf }: { label: string; path: string; value: string; onChange: (v: string) => void; labelOf?: (r: Row) => string }) {
  const { data } = useQuery({ queryKey: [path, 'filter'], queryFn: () => api<{ items: Row[] }>(`${path}${path.includes('?') ? '&' : '?'}limit=200`) })
  return (
    <select className="input" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{label}</option>{data?.items.map((r) => <option key={r.id} value={r.id}>{labelOf ? labelOf(r) : r.name}</option>)}
    </select>
  )
}

function RemoteSelect({ f, form, set, error, disabled }: { f: Extract<FieldDef, { key: string }>; form: Form; set: (v: string) => void; error?: string; disabled?: boolean }) {
  const path = f.remote!.path(form)
  const { data, isLoading } = useQuery({ queryKey: ['opts', path], queryFn: () => api<{ items: Row[] }>(path!), enabled: !!path })
  return (
    <Field label={f.label + (f.required ? ' *' : '')} error={error} hint={!path ? f.hint ?? 'Select the related field first' : undefined}>
      <SelectInput value={form[f.key] as string} onChange={(e) => set(e.target.value)} required={f.required} disabled={disabled || !path}>
        <option value="">{isLoading ? 'Loading…' : `Select ${f.label.toLowerCase()}`}</option>
        {data?.items.map((r) => <option key={f.remote!.value(r)} value={f.remote!.value(r)}>{f.remote!.label(r)}</option>)}
      </SelectInput>
    </Field>
  )
}

function EditModal({ p, row, isSuper, onClose, onSaved }: { p: Props; row: Row | null; isSuper: boolean; onClose: () => void; onSaved: () => void }) {
  const fields: FieldDef[] = [
    ...(p.vendorScoped && isSuper && !row ? [{
      key: 'vendor_id', label: 'Vendor', required: true, type: 'select', numeric: true,
      remote: { path: () => '/vendors?status=active&limit=200', value: (r: Row) => r.id, label: (r: Row) => `${r.name} (${r.code})` },
    } as FieldDef] : []),
    ...p.fields,
  ]
  const initial: Form = {}
  for (const f of fields) {
    if (f.type === 'section') continue
    const v = row?.[f.key]
    initial[f.key] = p.fixedFields?.[f.key] !== undefined && !row ? p.fixedFields[f.key] : f.type === 'multi' ? (Array.isArray(v) ? v.map(String) : []) : empty(v) ? '' : f.type === 'time' ? String(v).slice(0, 5) : String(v)
  }
  const [form, setForm] = useState<Form>(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setErrors({}); setFormError('')
    const payload: Record<string, unknown> = { ...p.fixedBody }
    for (const f of fields) {
      if (f.type === 'section') continue
      if (row && f.createOnly) continue
      const v = form[f.key]
      if (f.type === 'multi') payload[f.key] = (v as string[]).length ? v : null
      else if (v === '') payload[f.key] = null
      else payload[f.key] = f.numeric || f.type === 'number' ? Number(v) : v
    }
    try {
      await api(row ? `${p.endpoint}/${row.id}` : p.endpoint, { method: row ? 'PUT' : 'POST', body: JSON.stringify(payload) })
      onSaved()
    } catch (err) {
      if (err instanceof ApiError) { setErrors(err.fieldErrors); if (!Object.keys(err.fieldErrors).length) setFormError(err.message) }
      else setFormError('Something went wrong. Please try again.')
    } finally { setBusy(false) }
  }

  return (
    <Modal title={`${row ? 'Edit' : 'Add'} ${p.noun}${p.titleFor ? ` for ${p.titleFor}` : ''}`} onClose={onClose} wide={p.wideForm ?? true}>
      <form onSubmit={submit}>
        {formError && <div className="alert alert-danger" role="alert">{formError}</div>}
        {Object.keys(errors).length > 0 && <div className="alert alert-danger" role="alert">Please fix the highlighted fields.</div>}
        <div className="form-grid">
          {fields.map((f, i) => {
            if (f.type !== 'section' && p.fixedFields?.[f.key] !== undefined) return null
            if (f.type === 'section') return <h2 key={i} style={{ gridColumn: '1 / -1', margin: '8px 0 12px', fontSize: 15 }}>{f.label}</h2>
            const locked = !!row && !!f.createOnly
            const set = (v: string | string[]) => setForm((s) => {
              const next = { ...s, [f.key]: v }
              // clear dependent selects when their parent changes
              for (const d of fields) if (d.type !== 'section' && d.remote && d.key !== f.key && d.remote.path(s) !== d.remote.path(next)) next[d.key] = ''
              return next
            })
            const wrapStyle = f.wide || f.type === 'textarea' || f.type === 'multi' ? { gridColumn: '1 / -1' } : undefined
            if (f.remote) return <div key={f.key} style={wrapStyle}><RemoteSelect f={f} form={form} set={set} error={errors[f.key]} disabled={locked} /></div>
            return (
              <div key={f.key} style={wrapStyle}>
                <Field label={f.label + (f.required ? ' *' : '')} error={errors[f.key]} hint={f.hint}>
                  {f.type === 'select' ? (
                    <SelectInput value={form[f.key] as string} onChange={(e) => set(e.target.value)} required={f.required} disabled={locked}>
                      <option value="">Select {f.label.toLowerCase()}</option>{f.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </SelectInput>
                  ) : f.type === 'textarea' ? (
                    <textarea className="input" style={{ height: 76, padding: 10 }} value={form[f.key] as string} onChange={(e) => set(e.target.value)} required={f.required} />
                  ) : f.type === 'multi' ? (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      {f.options?.map((o) => {
                        const on = (form[f.key] as string[]).includes(String(o.value))
                        return (
                          <label key={o.value} className={`chip ${on ? 'on' : ''}`}>
                            <input type="checkbox" checked={on} onChange={() => set(on ? (form[f.key] as string[]).filter((x) => x !== String(o.value)) : [...(form[f.key] as string[]), String(o.value)])} /> {o.label}
                          </label>
                        )
                      })}
                    </div>
                  ) : (
                    <TextInput type={f.type ?? 'text'} value={form[f.key] as string} onChange={(e) => set(e.target.value)} required={f.required} disabled={locked} step={f.type === 'number' ? 'any' : undefined} />
                  )}
                </Field>
              </div>
            )
          })}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Modal>
  )
}
