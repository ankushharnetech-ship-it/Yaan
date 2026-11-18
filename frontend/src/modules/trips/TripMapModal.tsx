import { useQuery } from '@tanstack/react-query'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef } from 'react'
import { Modal } from '../../components/ui'
import { api } from '../../services/api'

interface Stop { kind: 'pickup' | 'employee' | 'drop' | 'office'; label: string; latitude: number; longitude: number; address?: string; sequence?: number; status: string | null }
interface RouteData {
  customer_location: { name: string; site: string | null; address: string | null; latitude: number; longitude: number } | null
  code: string; status: string; trip_type: string | null; vehicle_code: string | null; vehicle_number: string | null; stops: Stop[]; missing: number
  live: { latitude: number; longitude: number; at: string } | null
}

const pin = (text: string, color: string) =>
  L.divIcon({ className: '', iconSize: [28, 28], iconAnchor: [14, 14],
    html: `<div style="width:28px;height:28px;border-radius:50%;background:${color};color:#fff;font:600 13px/28px system-ui;text-align:center;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4)">${text}</div>` })
// Black map pin with a white building inside, for the customer's office
const officeIcon = L.divIcon({ className: '', iconSize: [34, 44], iconAnchor: [17, 42], popupAnchor: [0, -38],
  html: `<svg width="34" height="44" viewBox="0 0 34 44" xmlns="http://www.w3.org/2000/svg" style="filter:drop-shadow(0 2px 3px rgba(0,0,0,.4))">
    <path d="M17 1C8.2 1 1 8 1 16.7 1 28 17 43 17 43s16-15 16-26.300C33 8 25.800 1 17 1z" fill="#111827" stroke="#fff" stroke-width="1.5"/>
    <rect x="9.500" y="8" width="15" height="19" rx="1.500" fill="#fff"/>
    <g fill="#111827"><rect x="12" y="11" width="3" height="3"/><rect x="19" y="11" width="3" height="3"/><rect x="12" y="16.500" width="3" height="3"/><rect x="19" y="16.500" width="3" height="3"/><rect x="15" y="21.500" width="4" height="5.500"/></g></svg>` })
const carIcon = L.divIcon({ className: '', iconSize: [30, 30], iconAnchor: [15, 15],
  html: '<div style="width:30px;height:30px;border-radius:50%;background:#1d4ed8;border:3px solid #fff;box-shadow:0 0 0 4px rgba(29,78,216,.3);text-align:center;font-size:16px;line-height:24px">🚗</div>' })

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!))
const STOP_COLOR: Record<string, string> = { verified: '#16a34a', not_dropped: '#dc2626' }

/** Road geometry between the stops from the public OSRM server; falls back to straight lines if it is unreachable. */
async function roadPath(pts: [number, number][]): Promise<[number, number][]> {
  if (pts.length < 2) return pts
  try {
    const url = `https://router.project-osrm.org/route/v1/driving/${pts.map(([la, ln]) => `${ln},${la}`).join(';')}?overview=full&geometries=geojson`
    const r = await fetch(url)
    const j = await r.json()
    const coords: [number, number][] | undefined = j.routes?.[0]?.geometry?.coordinates
    if (coords?.length) return coords.map(([ln, la]) => [la, ln])
  } catch { /* use straight lines */ }
  return pts
}

export function TripMapModal({ tripId, code, onClose }: { tripId: number; code: string; onClose: () => void }) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)
  const fitted = useRef(false)
  const pathKey = useRef('')
  const path = useRef<[number, number][]>([])
  const leg = useRef<{ key: string; line: [number, number][] }>({ key: '', line: [] })
  const { data, isError } = useQuery({
    queryKey: ['trip-route', tripId],
    queryFn: () => api<RouteData>(`/trips/${tripId}/route`),
    refetchInterval: (q) => (q.state.data?.status === 'started' ? 5_000 : false), // live position while the trip runs
  })

  useEffect(() => {
    if (!el.current) return
    const m = L.map(el.current).setView([20.5, 78.9], 5)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(m)
    layer.current = L.layerGroup().addTo(m)
    map.current = m
    setTimeout(() => m.invalidateSize(), 50)
    return () => { m.remove(); map.current = null }
  }, [])

  useEffect(() => {
    const m = map.current, g = layer.current
    if (!data || !m || !g) return
    let cancelled = false
    const draw = (line: [number, number][]) => {
      if (cancelled) return
      g.clearLayers()
      if (line.length > 1) L.polyline(line, { color: '#16a34a', weight: 5, opacity: 0.85 }).addTo(g)
      if (data.live && leg.current.line.length > 1) L.polyline(leg.current.line, { color: '#2563eb', weight: 4, dashArray: '8 8', opacity: 0.9 }).addTo(g)
      let n = 0
      data.stops.forEach((s) => {
        if (s.kind === 'office') return // drawn as the building pin below
        const icon = s.kind === 'pickup' ? pin('P', '#2563eb') : s.kind === 'drop' ? pin('D', '#111827') : pin(String(++n), STOP_COLOR[s.status ?? ''] ?? '#f59e0b')
        const tip = `<strong>${esc(s.label)}</strong>${s.address ? `<br>${esc(s.address)}` : ''}${s.kind === 'employee' ? `<br>${s.status === 'verified' ? 'Dropped' : s.status === 'not_dropped' ? 'Not dropped' : 'Waiting'}` : ''}`
        L.marker([s.latitude, s.longitude], { icon }).bindPopup(tip).addTo(g)
      })
      const c = data.customer_location
      if (c) L.marker([c.latitude, c.longitude], { icon: officeIcon, zIndexOffset: 500 }).bindPopup(`<strong>${esc(c.name)}</strong>${c.site ? `<br>${esc(c.site)}` : ''}${c.address ? `<br>${esc(c.address)}` : ''}`).bindTooltip(esc(c.name), { direction: 'top', offset: [0, -40] }).addTo(g)
      if (data.live) L.marker([data.live.latitude, data.live.longitude], { icon: carIcon, zIndexOffset: 1000 }).bindTooltip(`Driver${data.vehicle_code || data.vehicle_number ? ` (${esc(data.vehicle_code ?? data.vehicle_number ?? '')})` : ''}`, { permanent: true, direction: 'top', offset: [0, -16] }).addTo(g)
      if (!fitted.current && data.stops.length) { m.fitBounds(L.latLngBounds([...data.stops.map((s) => [s.latitude, s.longitude] as [number, number]), ...(data.live ? [[data.live.latitude, data.live.longitude] as [number, number]] : []), ...(data.customer_location ? [[data.customer_location.latitude, data.customer_location.longitude] as [number, number]] : [])]), { padding: [40, 40] }); fitted.current = true }
    }
    // Where the driver is heading right now: Pickup trip -> the pickup point (first stop); Drop trip -> the next employee to drop.
    const target = data.live && data.status === 'started'
      ? (data.trip_type === 'Drop' ? data.stops.find((s) => s.kind === 'employee' && s.status !== 'verified' && s.status !== 'not_dropped') : undefined) ?? data.stops[0]
      : undefined
    const legKey = data.live && target ? `${target.latitude},${target.longitude}|${data.live.latitude.toFixed(3)},${data.live.longitude.toFixed(3)}` : ''
    if (!legKey) leg.current = { key: '', line: [] }
    else if (legKey !== leg.current.key && data.live) { // re-route only when the target changes or the driver moved ~100m
      const from: [number, number] = [data.live.latitude, data.live.longitude]
      roadPath([from, [target!.latitude, target!.longitude]]).then((line) => { leg.current = { key: legKey, line }; if (!cancelled) draw(path.current) })
    }
    const pts = data.stops.map((s) => [s.latitude, s.longitude] as [number, number])
    const key = JSON.stringify(pts)
    if (key === pathKey.current) draw(path.current) // stops unchanged: only the live marker moves, no new routing request
    else roadPath(pts).then((line) => { pathKey.current = key; path.current = line; draw(line) })
    return () => { cancelled = true }
  }, [data])

  return (
    <Modal title={`Route — ${code}`} onClose={onClose} wide>
      {isError && <div className="alert alert-danger">Could not load the route.</div>}
      {data && data.missing > 0 && <div className="alert alert-warning">{data.missing} stop(s) have no coordinates and are not shown.</div>}
      {data && data.stops.length < 2 && <div className="alert alert-warning">Not enough stops with coordinates to draw a route.</div>}
      {data?.live && <button type="button" className="btn" style={{ marginBottom: 8 }} onClick={() => map.current?.setView([data.live!.latitude, data.live!.longitude], 16)}>Centre on driver</button>}
      <div ref={el} style={{ height: 460, borderRadius: 8 }} />
      <p className="muted" style={{ fontSize: 13, margin: '8px 0 0' }}>
        {data?.status === 'started' ? (data.live ? `Live — updated ${new Date(data.live.at).toLocaleTimeString()}` : 'Trip started — waiting for the driver\'s location…') : 'Live tracking starts when the driver starts the trip.'}
        {' '}Building pin = customer office, P = pickup, D = drop, numbers = employee stops (green dropped, red not dropped). Dashed blue = driver to the next stop.
      </p>
    </Modal>
  )
}
