import { useCallback, useEffect, useRef, useState } from 'react'
import { ActivityIndicator, AppState, KeyboardAvoidingView, Linking, Platform, RefreshControl, SectionList, StyleSheet, Text, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { Alert } from 'react-native'
import { ApiError, api } from '../api'
import { Badge, Banner, Button, Card, Field } from '../components/ui'
import { TRIPS_REFRESH_MS } from '../config'
import { dayKey, fmtDate, fmtTime, todayKey } from '../format'
import { useShareLocation } from '../hooks/useShareLocation'
import { colors, space } from '../theme'
import type { Passenger, Trip, TripStatus } from '../types'

const STATUS: Record<TripStatus, { label: string; tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral' }> = {
  scheduled: { label: 'Awaiting assignment', tone: 'warning' }, assigned: { label: 'Assigned', tone: 'info' }, accepted: { label: 'Accepted', tone: 'info' },
  started: { label: 'Ongoing', tone: 'warning' }, completed: { label: 'Completed', tone: 'success' }, cancelled: { label: 'Cancelled', tone: 'danger' },
}
const NEXT: Partial<Record<TripStatus, { to: 'accepted' | 'started' | 'completed'; label: string }>> = {
  assigned: { to: 'accepted', label: 'Accept trip' }, scheduled: { to: 'accepted', label: 'Accept trip' },
  accepted: { to: 'started', label: 'Start trip' }, started: { to: 'completed', label: 'End trip' },
}

const openRoute = (t: Trip) => {
  const q = (v: string) => encodeURIComponent(v)
  Linking.openURL(`https://www.google.com/maps/dir/?api=1&origin=${q(t.pickup_address)}&destination=${q(t.drop_address)}&travelmode=driving`)
    .catch(() => Alert.alert('Cannot open maps', 'No maps app is available on this phone.'))
}

/** One employee at the drop point: the driver types the OTP the employee reads out. */
function DropRow({ tripId, p, onChanged }: { tripId: number; p: Passenger; onChanged: () => void }) {
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [skipping, setSkipping] = useState(false)
  const [reason, setReason] = useState('')
  const base = `/trips/${tripId}/passengers/${p.employee_id}`

  const verify = async () => {
    if (!code.trim()) return
    setBusy(true); setError('')
    try { await api(`${base}/verify-otp`, { method: 'POST', body: { otp: code } }); setCode('') }
    catch (e) { setError(e instanceof ApiError ? e.fieldErrors.otp ?? e.message : 'Could not verify the OTP'); setCode('') }
    finally { setBusy(false); onChanged() }
  }
  const skip = async () => {
    setBusy(true); setError('')
    try { await api(`${base}/not-dropped`, { method: 'POST', body: { reason: reason.trim() } }); setSkipping(false); setReason(''); onChanged() }
    catch (e) { setError(e instanceof ApiError ? e.fieldErrors.reason ?? e.message : 'Could not save') }
    finally { setBusy(false) }
  }

  if (p.drop_status === 'verified') {
    return <View style={[s.drop, { backgroundColor: '#f0fdf4' }]}><Text style={s.bold}>{p.name}</Text><Badge tone="success">Dropped</Badge></View>
  }
  if (p.drop_status === 'not_dropped') {
    return (
      <View style={[s.drop, { backgroundColor: '#fef2f2', alignItems: 'flex-start' }]}>
        <View style={s.rowBetween}><Text style={s.bold}>{p.name}</Text><Badge tone="danger">Not dropped</Badge></View>
        {p.not_dropped_reason ? <Text style={s.muted}>{p.not_dropped_reason}</Text> : null}
      </View>
    )
  }
  return (
    <View style={[s.drop, { alignItems: 'stretch' }]}>
      <View style={s.rowBetween}>
        <Text style={s.bold}>{p.name}</Text>
        {p.otp_locked ? <Badge tone="danger">OTP locked</Badge> : <Badge tone="warning">Waiting</Badge>}
      </View>
      {p.address ? <Text style={s.muted}>{p.address}</Text> : null}
      {p.mobile ? <Button title={`Call ${p.mobile}`} variant="link" onPress={() => Linking.openURL(`tel:${p.mobile}`)} style={{ alignSelf: 'flex-start' }} /> : null}
      {!skipping && (
        <>
          {p.otp_locked
            ? <Text style={s.muted}>Too many wrong OTPs. If {p.name.split(' ')[0]} cannot share it, mark them as not dropped.</Text>
            : (
              <View style={{ flexDirection: 'row', gap: space.sm, alignItems: 'flex-start', marginTop: space.sm }}>
                <View style={{ flex: 1 }}>
                  <Field label={`OTP from ${p.name.split(' ')[0]}`} value={code} onChangeText={(v) => setCode(v.replace(/\D/g, ''))} keyboardType="number-pad"
                    maxLength={8} placeholder="Enter OTP" autoComplete="one-time-code" onSubmitEditing={verify} />
                </View>
                <Button title="Verify" onPress={verify} loading={busy} disabled={!code} style={{ marginTop: 26 }} />
              </View>
            )}
          {error ? <Text style={s.err} accessibilityRole="alert">{error}</Text> : null}
          <Button title="Employee not dropped…" variant="link" onPress={() => { setSkipping(true); setError('') }} style={{ alignSelf: 'flex-start' }} />
        </>
      )}
      {skipping && (
        <View style={{ marginTop: space.sm }}>
          <Field label={`Why was ${p.name} not dropped?`} value={reason} onChangeText={setReason} multiline placeholder="e.g. Did not turn up, phone lost, asked to be left elsewhere" />
          {error ? <Text style={s.err} accessibilityRole="alert">{error}</Text> : null}
          <View style={{ flexDirection: 'row', gap: space.sm }}>
            <Button title="Back" variant="secondary" onPress={() => { setSkipping(false); setError('') }} style={{ flex: 1 }} />
            <Button title="Confirm" variant="danger" onPress={skip} loading={busy} disabled={reason.trim().length < 3} style={{ flex: 1 }} />
          </View>
          <Text style={[s.muted, { marginTop: 6 }]}>This is reported to your Vendor Admin and the Operator.</Text>
        </View>
      )}
    </View>
  )
}

function TripCard({ t, busy, onAction, onChanged }: { t: Trip; busy: boolean; onAction: (t: Trip, to: 'accepted' | 'started' | 'completed') => void; onChanged: () => void }) {
  const next = NEXT[t.status]
  const started = t.status === 'started'
  const waiting = t.passengers.filter((p) => p.drop_status === 'pending' || p.drop_status === 'none').length
  const pct = t.passenger_count ? Math.round((t.drops_resolved / t.passenger_count) * 100) : 0
  const blocked = started && waiting > 0
  return (
    <Card>
      <View style={s.rowBetween}><Text style={s.code}>{t.code}</Text><Badge tone={STATUS[t.status].tone}>{STATUS[t.status].label}</Badge></View>
      <Text style={s.time}>{fmtTime(t.scheduled_start)} – {fmtTime(t.scheduled_end)}</Text>
      <Text style={s.muted}>{fmtDate(t.scheduled_start)} · {t.trip_type} · {t.customer_name}, {t.site_name}</Text>
      <View style={{ marginTop: space.md, gap: 6 }}>
        <Text style={s.line}><Text style={s.bold}>Pickup: </Text>{t.pickup_address}</Text>
        <Text style={s.line}><Text style={s.bold}>Drop: </Text>{t.drop_address}</Text>
        {!started && <Text style={s.line}><Text style={s.bold}>{t.passenger_count} passenger{t.passenger_count > 1 ? 's' : ''}: </Text>{t.passengers.map((p) => p.name).join(', ')}</Text>}
        {t.vehicle_number ? <Text style={s.line}><Text style={s.bold}>Vehicle: </Text>{t.vehicle_number}</Text> : null}
      </View>
      {t.special_instructions ? <View style={{ marginTop: space.sm }}><Banner tone="warning">{t.special_instructions}</Banner></View> : null}
      <Button title="Open route in Maps" variant="secondary" onPress={() => openRoute(t)} style={{ marginTop: space.md }} />

      {started && (
        <View style={{ marginTop: space.lg }}>
          <Text style={s.h3}>Drop-offs · {t.drops_resolved} of {t.passenger_count} done</Text>
          <View style={s.progress}><View style={[s.progressFill, { width: `${pct}%` }]} /></View>
          <Text style={[s.muted, { marginBottom: space.sm }]}>At each drop point, ask the employee for their OTP and enter it. They received it by notification.</Text>
          <View style={{ gap: space.sm }}>{t.passengers.map((p) => <DropRow key={p.employee_id} tripId={t.id} p={p} onChanged={onChanged} />)}</View>
        </View>
      )}

      {next && (
        <>
          <Button title={next.label} onPress={() => onAction(t, next.to)} disabled={busy || blocked} style={{ marginTop: space.lg }} />
          {blocked && <Text style={[s.muted, { marginTop: 8 }]}>You can end the trip once {waiting} more employee{waiting > 1 ? 's are' : ' is'} dropped (OTP verified) or marked not dropped.</Text>}
        </>
      )}
    </Card>
  )
}

export function TripsScreen({ name }: { name: string }) {
  const [trips, setTrips] = useState<Trip[] | null>(null)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [acting, setActing] = useState(false)
  const mounted = useRef(true)

  const load = useCallback(async () => {
    try {
      const r = await api<{ items: Trip[] }>('/trips?limit=200&view=all')
      if (mounted.current) { setTrips(r.items); setLoadError('') }
    } catch (e) { if (mounted.current) setLoadError(e instanceof ApiError ? e.message : 'Could not load your trips.') }
  }, [])

  useEffect(() => {
    mounted.current = true
    load()
    // Pick up newly assigned trips while the app is open.
    const timer = setInterval(() => { if (AppState.currentState === 'active') load() }, TRIPS_REFRESH_MS)
    const sub = AppState.addEventListener('change', (st) => { if (st === 'active') load() })
    return () => { mounted.current = false; clearInterval(timer); sub.remove() }
  }, [load])

  const act = async (t: Trip, to: 'accepted' | 'started' | 'completed') => {
    const run = async () => {
      setActing(true); setError('')
      try { await api(`/trips/${t.id}/status`, { method: 'POST', body: { status: to } }) }
      catch (e) { setError(e instanceof ApiError ? e.fieldErrors.status ?? e.message : 'Could not update the trip') }
      finally { setActing(false); load() }
    }
    if (to === 'completed') Alert.alert('End this trip?', `Trip ${t.code} will be marked completed.`, [{ text: 'Cancel', style: 'cancel' }, { text: 'End trip', onPress: run }])
    else run()
  }

  const gpsDenied = useShareLocation((trips ?? []).filter((t) => t.status === 'started').map((t) => t.id))
  const today = todayKey()
  const items = [...(trips ?? [])].sort((a, b) => +new Date(a.scheduled_start) - +new Date(b.scheduled_start))
  const open = items.filter((t) => t.status === 'assigned' || t.status === 'scheduled' || t.status === 'accepted')
  const sections = ([
    { title: 'In progress', data: items.filter((t) => t.status === 'started') },
    { title: 'Today', data: open.filter((t) => dayKey(t.scheduled_start) <= today) },
    { title: 'Upcoming', data: open.filter((t) => dayKey(t.scheduled_start) > today) },
    { title: 'Completed', data: items.filter((t) => t.status === 'completed').reverse().slice(0, 10) },
  ]).filter((x) => x.data.length)

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <SectionList
          sections={sections}
          keyExtractor={(t) => String(t.id)}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ padding: space.lg, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false) }} tintColor={colors.brand} colors={[colors.brand]} />}
          ListHeaderComponent={(
            <View style={{ marginBottom: space.md }}>
              <Text style={s.title}>My trips</Text>
              <Text style={s.muted}>Hello, {name}. Pull down to refresh.</Text>
              {error ? <View style={{ marginTop: space.md }}><Banner>{error}</Banner></View> : null}
              {loadError ? <View style={{ marginTop: space.md }}><Banner>{loadError}</Banner></View> : null}
              {gpsDenied ? <View style={{ marginTop: space.md }}><Banner tone="warning">Location access is blocked, so your live position cannot be shared. Allow location for YAAN Driver in your phone's settings.</Banner></View> : null}
            </View>
          )}
          renderSectionHeader={({ section }) => <Text style={s.section}>{section.title} <Text style={s.sectionCount}>({section.data.length})</Text></Text>}
          renderItem={({ item }) => <TripCard t={item} busy={acting} onAction={act} onChanged={load} />}
          ListEmptyComponent={trips === null && !loadError
            ? <ActivityIndicator color={colors.brand} style={{ marginTop: 40 }} />
            : trips ? <Card><Text style={s.muted}>No trips assigned to you yet.</Text></Card> : undefined}
        />
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  title: { fontSize: 26, fontWeight: '800', color: colors.text },
  section: { fontSize: 18, fontWeight: '800', color: colors.text, marginTop: space.md, marginBottom: space.sm },
  sectionCount: { fontWeight: '400', color: colors.muted },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
  code: { fontSize: 15, fontWeight: '800', color: colors.text },
  time: { fontSize: 22, fontWeight: '800', color: colors.text, marginTop: 6 },
  muted: { fontSize: 13.5, color: colors.muted, lineHeight: 19 },
  line: { fontSize: 15, color: colors.text, lineHeight: 21 },
  bold: { fontWeight: '700', color: colors.text },
  h3: { fontSize: 16, fontWeight: '800', color: colors.text, marginBottom: 6 },
  err: { color: colors.danger, fontSize: 13, marginTop: 4 },
  progress: { height: 8, borderRadius: 4, backgroundColor: '#e8eef0', marginBottom: space.sm, overflow: 'hidden' },
  progressFill: { height: 8, backgroundColor: colors.brand },
  drop: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: space.md, gap: 4, backgroundColor: colors.surface, flexDirection: 'column' },
})
