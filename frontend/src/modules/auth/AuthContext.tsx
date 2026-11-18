import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, tokenStore } from '../../services/api'
import type { AuthUser, Role } from '../../types'

export interface Me extends AuthUser { email: string; must_change_password: boolean }
interface LoginResponse { access_token: string; user: Me }

interface AuthState {
  user: Me | null
  loading: boolean
  login: (username: string, password: string) => Promise<Me>
  applySession: (r: LoginResponse) => void
  logout: () => Promise<void>
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null)
  const [loading, setLoading] = useState(!!tokenStore.get())

  useEffect(() => {
    if (!tokenStore.get()) return
    api<Me>('/auth/me')
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false))
  }, [])

  const applySession = useCallback((r: LoginResponse) => {
    tokenStore.set(r.access_token)
    setUser(r.user)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const r = await api<LoginResponse>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
    applySession(r)
    return r.user
  }, [applySession])

  const logout = useCallback(async () => {
    try { await api('/auth/logout', { method: 'POST' }) } catch { /* token may already be invalid */ }
    tokenStore.clear()
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, loading, login, applySession, logout }), [user, loading, login, applySession, logout])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth() {
  const c = useContext(Ctx)
  if (!c) throw new Error('useAuth outside AuthProvider')
  return c
}

export const homeFor = (role: Role) => (role === 'driver' ? '/trips' : '/dashboard')
