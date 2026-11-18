import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError, api, setUnauthorizedHandler, tokenStore } from './api'
import type { LoginResponse, Me } from './types'

interface AuthState {
  user: Me | null
  /** true while the saved login is being checked on app start */
  loading: boolean
  /** a message to show on the login screen after being signed out automatically */
  notice: string
  login: (username: string, password: string) => Promise<void>
  applySession: (r: LoginResponse) => Promise<void>
  logout: () => Promise<void>
}

const Ctx = createContext<AuthState | null>(null)
const DRIVERS_ONLY = 'This app is for drivers only. Please use the YAAN website with your account.'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')

  // Restore the saved login on app start.
  useEffect(() => {
    (async () => {
      try {
        if (!(await tokenStore.load())) return
        const me = await api<Me>('/auth/me')
        if (me.role !== 'driver') { await tokenStore.clear(); return }
        setUser(me)
      } catch (e) {
        // Only an invalid login clears the saved token; being offline must not log the driver out.
        if (e instanceof ApiError && e.status === 401) await tokenStore.clear()
        else if (tokenStore.get()) setNotice('You are offline. Connect to the internet and reopen the app.')
      } finally { setLoading(false) }
    })()
  }, [])

  // The server rejected our token (session ended, account deactivated, ...): go back to the login screen.
  useEffect(() => {
    setUnauthorizedHandler(() => { tokenStore.clear(); setUser(null); setNotice('Your session has ended. Please sign in again.') })
    return () => setUnauthorizedHandler(null)
  }, [])

  const applySession = useCallback(async (r: LoginResponse) => {
    await tokenStore.set(r.access_token)
    setUser(r.user)
    setNotice('')
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const r = await api<LoginResponse>('/auth/login', { method: 'POST', body: { username: username.trim(), password }, token: null })
    if (r.user.role !== 'driver') {
      // Not a driver: don't keep this session on the phone, and end it on the server too.
      api('/auth/logout', { method: 'POST', token: r.access_token }).catch(() => {})
      throw new ApiError(403, DRIVERS_ONLY)
    }
    await applySession(r)
  }, [applySession])

  const logout = useCallback(async () => {
    try { await api('/auth/logout', { method: 'POST' }) } catch { /* the token may already be invalid */ }
    await tokenStore.clear()
    setUser(null)
    setNotice('')
  }, [])

  const value = useMemo(() => ({ user, loading, notice, login, applySession, logout }), [user, loading, notice, login, applySession, logout])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth() {
  const c = useContext(Ctx)
  if (!c) throw new Error('useAuth outside AuthProvider')
  return c
}
