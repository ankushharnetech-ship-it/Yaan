const TOKEN_KEY = 'yaan_token'

export const tokenStore = {
  get: () => {
    try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set: (t: string) => { try { sessionStorage.setItem(TOKEN_KEY, t) } catch { /* ignore */ } },
  clear: () => { try { sessionStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ } },
}

interface Detail { loc?: (string | number)[]; msg: string; type?: string; input?: unknown }

/** Turns the validator's technical wording into something a person can act on. Our own messages pass through unchanged. */
function friendlyMessage(d: Detail): string {
  if (!d.type) return d.msg
  if (d.type === 'missing' || d.type === 'string_too_short' || d.input === null || d.input === undefined) return 'This field is required'
  if (d.type.startsWith('float') || d.type.startsWith('int')) return 'Enter a valid number'
  return d.msg
}

/** Structured error so forms can map `fieldErrors` onto inputs. */
export class ApiError extends Error {
  status: number
  fieldErrors: Record<string, string>
  constructor(status: number, message: string, fieldErrors: Record<string, string> = {}) {
    super(message)
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

/** Downloads a binary response (e.g. an .xlsx report) with the auth header, then saves it. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const token = tokenStore.get()
  const res = await fetch(`/api${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, typeof body.detail === 'string' ? body.detail : 'Download failed')
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? fallbackName
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url; a.download = name
  document.body.appendChild(a); a.click(); a.remove()
  URL.revokeObjectURL(url)
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = tokenStore.get()
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  })
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const fieldErrors: Record<string, string> = {}
    if (Array.isArray(body.detail)) {
      for (const d of body.detail) fieldErrors[String(d.loc?.slice(-1)[0] ?? '_')] = friendlyMessage(d)
    }
    const message = typeof body.detail === 'string' ? body.detail : 'Please check the highlighted fields'
    throw new ApiError(res.status, message, fieldErrors)
  }
  return body as T
}
