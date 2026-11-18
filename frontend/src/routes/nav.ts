import {
  BarChart3, Building2, Bus, CalendarClock, ClipboardCheck, LayoutDashboard, MessageSquare,
  Settings, ShieldCheck, UserCog, Users, UsersRound, Wallet, type LucideIcon,
} from 'lucide-react'
import type { Role } from '../types'

export interface NavItem { label: string; to: string; icon: LucideIcon; roles: Role[] }

const ADMINS: Role[] = ['super_admin', 'vendor_admin']
const OPS: Role[] = ['super_admin', 'vendor_admin', 'operator']

/** Mirrors spec section 4. UI only – the backend enforces real access. */
export const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', to: '/dashboard', icon: LayoutDashboard, roles: OPS },
  { label: 'Trips', to: '/trips', icon: CalendarClock, roles: [...OPS, 'driver'] },
  { label: 'Expenses', to: '/expenses', icon: Wallet, roles: ['super_admin', 'vendor_admin', 'operator', 'driver'] },
  { label: 'Reports', to: '/reports', icon: BarChart3, roles: OPS },
  { label: 'Vehicles', to: '/vehicles', icon: Bus, roles: ADMINS },
  { label: 'Drivers', to: '/drivers', icon: UserCog, roles: ADMINS },
  { label: 'Customers', to: '/customers', icon: Building2, roles: ADMINS },
  { label: 'Employees', to: '/employees', icon: Users, roles: OPS }, // Operators add/edit employees of their vendor
  { label: 'Vendors', to: '/vendors', icon: ShieldCheck, roles: ['super_admin'] },
  { label: 'Compliance', to: '/compliance', icon: ClipboardCheck, roles: [...OPS, 'driver'] },
  { label: 'Users', to: '/users', icon: UsersRound, roles: ADMINS },
  { label: 'Notifications', to: '/notifications', icon: MessageSquare, roles: [...OPS, 'driver'] },
  { label: 'Settings', to: '/settings', icon: Settings, roles: ADMINS },
]

export const navFor = (role: Role) => NAV_ITEMS.filter((i) => i.roles.includes(role))
