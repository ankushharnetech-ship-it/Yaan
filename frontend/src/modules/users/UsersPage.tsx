import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Copy, MailPlus, Pencil, Plus, Power, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Badge, Field, Modal, PageHead, SelectInput, TextInput } from '../../components/ui'
import { ApiError, api } from '../../services/api'
import { ROLE_LABELS, type Role } from '../../types'
import { useAuth } from '../auth/AuthContext'

interface UserRow {
  id: number; first_name: string; middle_name?: string | null; last_name: string; username: string; email: string; mobile: string | null; gender?: string | null; address?: string | null
  role: Role; vendor_id?: number | null; vendor_name: string | null; customer_id?: number | null; customer_name?: string | null; status: 'active' | 'inactive'
  credential_status: 'temporary' | 'temporary_expired' | 'set'; last_login_at: string | null; created_at: string
}
interface Onboarding { user: UserRow; temporary_password: string; temp_password_expires_at: string; email_status: string }
interface Vendor { id: number; name: string; code: string }

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—')
const credBadge = (c: UserRow['credential_status']) =>
  c === 'set' ? <Badge tone="success">Password set</Badge>
    : c === 'temporary' ? <Badge tone="warning">Temporary</Badge> : <Badge tone="danger">Temp expired</Badge>

export function UsersPage() {
  const { user: me } = useAuth()
  const isSuper = me?.role === 'super_admin'
  // A Vendor Admin onboards and manages the Operators and Drivers of their own vendor; the Super Admin manages everyone.
  const canManage = isSuper || me?.role === 'vendor_admin'
  const manageable = (u: UserRow) => canManage && (isSuper || u.role === 'operator' || u.role === 'driver')
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [role, setRole] = useState('')
  const [tagging, setTagging] = useState<UserRow | null>(null)
  const [editing, setEditing] = useState<UserRow | null>(null)
  const [actionError, setActionError] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(0)
  const [adding, setAdding] = useState(false)
  const [result, setResult] = useState<Onboarding | null>(null)
  const limit = 15

  const params = new URLSearchParams({ limit: String(limit), offset: String(page * limit) })
  if (q) params.set('q', q); if (role) params.set('role', role); if (status) params.set('status', status)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['users', q, role, status, page],
    queryFn: () => api<{ total: number; items: UserRow[] }>(`/users?${params}`),
  })

  const toggle = useMutation({
    mutationFn: (u: UserRow) => api(`/users/${u.id}/status`, { method: 'PATCH', body: JSON.stringify({ status: u.status === 'active' ? 'inactive' : 'active' }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })
  const remove = useMutation({
    mutationFn: (u: UserRow) => api(`/users/${u.id}`, { method: 'DELETE' }),
    onSuccess: () => { setActionError(''); qc.invalidateQueries({ queryKey: ['users'] }) },
    onError: (err) => setActionError(err instanceof ApiError ? err.message : 'Could not delete the user. Please try again.'),
  })
  const resend = useMutation({
    mutationFn: (u: UserRow) => api<Onboarding>(`/users/${u.id}/resend-onboarding`, { method: 'POST' }),
    onSuccess: (r) => { setResult(r); qc.invalidateQueries({ queryKey: ['users'] }) },
  })

  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / limit))
  return (
    <>
      <PageHead
        title="Users"
        subtitle={isSuper ? 'Onboard and manage Vendor Admins, Operators and Drivers.' : 'Onboard and manage the Operators and Drivers of your vendor.'}
        actions={canManage && <button className="btn btn-primary" onClick={() => setAdding(true)}><Plus size={16} /> Add user</button>}
      />
      <div className="card">
        <div className="toolbar">
          <input className="input" style={{ flex: 1 }} placeholder="Search name, username or email" value={q} onChange={(e) => { setQ(e.target.value); setPage(0) }} aria-label="Search users" />
          <select className="input" value={role} onChange={(e) => { setRole(e.target.value); setPage(0) }} aria-label="Filter by role">
            <option value="">All roles</option>
            {(['vendor_admin', 'operator', 'driver'] as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
          </select>
          <select className="input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0) }} aria-label="Filter by status">
            <option value="">Any status</option><option value="active">Active</option><option value="inactive">Inactive</option>
          </select>
        </div>
        {actionError && <div className="alert alert-danger" role="alert">{actionError}</div>}
        {isLoading ? <p className="muted">Loading users…</p> : isError ? <div className="alert alert-danger">Could not load users.</div> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Name</th><th>Username</th><th>Email</th><th>Role</th><th>Vendor</th><th>Customer</th><th>Status</th><th>Credential</th><th>Last login</th>{canManage && <th>Actions</th>}</tr></thead>
              <tbody>
                {data!.items.map((u) => (
                  <tr key={u.id}>
                    <td><strong>{u.first_name} {u.last_name}</strong></td>
                    <td>{u.username}</td><td>{u.email}</td>
                    <td>{ROLE_LABELS[u.role]}</td><td>{u.vendor_name ?? '—'}</td>
                    <td>{u.role === 'operator' ? (u.customer_name ?? <Badge tone="warning">Not assigned</Badge>) : '—'}</td>
                    <td><Badge tone={u.status === 'active' ? 'success' : 'neutral'}>{u.status === 'active' ? 'Active' : 'Inactive'}</Badge></td>
                    <td>{credBadge(u.credential_status)}</td>
                    <td className="muted">{fmt(u.last_login_at)}</td>
                    {canManage && (
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {manageable(u) && (
                          <button className="btn" title="Edit details" aria-label={`Edit ${u.username}`} onClick={() => { setActionError(''); setEditing(u) }}><Pencil size={15} /></button>
                        )}{' '}
                        {manageable(u) && u.role === 'operator' && (
                          <button className="btn" title="Change customer" aria-label={`Change customer of ${u.username}`} onClick={() => setTagging(u)}><Building2 size={15} /></button>
                        )}{' '}
                        {manageable(u) && u.credential_status !== 'set' && (
                          <button className="btn" title="Resend onboarding (issues a new temporary password)" aria-label={`Resend onboarding to ${u.username}`}
                            onClick={() => window.confirm(`Issue a new temporary password for ${u.username} and email them?`) && resend.mutate(u)}><MailPlus size={15} /></button>
                        )}{' '}
                        {manageable(u) && u.id !== me!.id && (
                          <button className="btn" title={u.status === 'active' ? 'Deactivate' : 'Activate'} aria-label={u.status === 'active' ? `Deactivate ${u.username}` : `Activate ${u.username}`}
                            onClick={() => toggle.mutate(u)}><Power size={15} /></button>
                        )}{' '}
                        {isSuper && u.role !== 'super_admin' && u.id !== me!.id && (
                          <button className="btn btn-danger" title="Delete user (Super Admin only)" aria-label={`Delete ${u.username}`}
                            onClick={() => window.confirm(`Permanently delete ${u.first_name} ${u.last_name} (${u.username})? This cannot be undone.`) && remove.mutate(u)}><Trash2 size={15} /></button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
                {!data!.items.length && <tr><td colSpan={10} className="muted" style={{ textAlign: 'center', padding: 32 }}>No users found.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14 }}>
          <span className="muted">{data?.total ?? 0} users</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="muted">Page {page + 1} of {pages}</span>
            <button className="btn" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </div>
      </div>

      {editing && <EditUserModal user={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); qc.invalidateQueries({ queryKey: ['users'] }) }} />}
      {tagging && <TagCustomerModal user={tagging} onClose={() => setTagging(null)} onSaved={() => { setTagging(null); qc.invalidateQueries({ queryKey: ['users'] }) }} />}
      {adding && <AddUserModal isSuper={isSuper} ownVendorId={me?.vendor_id ?? null} onClose={() => setAdding(false)} onCreated={(r) => { setAdding(false); setResult(r); qc.invalidateQueries({ queryKey: ['users'] }) }} />}
      {result && <CredentialModal r={result} onClose={() => setResult(null)} />}
    </>
  )
}

function AddUserModal({ isSuper, ownVendorId, onClose, onCreated }: { isSuper: boolean; ownVendorId: number | null; onClose: () => void; onCreated: (r: Onboarding) => void }) {
  // Super Admin: any role in any vendor. Vendor Admin: Operators and Drivers, always in their own vendor.
  const { data: vendors } = useQuery({ queryKey: ['vendors', 'active'], enabled: isSuper, queryFn: () => api<{ items: Vendor[] }>('/vendors?status=active&limit=200').then((r) => r.items) })
  const [f, setF] = useState({ first_name: '', middle_name: '', last_name: '', username: '', email: '', mobile: '', gender: '', role: '', vendor_id: isSuper ? '' : String(ownVendorId ?? ''), driver_id: '', customer_id: '', address: '' })
  const { data: customers } = useQuery({
    queryKey: ['customers', 'for-operator', f.vendor_id], enabled: f.role === 'operator' && !!f.vendor_id,
    queryFn: () => api<{ items: { id: number; code: string; name: string }[] }>(`/customers?status=active&limit=200${isSuper ? `&vendor_id=${f.vendor_id}` : ''}`).then((r) => r.items),
  })
  const roles: Role[] = isSuper ? ['vendor_admin', 'operator', 'driver'] : ['operator', 'driver']
  const { data: drivers } = useQuery({
    queryKey: ['drivers', 'unlinked', f.vendor_id],
    queryFn: () => api<{ items: { id: number; code: string; first_name: string; last_name: string }[] }>(`/drivers?unlinked=true&status=active&vendor_id=${f.vendor_id}&limit=200`).then((r) => r.items),
    enabled: f.role === 'driver' && !!f.vendor_id,
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) =>
    setF({ ...f, [k]: e.target.value, ...(k === 'vendor_id' || k === 'role' ? { driver_id: '', customer_id: '' } : {}) })

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setErrors({}); setFormError('')
    const nullIfEmpty = (v: string) => (v.trim() ? v.trim() : null)
    try {
      onCreated(await api<Onboarding>('/users', {
        method: 'POST',
        body: JSON.stringify({
          ...f, middle_name: nullIfEmpty(f.middle_name), mobile: nullIfEmpty(f.mobile), gender: nullIfEmpty(f.gender),
          address: nullIfEmpty(f.address), vendor_id: f.vendor_id ? Number(f.vendor_id) : null,
          driver_id: f.role === 'driver' && f.driver_id ? Number(f.driver_id) : null,
          customer_id: f.role === 'operator' && f.customer_id ? Number(f.customer_id) : null,
        }),
      }))
    } catch (err) {
      if (err instanceof ApiError) { setErrors(err.fieldErrors); if (!Object.keys(err.fieldErrors).length) setFormError(err.message) }
      else setFormError('Something went wrong. Please try again.')
    } finally { setBusy(false) }
  }

  return (
    <Modal title="Add user" onClose={onClose} wide>
      <form onSubmit={submit}>
        {formError && <div className="alert alert-danger">{formError}</div>}
        <div className="form-grid">
          <Field label="First name *" error={errors.first_name}><TextInput value={f.first_name} onChange={set('first_name')} required autoFocus /></Field>
          <Field label="Middle name"><TextInput value={f.middle_name} onChange={set('middle_name')} /></Field>
          <Field label="Last name *" error={errors.last_name}><TextInput value={f.last_name} onChange={set('last_name')} required /></Field>
          <Field label="Username *" error={errors.username} hint="Letters, numbers, . _ -"><TextInput value={f.username} onChange={set('username')} required minLength={3} /></Field>
          <Field label="Email *" error={errors.email}><TextInput type="email" value={f.email} onChange={set('email')} required /></Field>
          <Field label="Mobile number" error={errors.mobile}><TextInput type="tel" value={f.mobile} onChange={set('mobile')} /></Field>
          <Field label="Role *" error={errors.role}>
            <SelectInput value={f.role} onChange={set('role')} required>
              <option value="">Select role</option>
              {roles.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </SelectInput>
          </Field>
          {isSuper && (
            <Field label="Vendor *" error={errors.vendor_id}>
              <SelectInput value={f.vendor_id} onChange={set('vendor_id')} required>
                <option value="">Select vendor</option>
                {vendors?.map((v) => <option key={v.id} value={v.id}>{v.name} ({v.code})</option>)}
              </SelectInput>
            </Field>
          )}
          {f.role === 'operator' && (
            <div style={{ gridColumn: '1 / -1' }}>
              <Field label="Customer *" error={errors.customer_id}
                hint={f.vendor_id && customers && !customers.length ? 'No active customers for this vendor — create one under Customers first.' : 'An Operator works for one customer company and only sees its employees and trips'}>
                <SelectInput value={f.customer_id} onChange={set('customer_id')} required disabled={!f.vendor_id}>
                  <option value="">{f.vendor_id ? 'Select customer' : 'Select a vendor first'}</option>
                  {customers?.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.code})</option>)}
                </SelectInput>
              </Field>
            </div>
          )}
          {f.role === 'driver' && (
            <div style={{ gridColumn: '1 / -1' }}>
              <Field label="Driver record *" error={errors.driver_id}
                hint={f.vendor_id && drivers && !drivers.length ? 'No unlinked drivers for this vendor — create one under Drivers first.' : 'Links this login to a driver master record'}>
                <SelectInput value={f.driver_id} onChange={set('driver_id')} required disabled={!f.vendor_id}>
                  <option value="">{f.vendor_id ? 'Select driver' : 'Select a vendor first'}</option>
                  {drivers?.map((d) => <option key={d.id} value={d.id}>{d.code} — {d.first_name} {d.last_name}</option>)}
                </SelectInput>
              </Field>
            </div>
          )}
          <Field label="Gender">
            <SelectInput value={f.gender} onChange={set('gender')}><option value="">Not specified</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option></SelectInput>
          </Field>
          <Field label="Address *" error={errors.address}><TextInput value={f.address} onChange={set('address')} required /></Field>
        </div>
        <p className="muted" style={{ fontSize: 13 }}>A temporary password is generated automatically. You'll see it once after saving, and the user gets an email with a link to set their own password.</p>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Creating…' : 'Create user'}</button>
        </div>
      </form>
    </Modal>
  )
}

function EditUserModal({ user, onClose, onSaved }: { user: UserRow; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ first_name: user.first_name, middle_name: user.middle_name ?? '', last_name: user.last_name, email: user.email, mobile: user.mobile ?? '', gender: user.gender ?? '', address: user.address ?? '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setErrors({}); setFormError('')
    const nullIfEmpty = (v: string) => (v.trim() ? v.trim() : null)
    try {
      await api(`/users/${user.id}`, {
        method: 'PUT',
        body: JSON.stringify({ first_name: f.first_name.trim(), middle_name: nullIfEmpty(f.middle_name), last_name: f.last_name.trim(), email: f.email.trim(),
          mobile: nullIfEmpty(f.mobile), gender: nullIfEmpty(f.gender), address: nullIfEmpty(f.address) }),
      })
      onSaved()
    } catch (err) {
      if (err instanceof ApiError) { setErrors(err.fieldErrors); if (!Object.keys(err.fieldErrors).length) setFormError(err.message) }
      else setFormError('Something went wrong. Please try again.')
    } finally { setBusy(false) }
  }
  return (
    <Modal title={`Edit ${user.username}`} onClose={onClose} wide>
      <form onSubmit={submit}>
        {formError && <div className="alert alert-danger" role="alert">{formError}</div>}
        <div className="form-grid">
          <Field label="First name *" error={errors.first_name}><TextInput value={f.first_name} onChange={set('first_name')} required autoFocus /></Field>
          <Field label="Middle name"><TextInput value={f.middle_name} onChange={set('middle_name')} /></Field>
          <Field label="Last name *" error={errors.last_name}><TextInput value={f.last_name} onChange={set('last_name')} required /></Field>
          <Field label="Email *" error={errors.email} hint="Onboarding and password-reset emails go here"><TextInput type="email" value={f.email} onChange={set('email')} required /></Field>
          <Field label="Mobile number" error={errors.mobile}><TextInput type="tel" value={f.mobile} onChange={set('mobile')} /></Field>
          <Field label="Gender">
            <SelectInput value={f.gender} onChange={set('gender')}><option value="">Not specified</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option></SelectInput>
          </Field>
          <div style={{ gridColumn: '1 / -1' }}><Field label="Address *" error={errors.address}><TextInput value={f.address} onChange={set('address')} required /></Field></div>
        </div>
        <p className="muted" style={{ fontSize: 13 }}>Username ({user.username}) and role ({ROLE_LABELS[user.role]}) cannot be changed.</p>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save changes'}</button>
        </div>
      </form>
    </Modal>
  )
}

function TagCustomerModal({ user, onClose, onSaved }: { user: UserRow; onClose: () => void; onSaved: () => void }) {
  const [customerId, setCustomerId] = useState(user.customer_id ? String(user.customer_id) : '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const { data: customers } = useQuery({ queryKey: ['customers', 'for-tag', user.id], queryFn: () => api<{ items: { id: number; code: string; name: string }[] }>(`/customers?status=active&limit=200${user.vendor_id ? `&vendor_id=${user.vendor_id}` : ''}`).then((r) => r.items) })
  const save = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setError('')
    try { await api(`/users/${user.id}`, { method: 'PUT', body: JSON.stringify({ customer_id: Number(customerId) }) }); onSaved() }
    catch (err) { setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.') }
    finally { setBusy(false) }
  }
  return (
    <Modal title={`Customer for ${user.first_name} ${user.last_name}`} onClose={onClose}>
      <form onSubmit={save}>
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        <Field label="Customer *" hint="This Operator will only see this customer's employees and trips.">
          <SelectInput value={customerId} onChange={(e) => setCustomerId(e.target.value)} required>
            <option value="">Select customer</option>
            {customers?.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.code})</option>)}
          </SelectInput>
        </Field>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || !customerId}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Modal>
  )
}

function CredentialModal({ r, onClose }: { r: Onboarding; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try { await navigator.clipboard.writeText(r.temporary_password); setCopied(true) } catch { /* clipboard unavailable */ }
  }
  return (
    <Modal title="User created" onClose={onClose}>
      <p><strong>{r.user.first_name} {r.user.last_name}</strong> ({ROLE_LABELS[r.user.role]}) can now sign in.</p>
      <div className="alert alert-warning">This temporary password is shown <strong>only once</strong>. Copy it now if you need to share it.</div>
      <div className="credential-box">
        <div className="muted" style={{ fontSize: 12 }}>Username</div><div style={{ fontWeight: 600, marginBottom: 8 }}>{r.user.username}</div>
        <div className="muted" style={{ fontSize: 12 }}>Temporary password</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <code>{r.temporary_password}</code>
          <button className="btn" onClick={copy} aria-label="Copy password"><Copy size={15} /> {copied ? 'Copied' : 'Copy'}</button>
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>Valid until {fmt(r.temp_password_expires_at)}</div>
      </div>
      <p>Onboarding email to {r.user.email}: {r.email_status === 'sent' ? <Badge tone="success">Sent</Badge> : <Badge tone="danger">Failed — use Resend later</Badge>}</p>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}><button className="btn btn-primary" onClick={onClose}>Done</button></div>
    </Modal>
  )
}
