/** The parts of the YAAN API this app uses (mirrors the web app's types). */
export type Role = 'super_admin' | 'vendor_admin' | 'operator' | 'driver'

export interface Me {
  id: number; username: string; first_name: string; last_name: string; email: string
  role: Role; vendor_id: number | null; must_change_password: boolean
}
export interface LoginResponse { access_token: string; user: Me }

/** none = no OTP yet | pending = waiting to be dropped | verified = OTP confirmed | not_dropped = driver skipped them */
export type DropStatus = 'none' | 'pending' | 'verified' | 'not_dropped'
export interface Passenger {
  employee_id: number; sequence: number; name: string; mobile?: string; gender?: string; address: string | null
  drop_status: DropStatus; otp_locked: boolean; otp_verified_at: string | null; not_dropped_at: string | null; not_dropped_reason: string | null
}
export type TripStatus = 'scheduled' | 'assigned' | 'accepted' | 'started' | 'completed' | 'cancelled'
export interface Trip {
  id: number; code: string; status: TripStatus; customer_name: string; site_name: string; trip_type: string
  scheduled_start: string; scheduled_end: string; special_instructions: string | null
  pickup_address: string; drop_address: string; passenger_count: number; escort_required: boolean
  passengers: Passenger[]; drops_resolved: number
  vehicle_number: string | null; started_at: string | null; completed_at: string | null
}
