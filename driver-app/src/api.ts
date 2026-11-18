import * as SecureStore from 'expo-secure-store'
import { API_URL } from './config'

const TOKEN_KEY = 'yaan_driver_token'
let memory: string | null = null

/** The login token lives in the phone's encrypted storage (Keychain / Keystore), never in plain files. */
export const tokenStore = {
  get: () => memory,
  async load() { try { memory = await SecureStore.getItemAsync(TOKEN_KEY) } catch { memory = null } return memory },
  async set(t: string) { memory = t; try { await SecureStore.setItemAsync(TOKEN_KEY, t) } catch { /* keep in memory */ } },
  async clear() { memory = null; try { await SecureStore.deleteItemAsync(TOKEN_KEY) } catch { /* ignore */ } },
}

/** Called when the server says the saved login is no longer valid (expired, deactivated, signed in elsewhere). */
let onUnauthorized: (() => void) | null = null
export const setUnauthorizedHandler = (fn: (() => void) | null) => { onUnauthorized = fn }

interface Detail { loc?: (string | number)[]; msg: string; type?: string; input?: unknown }
function friendlyMessage(d: Detail): string {
  if (!d.type) return d.msg
  if (d.type === 'missing' || d.type === 'string_too_short' || d.input === null || d.input === undefined) return 'This field is required'
  return d.msg
}

export class ApiError extends Error {
  status: number
  fieldErrors: Record<string, string>
  constructor(status: number, message: string, fieldErrors: Record<string, string> = {}) {
    super(message)
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

export async function api<T>(path: string, init: { method?: string; body?: unknown; token?: string | null } = {}): Promise<T> {
  const token = init.token === undefined ? memory : init.token
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 20_000)
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: init.method ?? 'GET',
      signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    })
  } catch (e) {
    throw new ApiError(0, e instanceof Error && e.name === 'AbortError'
      ? 'The server took too long to respond. Please try again.'
      : 'Cannot reach the server. Check your internet connection and try again.')
  } finally { clearTimeout(timer) }

  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    if (res.status === 401 && token && !path.startsWith('/auth/login')) onUnauthorized?.()
    const fieldErrors: Record<string, string> = {}
    if (Array.isArray(body.detail)) for (const d of body.detail) fieldErrors[String(d.loc?.slice(-1)[0] ?? '_')] = friendlyMessage(d)
    const message = typeof body.detail === 'string' ? body.detail
      : Object.values(fieldErrors)[0] ?? 'Something went wrong. Please try again.'
    throw new ApiError(res.status, message, fieldErrors)
  }
  return body as T
}
