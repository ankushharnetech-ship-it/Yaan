import * as Location from 'expo-location'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { LOCATION_SEND_MS } from '../config'

/**
 * While a trip is started, send this phone's position to the server so the vendor and operator can follow it
 * (same endpoint the web app uses). Foreground only: it works while the app is open.
 * Returns true when the driver has blocked location access, so the screen can explain how to turn it on.
 */
export function useShareLocation(tripIds: number[]) {
  const key = tripIds.join(',')
  const [denied, setDenied] = useState(false)

  useEffect(() => {
    if (!key) return
    let alive = true
    let sub: Location.LocationSubscription | null = null
    let timer: ReturnType<typeof setInterval> | null = null
    let pos: { latitude: number; longitude: number } | null = null
    const send = () => {
      if (!pos) return
      key.split(',').forEach((id) => api(`/trips/${id}/location`, { method: 'POST', body: pos }).catch(() => {}))
    }
    ;(async () => {
      const perm = await Location.requestForegroundPermissionsAsync()
      if (!alive) return
      if (perm.status !== 'granted') { setDenied(true); return }
      setDenied(false)
      sub = await Location.watchPositionAsync(
        { accuracy: Location.Accuracy.High, timeInterval: LOCATION_SEND_MS, distanceInterval: 10 },
        (p) => { const first = !pos; pos = { latitude: p.coords.latitude, longitude: p.coords.longitude }; if (first) send() },
      )
      if (!alive) { sub.remove(); return }
      timer = setInterval(send, LOCATION_SEND_MS) // keep "last seen" fresh even when stationary
    })().catch(() => setDenied(true))

    return () => { alive = false; sub?.remove(); if (timer) clearInterval(timer) }
  }, [key])

  return denied
}
