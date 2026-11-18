import { useState, type ReactNode } from 'react'
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { ApiError, api } from '../api'
import { useAuth } from '../auth'
import { Banner, Button, Field } from '../components/ui'
import { colors, radius, space } from '../theme'
import type { LoginResponse } from '../types'

function Shell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <SafeAreaView style={s.safe}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          <View style={s.logoRow}>
            <View style={s.logo}><Text style={s.logoMark}>Y</Text></View>
            <View>
              <Text style={s.brand}>YAAN</Text>
              <Text style={s.brandSub}>Driver</Text>
            </View>
          </View>
          <View style={s.card}>
            <Text style={s.title}>{title}</Text>
            {subtitle ? <Text style={s.subtitle}>{subtitle}</Text> : null}
            {children}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

export function LoginScreen() {
  const { login, notice } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [forgot, setForgot] = useState(false)
  if (forgot) return <ForgotScreen onBack={() => setForgot(false)} initial={username} />

  const submit = async () => {
    if (!username.trim() || !password) { setError('Enter your username and password.'); return }
    setBusy(true); setError('')
    try { await login(username, password) }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Something went wrong. Please try again.') }
    finally { setBusy(false) }
  }
  return (
    <Shell title="Sign in" subtitle="Use the username and password given to you by your transport vendor.">
      {notice ? <Banner tone="warning">{notice}</Banner> : null}
      {error ? <Banner>{error}</Banner> : null}
      <Field label="Username" value={username} onChangeText={setUsername} autoCapitalize="none" autoCorrect={false} autoComplete="username"
        textContentType="username" returnKeyType="next" />
      <Field label="Password" value={password} onChangeText={setPassword} secureTextEntry={!show} autoCapitalize="none" autoComplete="current-password"
        textContentType="password" returnKeyType="go" onSubmitEditing={submit} />
      <Button title={show ? 'Hide password' : 'Show password'} variant="link" onPress={() => setShow((v) => !v)} />
      <Button title="Sign in" onPress={submit} loading={busy} style={{ marginTop: space.sm }} />
      <Button title="Forgot password?" variant="link" onPress={() => setForgot(true)} style={{ marginTop: space.sm }} />
    </Shell>
  )
}

function ForgotScreen({ onBack, initial }: { onBack: () => void; initial: string }) {
  const [identifier, setIdentifier] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState('')
  const [error, setError] = useState('')
  const submit = async () => {
    if (!identifier.trim()) { setError('Enter your username or email.'); return }
    setBusy(true); setError('')
    try { setDone((await api<{ message: string }>('/auth/forgot-password', { method: 'POST', body: { identifier: identifier.trim() }, token: null })).message) }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Something went wrong. Please try again.') }
    finally { setBusy(false) }
  }
  return (
    <Shell title="Forgot password" subtitle="We'll email you a link to choose a new password.">
      {done ? <Banner tone="success">{done}</Banner> : null}
      {error ? <Banner>{error}</Banner> : null}
      <Field label="Username or email" value={identifier} onChangeText={setIdentifier} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" />
      <Button title="Send reset link" onPress={submit} loading={busy} disabled={!!done} />
      <Button title="Back to sign in" variant="link" onPress={onBack} style={{ marginTop: space.sm }} />
    </Shell>
  )
}

/** Shown right after signing in with a temporary password (forced), and from Profile (optional). */
export function ChangePasswordScreen({ forced, onDone }: { forced: boolean; onDone?: () => void }) {
  const { applySession, logout } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  const submit = async () => {
    const e: Record<string, string> = {}
    if (!current) e.current_password = forced ? 'Enter your temporary password' : 'Enter your current password'
    if (next.length < 10) e.new_password = 'Use at least 10 characters'
    if (confirm !== next) e.confirm = 'The two passwords do not match'
    setErrors(e); setError('')
    if (Object.keys(e).length) return
    setBusy(true)
    try {
      const r = await api<LoginResponse>('/auth/change-password', { method: 'POST', body: { current_password: current, new_password: next } })
      await applySession(r)  // the server issues a fresh token; the old one stops working
      onDone?.()
    } catch (err) {
      if (err instanceof ApiError) { setErrors(err.fieldErrors); setError(Object.keys(err.fieldErrors).length ? '' : err.message) }
      else setError('Something went wrong. Please try again.')
    } finally { setBusy(false) }
  }
  return (
    <Shell title={forced ? 'Choose a new password' : 'Change password'}
      subtitle={forced ? 'Your temporary password must be replaced before you continue.' : undefined}>
      {error ? <Banner>{error}</Banner> : null}
      <Field label={forced ? 'Temporary password' : 'Current password'} value={current} onChangeText={setCurrent} secureTextEntry autoCapitalize="none" error={errors.current_password} />
      <Field label="New password" value={next} onChangeText={setNext} secureTextEntry autoCapitalize="none" error={errors.new_password} hint="At least 10 characters" />
      <Field label="Confirm new password" value={confirm} onChangeText={setConfirm} secureTextEntry autoCapitalize="none" error={errors.confirm} />
      <Button title="Save password" onPress={submit} loading={busy} />
      {forced
        ? <Button title="Sign out" variant="link" onPress={logout} style={{ marginTop: space.sm }} />
        : <Button title="Cancel" variant="link" onPress={() => onDone?.()} style={{ marginTop: space.sm }} />}
    </Shell>
  )
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  scroll: { padding: space.lg, paddingTop: space.xl, flexGrow: 1, justifyContent: 'center' },
  logoRow: { flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: space.xl, justifyContent: 'center' },
  logo: { width: 52, height: 52, borderRadius: 14, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  logoMark: { color: '#fff', fontSize: 28, fontWeight: '800' },
  brand: { fontSize: 26, fontWeight: '800', color: colors.text, letterSpacing: 0.5 },
  brandSub: { fontSize: 13, color: colors.muted, marginTop: -2 },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: space.xl },
  title: { fontSize: 22, fontWeight: '800', color: colors.text, marginBottom: 4 },
  subtitle: { fontSize: 14, color: colors.muted, marginBottom: space.lg, lineHeight: 20 },
})
