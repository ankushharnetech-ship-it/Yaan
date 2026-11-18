import { useState, type FormEvent } from 'react'
import { Badge, Field, Modal } from '../../components/ui'
import { ApiError, api } from '../../services/api'

/** none = no OTP yet (a request) | pending = waiting to be dropped | verified = OTP confirmed | not_dropped = driver skipped them */
export type DropStatus = 'none' | 'pending' | 'verified' | 'not_dropped'
export interface Passenger {
  employee_id: number; sequence: number; name: string; mobile?: string; gender?: string; address: string | null
  drop_status: DropStatus; otp_locked: boolean; otp_verified_at: string | null; not_dropped_at: string | null; not_dropped_reason: string | null
  /** present ONLY for the Operator who requested the trip, while the employee is still to be dropped */
  otp?: string
}
export interface Trip {
  id: number; code: string; status: TripStatus; vendor_id: number; customer_id: number; customer_name: string; site_id: number; site_name: string
  trip_type_id: number; trip_type: string; shift_id: number | null; shift_name: string | null
  scheduled_start: string; scheduled_end: string; route_name: string | null; special_instructions: string | null
  pickup_address: string; drop_address: string; passenger_count: number; escort_required: boolean; required_capacity: number
  passengers: Passenger[]; sms_status: 'pending' | 'sent' | 'delivered' | 'failed' | null; notify_status: 'pending' | 'sent' | 'failed' | null
  drops_resolved: number; created_by_id: number
  /** null while the trip is a request awaiting a Vendor Admin's assignment */
  driver_id: number | null; driver_name: string | null; driver_contact: string | null
  vehicle_id: number | null; vehicle_number: string | null; vehicle_capacity: number | null; created_by: string
  /** what the signed-in user may do next (the API enforces it) */
  can_assign: boolean; can_edit: boolean; can_cancel: boolean
  accepted_at: string | null; started_at: string | null; completed_at: string | null
  cancelled_at: string | null; cancelled_by: string | null; cancellation_reason: string | null
  history?: { from: string | null; to: string; by: string; at: string; note: string | null }[]
}
// "scheduled" = a request from an Operator that is waiting for a Vendor Admin to assign a driver and vehicle.
export type TripStatus = 'scheduled' | 'assigned' | 'accepted' | 'started' | 'completed' | 'cancelled'

export const STATUS_LABEL: Record<TripStatus, string> = {
  scheduled: 'Awaiting assignment', assigned: 'Assigned', accepted: 'Accepted', started: 'Ongoing', completed: 'Completed', cancelled: 'Cancelled',
}
const TONE: Record<TripStatus, 'success' | 'warning' | 'danger' | 'info' | 'neutral'> = {
  scheduled: 'warning', assigned: 'info', accepted: 'info', started: 'warning', completed: 'success', cancelled: 'danger',
}
export const TripStatusBadge = ({ status }: { status: TripStatus }) => <Badge tone={TONE[status]}>{STATUS_LABEL[status]}</Badge>

export const fmtDate = (iso: string) => new Date(iso).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
export const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
export const fmtDateTime = (iso: string) => `${fmtDate(iso)}, ${fmtTime(iso)}`
export const DROP_LABEL: Record<DropStatus, string> = { none: '—', pending: 'Waiting', verified: 'Dropped', not_dropped: 'Not dropped' }
export const isOpen = (s: TripStatus) => s === 'scheduled' || s === 'assigned' || s === 'accepted'

/** `datetime-local` string (browser local time) <-> ISO instant */
export const toLocalInput = (iso: string) => {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}
/** Current minute as a `datetime-local` value — the earliest start a trip may be booked for. */
export const nowLocalInput = () => toLocalInput(new Date().toISOString())
export const fromLocalInput = (v: string) => new Date(v).toISOString()

/** Cancels a trip. With `reject`, the same call is presented as rejecting an Operator's request. */
export function CancelTripModal({ trip, onClose, onDone, reject }: { trip: Pick<Trip, 'id' | 'code'>; onClose: () => void; onDone: () => void; reject?: boolean }) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      await api(`/trips/${trip.id}/cancel`, { method: 'POST', body: JSON.stringify({ reason }) })
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.fieldErrors.reason ?? err.message : `Could not ${reject ? 'reject the request' : 'cancel the trip'}`)
    } finally { setBusy(false) }
  }
  return (
    <Modal title={reject ? `Reject ${trip.code}?` : `Cancel ${trip.code}?`} onClose={onClose}>
      <form onSubmit={submit}>
        <p className="muted" style={{ marginTop: 0 }}>
          {reject ? 'The Operator will see your reason. No SMS is sent, because nobody has been notified about this request yet.'
            : 'The trip stays in history. The driver and vehicle become free for other trips.'}
        </p>
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        <Field label={reject ? 'Reason for rejecting *' : 'Reason for cancellation *'}>
          <textarea className="input" style={{ height: 80, padding: 10 }} value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} autoFocus />
        </Field>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>{reject ? 'Keep request' : 'Keep trip'}</button>
          <button className="btn btn-danger" disabled={busy || reason.trim().length < 3}>
            {busy ? (reject ? 'Rejecting…' : 'Cancelling…') : reject ? 'Reject request' : 'Cancel trip'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
