import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowLeft, ArrowUp, Info, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Badge, Field, PageHead, SelectInput, TextInput } from '../../components/ui'
import { ApiError, api } from '../../services/api'
import { lookupOptions, useLookups } from '../../services/lookups'
import { useAuth } from '../auth/AuthContext'
import { AssignmentPicker, SmsPreviewCard } from './AssignmentPicker'
import { fromLocalInput, nowLocalInput, toLocalInput, type Trip } from './shared'

interface Emp { id: number; name: string; code?: string; mobile?: string; gender?: string; address: string | null }
interface Customer { id: number; vendor_id: number; name: string }

const useDebounced = <T,>(v: T, ms = 300) => {
  const [d, setD] = useState(v)
  useEffect(() => { const h = setTimeout(() => setD(v), ms); return () => clearTimeout(h) }, [v, ms])
  return d
}

/**
 * Create / edit a trip.
 *  - Operator: sends a REQUEST (customer, site, time, employees, addresses). No driver or vehicle: a Vendor Admin assigns those.
 *  - Vendor Admin / Super Admin: can create AND assign in one step. Editing a request never shows driver/vehicle (use Assign).
 */
export function TripFormPage() {
  const { id } = useParams()
  const editing = !!id
  const nav = useNavigate()
  const qc = useQueryClient()
  const { user } = useAuth()
  const { data: lk } = useLookups()
  const canAssign = user?.role === 'super_admin' || user?.role === 'vendor_admin'

  const mine = user?.role === 'operator' ? user.customer_id ?? null : null // an Operator works for one customer
  const [f, setF] = useState({ customer_id: mine ? String(mine) : '', site_id: '', trip_type_id: '', shift_id: '', start: '', end: '', route_name: '', special_instructions: '', pickup_address: '', drop_address: '' })
  const [selected, setSelected] = useState<Emp[]>([])
  const [driverId, setDriverId] = useState<number | null>(null)
  const [vehicleId, setVehicleId] = useState<number | null>(null)
  const [stale, setStale] = useState(false)
  const onStale = useCallback((s: boolean) => setStale(s), [])
  const [touchedAddr, setTouchedAddr] = useState(false)
  const [search, setSearch] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [banner, setBanner] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    const v = e.target.value
    setF((s) => ({ ...s, [k]: v, ...(k === 'customer_id' ? { site_id: '', shift_id: '' } : {}) }))
    if (k === 'customer_id') { setSelected([]); setDriverId(null); setVehicleId(null) }
  }

  // ----- load existing trip when editing
  const { data: existing } = useQuery({ queryKey: ['trip', id], queryFn: () => api<Trip>(`/trips/${id}`), enabled: editing })
  useEffect(() => {
    if (!existing) return
    setF({
      customer_id: String(existing.customer_id), site_id: String(existing.site_id), trip_type_id: String(existing.trip_type_id),
      shift_id: existing.shift_id ? String(existing.shift_id) : '', start: toLocalInput(existing.scheduled_start), end: toLocalInput(existing.scheduled_end),
      route_name: existing.route_name ?? '', special_instructions: existing.special_instructions ?? '',
      pickup_address: existing.pickup_address, drop_address: existing.drop_address,
    })
    setSelected(existing.passengers.map((p) => ({ id: p.employee_id, name: p.name, mobile: p.mobile, gender: p.gender, address: p.address })))
    setDriverId(existing.driver_id); setVehicleId(existing.vehicle_id); setTouchedAddr(true)
  }, [existing])

  // A request (new, or an existing one awaiting assignment) carries no driver/vehicle.
  const requestMode = !canAssign || (editing && existing?.status === 'scheduled')

  const { data: customers } = useQuery({ queryKey: ['customers', 'active'], queryFn: () => api<{ items: Customer[] }>('/customers?status=active&limit=200').then((r) => r.items) })
  const cid = f.customer_id
  const { data: sites } = useQuery({ queryKey: ['sites', cid], enabled: !!cid, queryFn: () => api<{ items: { id: number; name: string; city: string | null; address: string }[] }>(`/sites?customer_id=${cid}&status=active`).then((r) => r.items) })
  const { data: shifts } = useQuery({ queryKey: ['shifts', cid], enabled: !!cid, queryFn: () => api<{ items: { id: number; name: string; start_time: string; end_time: string }[] }>(`/shifts?customer_id=${cid}&status=active`).then((r) => r.items) })
  const q = useDebounced(search)
  const { data: empList } = useQuery({
    queryKey: ['emps', cid, q], enabled: !!cid,
    queryFn: () => api<{ items: { id: number; employee_code: string; first_name: string; last_name: string; mobile: string; gender: string; address: string | null }[] }>(`/employees?customer_id=${cid}&status=active&limit=50${q ? `&q=${encodeURIComponent(q)}` : ''}`)
      .then((r) => r.items.map((e): Emp => ({ id: e.id, name: `${e.first_name} ${e.last_name}`, code: e.employee_code, mobile: e.mobile, gender: e.gender, address: e.address }))),
  })

  const customer = customers?.find((c) => String(c.id) === cid)
  const validWindow = !!f.start && !!f.end && new Date(f.end) > new Date(f.start)
  const ready = !!customer && validWindow && selected.length > 0

  // ----- pickup/drop suggestions (only until the user edits them)
  const typeLabel = lk?.trip_type.find((t) => String(t.id) === f.trip_type_id)?.label
  const site = sites?.find((s) => String(s.id) === f.site_id)
  useEffect(() => {
    if (touchedAddr || editing) return
    if (typeLabel === 'Pickup') setF((s) => ({ ...s, pickup_address: selected[0]?.address ?? '', drop_address: site?.address ?? '' }))
    else if (typeLabel === 'Drop') setF((s) => ({ ...s, pickup_address: site?.address ?? '', drop_address: selected[selected.length - 1]?.address ?? '' }))
  }, [typeLabel, site, selected, touchedAddr, editing])

  const pickupD = useDebounced(f.pickup_address, 500)
  const dropD = useDebounced(f.drop_address, 500)

  const toggleEmp = (e: Emp) => setSelected((s) => (s.some((x) => x.id === e.id) ? s.filter((x) => x.id !== e.id) : [...s, e]))
  const move = (i: number, d: -1 | 1) => setSelected((s) => { const n = [...s]; [n[i], n[i + d]] = [n[i + d], n[i]]; return n })
  const hasFemale = selected.some((s) => s.gender === 'female')
  const seatsNeeded = selected.length + (hasFemale ? 1 : 0)
  const summary = useMemo(() => `${selected.length} passenger${selected.length === 1 ? '' : 's'}${hasFemale ? ' + 1 escort seat' : ''}`, [selected, hasFemale])

  // No booking in the past. When editing, an unchanged time is left alone (a trip may already be under way).
  const origStart = editing && existing ? toLocalInput(existing.scheduled_start) : null
  const origEnd = editing && existing ? toLocalInput(existing.scheduled_end) : null
  const minStart = f.start === origStart ? undefined : nowLocalInput()
  const startError = (v: string) => (v && v !== origStart && v < nowLocalInput() ? 'Start time cannot be in the past' : '')
  const endError = (start: string, v: string) =>
    !v ? '' : start && v <= start ? 'End time must be after the start time' : v < nowLocalInput() && v !== origEnd ? 'End time cannot be in the past' : ''
  // Shown under the field as soon as a past time is typed or picked; the form cannot be submitted until it is fixed.
  const onStart = (e: { target: { value: string } }) => {
    set('start')(e)
    setErrors((p) => ({ ...p, scheduled_start: startError(e.target.value), scheduled_end: f.end ? endError(e.target.value, f.end) : p.scheduled_end }))
  }
  const onEnd = (e: { target: { value: string } }) => {
    set('end')(e)
    setErrors((p) => ({ ...p, scheduled_end: endError(f.start, e.target.value) }))
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const se = startError(f.start), ee = endError(f.start, f.end)
    if (se || ee) { setErrors({ scheduled_start: se, scheduled_end: ee }); return }
    setBusy(true); setErrors({}); setBanner('')
    const payload: Record<string, unknown> = {
      customer_id: Number(f.customer_id), site_id: Number(f.site_id), trip_type_id: Number(f.trip_type_id),
      shift_id: f.shift_id ? Number(f.shift_id) : null,
      scheduled_start: f.start ? fromLocalInput(f.start) : null, scheduled_end: f.end ? fromLocalInput(f.end) : null,
      route_name: f.route_name || null, special_instructions: f.special_instructions || null,
      pickup_address: f.pickup_address, drop_address: f.drop_address,
      employee_ids: selected.map((s) => s.id),
    }
    if (!requestMode) { payload.driver_id = driverId; payload.vehicle_id = vehicleId }
    try {
      const t = await api<Trip>(editing ? `/trips/${id}` : '/trips', { method: editing ? 'PUT' : 'POST', body: JSON.stringify(payload) })
      qc.invalidateQueries({ queryKey: ['trips'] }); qc.invalidateQueries({ queryKey: ['trip'] }); qc.invalidateQueries({ queryKey: ['dash'] })
      nav(`/trips/${t.id}`)
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors)
        setBanner(Object.keys(err.fieldErrors).length ? 'Please fix the highlighted items.' : err.message)
        if (err.status === 409) { qc.invalidateQueries({ queryKey: ['av-drivers'] }); qc.invalidateQueries({ queryKey: ['av-vehicles'] }) }
        window.scrollTo({ top: 0, behavior: 'smooth' })
      } else setBanner('Something went wrong. Please try again.')
    } finally { setBusy(false) }
  }

  const locked = editing && existing && existing.status === 'started'
  const blocked = editing && existing && !existing.can_edit && !locked
  const forWho = mine && user?.customer_name ? ` for ${user.customer_name}` : ''
  const title = editing ? `Edit ${existing?.code ?? 'trip'}` : requestMode ? `Request a trip${forWho}` : 'Create & assign trip'
  const subtitle = requestMode
    ? (mine ? 'Choose the time and employees.' : 'Choose the customer, time and employees.') + ' A Vendor Admin will assign the driver and vehicle.'
    : 'Choose passengers and time first, then pick from the available drivers and vehicles.'
  const startIso = f.start ? fromLocalInput(f.start) : ''
  const endIso = f.end ? fromLocalInput(f.end) : ''

  if (blocked) {
    return (
      <>
        <p style={{ margin: '0 0 8px' }}><Link to="/trips"><ArrowLeft size={14} /> Trips</Link></p>
        <PageHead title={title} />
        <div className="alert alert-warning">This trip can no longer be changed by you{user?.role === 'operator' ? ' — a Vendor Admin has already assigned it. Ask them to make the change.' : '.'}</div>
      </>
    )
  }

  return (
    <form onSubmit={submit}>
      <p style={{ margin: '0 0 8px' }}><Link to="/trips"><ArrowLeft size={14} /> Trips</Link></p>
      <PageHead title={title} subtitle={subtitle} />
      {user?.role === 'operator' && !mine && <div className="alert alert-warning">Your account is not linked to a customer yet, so you cannot request trips. Ask your administrator to assign one.</div>}
      {banner && <div className="alert alert-danger" role="alert">{banner}</div>}
      {locked && <div className="alert alert-warning">This trip has started. Only the instructions can be changed.</div>}

      <fieldset disabled={!!locked} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        <div className="card section">
          <h2>Trip information</h2>
          <div className="form-grid">
            {!mine && (
              <Field label="Customer *" error={errors.customer_id}>
                <SelectInput value={f.customer_id} onChange={set('customer_id')} required disabled={editing}>
                  <option value="">Select customer</option>{customers?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </SelectInput>
              </Field>
            )}
            <Field label="Site / office *" error={errors.site_id} hint={!cid ? 'Select a customer first' : undefined}>
              <SelectInput value={f.site_id} onChange={set('site_id')} required disabled={!cid}>
                <option value="">Select site</option>{sites?.map((s) => <option key={s.id} value={s.id}>{s.name}{s.city ? ` — ${s.city}` : ''}</option>)}
              </SelectInput>
            </Field>
            <Field label="Trip type *" error={errors.trip_type_id}>
              <SelectInput value={f.trip_type_id} onChange={set('trip_type_id')} required>
                <option value="">Select type</option>{lookupOptions(lk, 'trip_type').map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </SelectInput>
            </Field>
            <Field label="Shift" error={errors.shift_id}>
              <SelectInput value={f.shift_id} onChange={set('shift_id')} disabled={!cid}>
                <option value="">No shift</option>{shifts?.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)})</option>)}
              </SelectInput>
            </Field>
            <Field label="Start Trip *" error={errors.scheduled_start}><TextInput type="datetime-local" value={f.start} onChange={onStart} min={minStart} required
              onInvalid={(e) => { if (e.currentTarget.validity.rangeUnderflow) { e.preventDefault(); setErrors((p) => ({ ...p, scheduled_start: startError(f.start) })) } }} /></Field>
            <Field label="End Trip *" error={errors.scheduled_end} hint="Needed to check driver and vehicle availability"><TextInput type="datetime-local" value={f.end} onChange={onEnd} min={f.start || minStart} required
              onInvalid={(e) => { if (e.currentTarget.validity.rangeUnderflow) { e.preventDefault(); setErrors((p) => ({ ...p, scheduled_end: endError(f.start, f.end) })) } }} /></Field>
            <Field label="Route name"><TextInput value={f.route_name} onChange={set('route_name')} /></Field>
          </div>
        </div>

        <div className="card section">
          <h2>Employees</h2>
          {errors.employee_ids && <div className="alert alert-danger">{errors.employee_ids}</div>}
          {!cid ? <p className="muted">Select a customer to choose employees.</p> : (
            <div className="grid-2">
              <div>
                <input className="input" placeholder="Search employees by name, ID or mobile" aria-label="Search employees" value={search} onChange={(e) => setSearch(e.target.value)} />
                <div className="pick" style={{ marginTop: 10, maxHeight: 280, overflowY: 'auto' }}>
                  {empList?.map((e) => (
                    <label key={e.id} className={`pick-row ${selected.some((s) => s.id === e.id) ? 'on' : ''}`}>
                      <input type="checkbox" checked={selected.some((s) => s.id === e.id)} onChange={() => toggleEmp(e)} />
                      <span><strong>{e.name}</strong> <span className="muted">{e.code}</span><br /><span className="muted">{e.mobile} · {e.gender}</span></span>
                    </label>
                  ))}
                  {empList && !empList.length && <p className="muted">No employees found. {user?.role === 'operator' && <Link to="/employees">Add an employee</Link>}</p>}
                </div>
              </div>
              <div>
                <strong>Selected ({summary})</strong>
                {!selected.length && <p className="muted">Nobody selected yet.</p>}
                <ol style={{ paddingLeft: 20, display: 'grid', gap: 8 }}>
                  {selected.map((s, i) => (
                    <li key={s.id}>
                      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                        {s.name} {s.gender === 'female' && <Badge tone="info">Female</Badge>}
                        <button type="button" className="btn" style={{ height: 28, padding: '0 6px' }} disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up"><ArrowUp size={13} /></button>
                        <button type="button" className="btn" style={{ height: 28, padding: '0 6px' }} disabled={i === selected.length - 1} onClick={() => move(i, 1)} aria-label="Move down"><ArrowDown size={13} /></button>
                        <button type="button" className="btn" style={{ height: 28, padding: '0 6px' }} onClick={() => toggleEmp(s)} aria-label={`Remove ${s.name}`}><X size={13} /></button>
                      </span>
                    </li>
                  ))}
                </ol>
                {hasFemale && <div className="alert alert-warning">A female employee is on this trip, so <strong>one extra seat is reserved for an escort</strong>.</div>}
              </div>
            </div>
          )}
        </div>

        <div className="card section">
          <h2>Pickup & drop</h2>
          <div className="form-grid">
            <Field label="Pickup address *" error={errors.pickup_address}><textarea className="input" style={{ height: 70, padding: 10 }} value={f.pickup_address} onChange={(e) => { setTouchedAddr(true); set('pickup_address')(e) }} required /></Field>
            <Field label="Drop address *" error={errors.drop_address}><textarea className="input" style={{ height: 70, padding: 10 }} value={f.drop_address} onChange={(e) => { setTouchedAddr(true); set('drop_address')(e) }} required /></Field>
          </div>
        </div>

        {requestMode ? (
          <div className="card section" style={{ background: 'var(--brand-50)' }}>
            <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Info size={18} aria-hidden /> What happens next</h2>
            <ol style={{ margin: 0, paddingLeft: 20, display: 'grid', gap: 6 }}>
              <li>Your request goes to the Vendor Admin{selected.length > 0 && <> — it needs <strong>{seatsNeeded} seat{seatsNeeded === 1 ? '' : 's'}</strong> ({summary})</>}.</li>
              <li>They pick an available driver and vehicle for these times.</li>
              <li>Only then is the trip confirmed, and the driver and employees get an SMS.</li>
            </ol>
            <p className="muted" style={{ marginBottom: 0 }}>Until it is assigned you can still edit or cancel this request.</p>
          </div>
        ) : (
          <div className="card section">
            <h2>Driver & vehicle</h2>
            <AssignmentPicker vendorId={customer?.vendor_id} start={startIso} end={endIso} employeeIds={selected.map((s) => s.id)}
              excludeTripId={editing ? Number(id) : undefined} driverId={driverId} vehicleId={vehicleId}
              onDriver={setDriverId} onVehicle={setVehicleId} errors={errors} onStale={onStale} />
          </div>
        )}
      </fieldset>

      <div className="card section">
        <h2>Special instructions</h2>
        <textarea className="input" style={{ height: 70, padding: 10 }} value={f.special_instructions} onChange={set('special_instructions')} placeholder="Optional notes for the driver" />
      </div>

      {!requestMode && !editing && (
        <SmsPreviewCard intro="These SMS are sent when you create the trip:" enabled={ready && !!f.site_id && !!f.trip_type_id && !!pickupD && !!dropD}
          body={{ customer_id: Number(cid), site_id: Number(f.site_id), trip_type_id: Number(f.trip_type_id), scheduled_start: startIso, pickup_address: pickupD, drop_address: dropD, employee_ids: selected.map((s) => s.id), driver_id: driverId, vehicle_id: vehicleId }} />
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 32 }}>
        <button type="button" className="btn" onClick={() => nav(-1)}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || (!locked && (!selected.length || (!requestMode && (!driverId || !vehicleId || stale))))}>
          {busy ? 'Saving…' : editing ? 'Save changes' : requestMode ? 'Send request' : 'Create & assign trip'}
        </button>
      </div>
    </form>
  )
}
