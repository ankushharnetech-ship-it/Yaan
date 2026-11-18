import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, KeyRound, Lock, Map as MapIcon, MapPin, Play, ThumbsUp, UserX, Users } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Badge, PageHead } from '../../components/ui'
import { ApiError, api } from '../../services/api'
import { TripMapModal } from './TripMapModal'
import { fmtDate, fmtTime, TripStatusBadge, type Passenger, type Trip } from './shared'

const NEXT = {
  assigned: { to: 'accepted', label: 'Accept trip', icon: ThumbsUp },
  scheduled: { to: 'accepted', label: 'Accept trip', icon: ThumbsUp },
  accepted: { to: 'started', label: 'Start trip', icon: Play },
  started: { to: 'completed', label: 'End trip', icon: CheckCircle2 },
} as const

const dayKey = (iso: string) => new Date(iso).toLocaleDateString('en-CA') // local YYYY-MM-DD

/** While a trip is started, send this device's position to the server (on every movement, at most every 5s). */
function useShareLocation(tripIds: number[]) {
  const key = tripIds.join(',')
  const [denied, setDenied] = useState(false)
  useEffect(() => {
    if (!key || !('geolocation' in navigator)) return
    let pos: { latitude: number; longitude: number } | null = null
    const send = () => { if (pos) key.split(',').forEach((t) => api(`/trips/${t}/location`, { method: 'POST', body: JSON.stringify(pos) }).catch(() => {})) }
    const id = navigator.geolocation.watchPosition(
      (p) => { setDenied(false); const first = !pos; pos = { latitude: p.coords.latitude, longitude: p.coords.longitude }; if (first) send() },
      (err) => { if (err.code === err.PERMISSION_DENIED) setDenied(true) },
      { enableHighAccuracy: true, maximumAge: 5000 },
    )
    const timer = setInterval(send, 5000) // keep the "last seen" fresh even when the device is stationary
    return () => { navigator.geolocation.clearWatch(id); clearInterval(timer) }
  }, [key])
  return denied
}

/** One employee at the drop point: the driver types the OTP the employee reads out. */
function DropRow({ tripId, p, onChanged }: { tripId: number; p: Passenger; onChanged: () => void }) {
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [skipping, setSkipping] = useState(false)
  const [reason, setReason] = useState('')
  const base = `/trips/${tripId}/passengers/${p.employee_id}`
  const verify = useMutation({
    mutationFn: () => api(`${base}/verify-otp`, { method: 'POST', body: JSON.stringify({ otp: code }) }),
    onSuccess: () => { setError(''); setCode(''); onChanged() },
    onError: (e) => { setError(e instanceof ApiError ? e.fieldErrors.otp ?? e.message : 'Could not verify'); setCode(''); onChanged() },
  })
  const skip = useMutation({
    mutationFn: () => api(`${base}/not-dropped`, { method: 'POST', body: JSON.stringify({ reason }) }),
    onSuccess: () => { setSkipping(false); setReason(''); setError(''); onChanged() },
    onError: (e) => setError(e instanceof ApiError ? e.fieldErrors.reason ?? e.message : 'Could not save'),
  })
  const submit = (e: FormEvent) => { e.preventDefault(); if (code.trim()) verify.mutate() }

  if (p.drop_status === 'verified') {
    return <div className="drop-row done"><strong>{p.name}</strong> <Badge tone="success"><CheckCircle2 size={12} style={{ marginRight: 4 }} />Dropped</Badge></div>
  }
  if (p.drop_status === 'not_dropped') {
    return (
      <div className="drop-row skipped">
        <div><strong>{p.name}</strong> <Badge tone="danger"><UserX size={12} style={{ marginRight: 4 }} />Not dropped</Badge></div>
        <div className="reason">{p.not_dropped_reason}</div>
      </div>
    )
  }
  return (
    <div className="drop-row">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <strong>{p.name}</strong>
        {p.otp_locked ? <Badge tone="danger"><Lock size={12} style={{ marginRight: 4 }} />OTP locked</Badge> : <Badge tone="warning">Waiting</Badge>}
      </div>
      {p.address && <div className="muted" style={{ fontSize: 13 }}>{p.address}</div>}
      {!skipping && (
        <>
          {!p.otp_locked && (
            <form onSubmit={submit} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <input className="input otp-input" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]*" maxLength={8} placeholder="OTP"
                aria-label={`OTP from ${p.name}`} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />
              <button className="btn btn-primary" disabled={!code || verify.isPending}><KeyRound size={15} /> {verify.isPending ? 'Checking…' : 'Verify'}</button>
            </form>
          )}
          {p.otp_locked && <div className="reason">Too many wrong OTPs. If {p.name.split(' ')[0]} cannot share it, mark them as not dropped.</div>}
          {error && <div className="error-text" role="alert">{error}</div>}
          <button type="button" className="linkbtn" style={{ justifySelf: 'start', color: 'var(--danger)' }} onClick={() => { setSkipping(true); setError('') }}>
            Employee not dropped…
          </button>
        </>
      )}
      {skipping && (
        <div style={{ display: 'grid', gap: 8 }}>
          <label htmlFor={`why-${p.employee_id}`} style={{ fontWeight: 500, fontSize: 13 }}>Why was {p.name} not dropped? *</label>
          <textarea id={`why-${p.employee_id}`} className="input" style={{ height: 64, padding: 10 }} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus
            placeholder="e.g. Did not turn up, phone lost, asked to be left elsewhere" />
          {error && <div className="error-text" role="alert">{error}</div>}
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="btn" onClick={() => { setSkipping(false); setError('') }}>Back</button>
            <button type="button" className="btn btn-danger" disabled={reason.trim().length < 3 || skip.isPending} onClick={() => skip.mutate()}>Confirm not dropped</button>
          </div>
          <span className="muted" style={{ fontSize: 12.5 }}>This is reported to your Vendor Admin and the Operator.</span>
        </div>
      )}
    </div>
  )
}

export function DriverTripsPage() {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const [mapFor, setMapFor] = useState<Trip | null>(null)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['trips', 'mine'],
    queryFn: () => api<{ items: Trip[] }>('/trips?limit=200&view=all'),
    refetchInterval: 30_000, // pick up newly assigned trips
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['trips'] })
  const act = useMutation({
    mutationFn: ({ id, to }: { id: number; to: string }) => api(`/trips/${id}/status`, { method: 'POST', body: JSON.stringify({ status: to }) }),
    onSuccess: () => { setError(''); refresh() },
    onError: (e) => { setError(e instanceof ApiError ? e.fieldErrors.status ?? e.message : 'Could not update the trip'); refresh() },
  })

  const gpsDenied = useShareLocation((data?.items ?? []).filter((t) => t.status === 'started').map((t) => t.id))
  const today = dayKey(new Date().toISOString())
  const items = [...(data?.items ?? [])].sort((a, b) => +new Date(a.scheduled_start) - +new Date(b.scheduled_start))
  const open = items.filter((t) => t.status === 'assigned' || t.status === 'scheduled' || t.status === 'accepted')
  const groups: [string, Trip[]][] = [
    ['In progress', items.filter((t) => t.status === 'started')],
    ['Today', open.filter((t) => dayKey(t.scheduled_start) <= today)],
    ['Upcoming', open.filter((t) => dayKey(t.scheduled_start) > today)],
    ['Completed', items.filter((t) => t.status === 'completed').reverse().slice(0, 10)],
  ]

  return (
    <>
      <PageHead title="My trips" subtitle="Trips assigned to you." />
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {gpsDenied && <div className="alert alert-warning" role="alert">Location access is blocked, so your live position cannot be shared. Allow location for this site in the browser settings.</div>}
      {isLoading && <p className="muted">Loading…</p>}
      {isError && <div className="alert alert-danger">Could not load your trips.</div>}
      {data && !items.length && <div className="card muted">No trips assigned to you yet.</div>}
      {groups.map(([title, list]) => list.length > 0 && (
        <section key={title} style={{ marginBottom: 24 }}>
          <h2 style={{ marginBottom: 10 }}>{title} <span className="muted" style={{ fontWeight: 400 }}>({list.length})</span></h2>
          {list.map((t) => {
            const next = NEXT[t.status as keyof typeof NEXT]
            const started = t.status === 'started'
            const waiting = t.passengers.filter((p) => p.drop_status === 'pending' || p.drop_status === 'none').length
            const pct = t.passenger_count ? Math.round((t.drops_resolved / t.passenger_count) * 100) : 0
            const blocked = started && waiting > 0
            return (
              <article key={t.id} className="trip-card" aria-label={t.code}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                  <strong>{t.code}</strong><TripStatusBadge status={t.status} />
                </div>
                <div style={{ fontSize: 20, fontWeight: 650, margin: '6px 0 2px' }}>{fmtTime(t.scheduled_start)} – {fmtTime(t.scheduled_end)}</div>
                <div className="muted">{fmtDate(t.scheduled_start)} · {t.trip_type} · {t.customer_name}, {t.site_name}</div>
                <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
                  <div><MapPin size={14} /> <strong>Pickup:</strong> {t.pickup_address}</div>
                  <div><MapPin size={14} /> <strong>Drop:</strong> {t.drop_address}</div>
                  {!started && <div><Users size={14} /> <strong>{t.passenger_count} passenger{t.passenger_count > 1 ? 's' : ''}:</strong> {t.passengers.map((p) => p.name).join(', ')}</div>}
                  <div><strong>Vehicle:</strong> {t.vehicle_number}</div>
                  <button type="button" className="btn" style={{ justifySelf: 'start' }} onClick={() => setMapFor(t)}><MapIcon size={15} /> View route on map</button>
                  {t.special_instructions && <div className="alert alert-warning" style={{ margin: 0 }}>{t.special_instructions}</div>}
                </div>

                {started && (
                  <div style={{ marginTop: 14 }}>
                    <h3 style={{ fontSize: 15, marginBottom: 2 }}>Drop-offs · {t.drops_resolved} of {t.passenger_count} done</h3>
                    <div className="progress-line" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Drop-off progress"><div style={{ width: `${pct}%` }} /></div>
                    <p className="muted" style={{ margin: '0 0 10px', fontSize: 13 }}>At each drop point, ask the employee for their OTP and enter it. They received it by notification.</p>
                    <div style={{ display: 'grid', gap: 10 }}>
                      {t.passengers.map((p) => <DropRow key={p.employee_id} tripId={t.id} p={p} onChanged={refresh} />)}
                    </div>
                  </div>
                )}

                {next && (
                  <>
                    <button className={`btn big ${started ? 'btn-primary' : ''}`} style={!started ? { background: 'var(--brand-600)', color: '#fff', borderColor: 'var(--brand-600)' } : undefined}
                      disabled={act.isPending || blocked} aria-describedby={blocked ? `why-${t.id}` : undefined}
                      onClick={() => (next.to !== 'completed' || window.confirm('End this trip?')) && act.mutate({ id: t.id, to: next.to })}>
                      <next.icon size={18} /> {next.label}
                    </button>
                    {blocked && <p id={`why-${t.id}`} className="muted" style={{ margin: '8px 0 0', fontSize: 13 }}>You can end the trip once {waiting} more employee{waiting > 1 ? 's are' : ' is'} dropped (OTP verified) or marked not dropped.</p>}
                  </>
                )}
              </article>
            )
          })}
        </section>
      ))}
    {mapFor && <TripMapModal tripId={mapFor.id} code={mapFor.code} onClose={() => setMapFor(null)} />}
    </>
  )
}
