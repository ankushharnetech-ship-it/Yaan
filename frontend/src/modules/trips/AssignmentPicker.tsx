import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Mail, Phone } from 'lucide-react'
import { useEffect } from 'react'
import { Badge } from '../../components/ui'
import { api } from '../../services/api'

interface Reason { code: string; message: string }
interface DriverAv { id: number; code: string; name: string; contact_number: string; available: boolean; reasons: Reason[] }
interface VehicleAv { id: number; vehicle_number: string; model: string; vehicle_type: string; capacity: number; available: boolean; reasons: Reason[] }

export interface PickerProps {
  vendorId?: number
  start: string // ISO instants
  end: string
  employeeIds: number[]
  excludeTripId?: number // when changing an existing trip, so it doesn't clash with itself
  driverId: number | null
  vehicleId: number | null
  onDriver: (id: number) => void
  onVehicle: (id: number) => void
  errors?: { driver_id?: string; vehicle_id?: string }
  onStale?: (stale: boolean) => void // true when the current choice stopped being available
}

/**
 * Shows every driver and vehicle of the vendor with live availability for the given time and passengers
 * (30-minute gap, capacity incl. escort seat) and the reason for anything unavailable. Used by the Vendor Admin when
 * creating a trip directly and when assigning an Operator's request.
 */
export function AssignmentPicker(p: PickerProps) {
  const valid = !!p.start && !!p.end && new Date(p.end) > new Date(p.start)
  const ready = !!p.vendorId && valid && p.employeeIds.length > 0
  const base = `start=${encodeURIComponent(p.start)}&end=${encodeURIComponent(p.end)}&vendor_id=${p.vendorId ?? ''}${p.excludeTripId ? `&exclude_trip_id=${p.excludeTripId}` : ''}`
  const { data: drivers, isFetching: dLoading } = useQuery({
    queryKey: ['av-drivers', base], enabled: ready,
    queryFn: () => api<{ items: DriverAv[] }>(`/drivers/availability?${base}`).then((r) => r.items),
  })
  const { data: vehRes, isFetching: vLoading } = useQuery({
    queryKey: ['av-vehicles', base, p.employeeIds.join()], enabled: ready,
    queryFn: () => api<{ passenger_count: number; escort_required: boolean; required_capacity: number; items: VehicleAv[] }>(`/vehicles/availability?${base}&employee_ids=${p.employeeIds.join(',')}`),
  })
  const selDriver = drivers?.find((d) => d.id === p.driverId)
  const selVehicle = vehRes?.items.find((v) => v.id === p.vehicleId)
  const stale = (!!selDriver && !selDriver.available) || (!!selVehicle && !selVehicle.available)
  const { onStale } = p
  useEffect(() => { onStale?.(stale) }, [stale, onStale])

  if (!ready) return <p className="muted">Choose a customer, a valid start/end time and at least one passenger to see who is available.</p>
  return (
    <>
      {vehRes && (
        <div className="alert alert-success" style={{ background: 'var(--brand-50)', color: 'var(--brand-700)' }}>
          Seats required: <strong>{vehRes.required_capacity}</strong> ({vehRes.passenger_count} passenger{vehRes.passenger_count > 1 ? 's' : ''}{vehRes.escort_required ? ' + 1 escort seat' : ''}).
          Drivers and vehicles need a 30-minute gap between trips.
        </div>
      )}
      {stale && <div className="alert alert-danger" role="alert"><AlertTriangle size={14} /> Your selected {selDriver && !selDriver.available ? 'driver' : 'vehicle'} is no longer available for these details. Pick another.</div>}
      <div className="grid-2">
        <div>
          <strong>Driver {dLoading && <span className="muted">· checking…</span>}</strong>
          {p.errors?.driver_id && <div className="error-text" role="alert">{p.errors.driver_id}</div>}
          <div className="pick" style={{ marginTop: 8 }}>
            {drivers?.map((d) => (
              <label key={d.id} className={`pick-row ${p.driverId === d.id ? 'on' : ''} ${!d.available ? 'off' : ''}`}>
                <input type="radio" name="driver" checked={p.driverId === d.id} disabled={!d.available} onChange={() => p.onDriver(d.id)} />
                <span><strong>{d.name}</strong> <span className="muted">{d.code}</span><br /><span className="muted"><Phone size={12} /> {d.contact_number}</span>
                  {d.available ? <><br /><Badge tone="success">Available</Badge></> : d.reasons.map((r) => <div key={r.code} className="reason">{r.message}</div>)}</span>
              </label>
            ))}
            {drivers && !drivers.length && <p className="muted">This vendor has no drivers yet.</p>}
          </div>
        </div>
        <div>
          <strong>Vehicle {vLoading && <span className="muted">· checking…</span>}</strong>
          {p.errors?.vehicle_id && <div className="error-text" role="alert">{p.errors.vehicle_id}</div>}
          <div className="pick" style={{ marginTop: 8 }}>
            {vehRes?.items.map((v) => (
              <label key={v.id} className={`pick-row ${p.vehicleId === v.id ? 'on' : ''} ${!v.available ? 'off' : ''}`}>
                <input type="radio" name="vehicle" checked={p.vehicleId === v.id} disabled={!v.available} onChange={() => p.onVehicle(v.id)} />
                <span><strong>{v.vehicle_number}</strong> <span className="muted">{v.vehicle_type} · {v.model} · {v.capacity} seats</span>
                  {v.available ? <><br /><Badge tone="success">Available</Badge></> : v.reasons.map((r) => <div key={r.code} className="reason">{r.message}</div>)}</span>
              </label>
            ))}
            {vehRes && !vehRes.items.length && <p className="muted">This vendor has no vehicles yet.</p>}
          </div>
        </div>
      </div>
    </>
  )
}

/** The exact SMS that will go to the driver and passengers once the trip is assigned. */
export function SmsPreviewCard({ enabled, body, intro }: {
  enabled: boolean; intro: string
  body: { customer_id: number; site_id: number; trip_type_id: number; scheduled_start: string; pickup_address: string; drop_address: string; employee_ids: number[]; driver_id: number | null; vehicle_id: number | null }
}) {
  const { data: preview } = useQuery({
    queryKey: ['sms-preview', JSON.stringify(body)], enabled: enabled && !!body.driver_id && !!body.vehicle_id,
    queryFn: () => api<{ messages: { recipient: string; type: string; phone: string | null; email?: string | null; message: string }[]; channels: { sms: boolean; email: boolean } }>('/trips/sms-preview', { method: 'POST', body: JSON.stringify(body) }),
  })
  return (
    <div className="card section">
      <h2>SMS preview</h2>
      {!preview ? <p className="muted" style={{ margin: 0 }}>Choose a driver and a vehicle to preview the messages that will be sent.</p> : (
        <>
          <p className="muted" style={{ marginTop: 0 }}>{intro}</p>
          {!preview.channels.sms && !preview.channels.email
            ? <div className="alert alert-warning"><strong>Notifications are switched off for this vendor</strong> (Settings), so nothing will be sent. Each employee's OTP will not reach them; the requesting Operator can still read it out.</div>
            : <p style={{ marginTop: 0 }}>Will be sent by <strong>{preview.channels.sms && preview.channels.email ? 'SMS and Email' : preview.channels.sms ? 'SMS' : 'Email'}</strong>. Each employee's own OTP replaces the dots (••••) when it is sent.</p>}
          <div style={{ display: 'grid', gap: 10 }}>
            {preview.messages.map((m, i) => (
              <div key={i} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                  <strong>{m.recipient} <span className="muted" style={{ fontWeight: 400 }}>· {m.type === 'driver' ? 'Driver' : 'Passenger'}</span></strong>
                  <span style={{ display: 'inline-flex', gap: 10, flexWrap: 'wrap' }}>
                    {preview.channels.sms && (m.phone ? <span className="muted"><Phone size={12} /> {m.phone}</span> : <Badge tone="danger">No valid phone number</Badge>)}
                    {preview.channels.email && (m.email ? <span className="muted"><Mail size={12} /> {m.email}</span> : <Badge tone="danger">No email address</Badge>)}
                  </span>
                </div>
                <div style={{ marginTop: 6, fontSize: 13.5 }}>{m.message}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
