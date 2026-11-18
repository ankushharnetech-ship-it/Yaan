import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, UserCheck, XCircle } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Badge, PageHead } from '../../components/ui'
import { ApiError, api } from '../../services/api'
import { AssignmentPicker, SmsPreviewCard } from './AssignmentPicker'
import { CancelTripModal, fmtDateTime, isOpen, TripStatusBadge, type Trip } from './shared'

/** Vendor Admin: pick an available driver and vehicle for an Operator's request (or change them later). */
export function TripAssignPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const { data: t, isLoading, isError } = useQuery({ queryKey: ['trip', id], queryFn: () => api<Trip>(`/trips/${id}`) })
  const [driverId, setDriverId] = useState<number | null>(null)
  const [vehicleId, setVehicleId] = useState<number | null>(null)
  const [stale, setStale] = useState(false)
  const onStale = useCallback((s: boolean) => setStale(s), [])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [banner, setBanner] = useState('')
  const [busy, setBusy] = useState(false)
  const [rejecting, setRejecting] = useState(false)

  useEffect(() => { if (t) { setDriverId(t.driver_id); setVehicleId(t.vehicle_id) } }, [t?.id, t?.driver_id, t?.vehicle_id]) // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading) return <p className="muted">Loading…</p>
  if (isError || !t) return <div className="alert alert-danger">Trip not found. <Link to="/trips">Back to trips</Link></div>
  const isRequest = t.status === 'scheduled'
  if (!isOpen(t.status) || !t.can_assign) {
    return (
      <>
        <p style={{ margin: '0 0 8px' }}><Link to={`/trips/${t.id}`}><ArrowLeft size={14} /> {t.code}</Link></p>
        <div className="alert alert-warning">This trip is {t.status} and can't be assigned{t.can_assign ? '' : ' by you'}.</div>
      </>
    )
  }
  const females = t.passengers.filter((p) => p.gender === 'female').length

  const submit = async () => {
    setBusy(true); setErrors({}); setBanner('')
    try {
      await api(`/trips/${t.id}/assign`, { method: 'POST', body: JSON.stringify({ driver_id: driverId, vehicle_id: vehicleId }) })
      qc.invalidateQueries({ queryKey: ['trips'] }); qc.invalidateQueries({ queryKey: ['trip'] }); qc.invalidateQueries({ queryKey: ['dash'] })
      nav(`/trips/${t.id}`)
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors)
        setBanner(Object.keys(err.fieldErrors).length ? 'That choice can no longer be used. Please pick again.' : err.message)
        if (err.status === 409) { qc.invalidateQueries({ queryKey: ['av-drivers'] }); qc.invalidateQueries({ queryKey: ['av-vehicles'] }) }
      } else setBanner('Something went wrong. Please try again.')
    } finally { setBusy(false) }
  }

  return (
    <>
      <p style={{ margin: '0 0 8px' }}><Link to={isRequest ? '/trips?view=awaiting' : `/trips/${t.id}`}><ArrowLeft size={14} /> {isRequest ? 'Awaiting assignment' : t.code}</Link></p>
      <PageHead title={isRequest ? `Assign ${t.code}` : `Change driver / vehicle — ${t.code}`}
        subtitle={isRequest ? `Requested by ${t.created_by}. Once you assign, the trip is confirmed and the driver and employees are notified.` : 'Reassigning re-checks availability and capacity.'}
        actions={<TripStatusBadge status={t.status} />} />
      {banner && <div className="alert alert-danger" role="alert">{banner}</div>}

      <div className="card section">
        <h2>Request</h2>
        <dl className="kv">
          <dt>Customer</dt><dd>{t.customer_name} · {t.site_name} · {t.trip_type}</dd>
          <dt>When</dt><dd>{fmtDateTime(t.scheduled_start)} → {fmtDateTime(t.scheduled_end)}</dd>
          <dt>Route</dt><dd>{t.pickup_address} → {t.drop_address}</dd>
          <dt>Employees</dt><dd>{t.passengers.map((p) => p.name).join(', ')}</dd>
          <dt>Seats needed</dt>
          <dd><strong>{t.required_capacity}</strong> ({t.passenger_count} employee{t.passenger_count > 1 ? 's' : ''}{t.escort_required ? ' + 1 escort seat' : ''}) {females > 0 && <Badge tone="info">Female employee on board</Badge>}</dd>
          {t.special_instructions && <><dt>Instructions</dt><dd>{t.special_instructions}</dd></>}
        </dl>
      </div>

      <div className="card section">
        <h2>Driver & vehicle</h2>
        <AssignmentPicker vendorId={t.vendor_id} start={t.scheduled_start} end={t.scheduled_end} employeeIds={t.passengers.map((p) => p.employee_id)}
          excludeTripId={t.id} driverId={driverId} vehicleId={vehicleId} onDriver={setDriverId} onVehicle={setVehicleId} errors={errors} onStale={onStale} />
      </div>

      {isRequest && (
        <SmsPreviewCard intro="These SMS are sent as soon as you assign:" enabled
          body={{ customer_id: t.customer_id, site_id: t.site_id, trip_type_id: t.trip_type_id, scheduled_start: t.scheduled_start, pickup_address: t.pickup_address, drop_address: t.drop_address, employee_ids: t.passengers.map((p) => p.employee_id), driver_id: driverId, vehicle_id: vehicleId }} />
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 32, flexWrap: 'wrap' }}>
        <div>{isRequest && t.can_cancel && <button type="button" className="btn" onClick={() => setRejecting(true)}><XCircle size={16} /> Reject request</button>}</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="btn" onClick={() => nav(-1)}>Back</button>
          <button type="button" className="btn btn-primary" disabled={busy || !driverId || !vehicleId || stale || (!isRequest && driverId === t.driver_id && vehicleId === t.vehicle_id)} onClick={submit}>
            <UserCheck size={16} /> {busy ? 'Assigning…' : isRequest ? 'Assign & notify' : 'Save change'}
          </button>
        </div>
      </div>
      {rejecting && <CancelTripModal reject trip={t} onClose={() => setRejecting(false)}
        onDone={() => { setRejecting(false); qc.invalidateQueries({ queryKey: ['trips'] }); qc.invalidateQueries({ queryKey: ['dash'] }); nav('/trips?view=awaiting') }} />}
    </>
  )
}
