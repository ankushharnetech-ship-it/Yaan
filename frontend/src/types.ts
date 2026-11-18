export type Role = 'super_admin' | 'vendor_admin' | 'operator' | 'driver'

export const ROLE_LABELS: Record<Role, string> = {
  super_admin: 'Super Admin',
  vendor_admin: 'Vendor Admin',
  operator: 'Operator',
  driver: 'Driver',
}

export interface AuthUser {
  id: number
  username: string
  first_name: string
  last_name: string
  role: Role
  vendor_id: number | null
  customer_id?: number | null // Operators only: the customer they work for
  customer_name?: string | null
}
