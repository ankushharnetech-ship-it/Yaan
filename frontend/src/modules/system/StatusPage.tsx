import { useQuery } from '@tanstack/react-query'
import { Brand } from '../../components/AppLayout'
import { api } from '../../services/api'

export function StatusPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['health'],
    queryFn: () => api<{ status: string; database: string }>('/health'),
    retry: false,
  })
  const ok = data?.status === 'ok'
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 16 }}>
      <div className="card" style={{ width: 'min(440px, 100%)' }}>
        <div style={{ background: 'var(--brand-900)', borderRadius: 10, marginBottom: 20 }}><Brand /></div>
        <h1>Employee Transport Platform</h1>
        <p className="muted">Foundation check — services status.</p>
        <p>
          API & database:{' '}
          {isLoading ? <span className="badge badge-neutral">Checking…</span>
            : ok ? <span className="badge badge-success">Online</span>
            : <span className="badge badge-danger">{isError ? 'Unreachable' : 'Degraded'}</span>}
        </p>
      </div>
    </div>
  )
}
