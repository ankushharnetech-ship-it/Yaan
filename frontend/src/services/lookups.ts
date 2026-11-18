import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export type Lookups = Record<string, { id: number; code: string; label: string }[]>

export function useLookups() {
  return useQuery({ queryKey: ['lookups'], queryFn: () => api<Lookups>('/lookups'), staleTime: 5 * 60_000 })
}

export const lookupOptions = (l: Lookups | undefined, category: string) =>
  (l?.[category] ?? []).map((x) => ({ value: x.id, label: x.label }))

export const lookupLabel = (l: Lookups | undefined, category: string, id: number | null | undefined) =>
  l?.[category]?.find((x) => x.id === id)?.label ?? '—'
