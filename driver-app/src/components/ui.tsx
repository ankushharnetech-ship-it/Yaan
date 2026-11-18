import type { ReactNode } from 'react'
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View, type StyleProp, type TextInputProps, type ViewStyle } from 'react-native'
import { colors, radius, space } from '../theme'

type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'
const TONES: Record<Tone, { bg: string; fg: string }> = {
  success: { bg: colors.successBg, fg: colors.success }, warning: { bg: colors.warningBg, fg: colors.warning },
  danger: { bg: colors.dangerBg, fg: colors.danger }, info: { bg: colors.infoBg, fg: colors.info }, neutral: { bg: '#eef2f3', fg: colors.muted },
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  const t = TONES[tone]
  return <View style={[s.badge, { backgroundColor: t.bg }]}><Text style={[s.badgeText, { color: t.fg }]}>{children}</Text></View>
}

export function Button({ title, onPress, variant = 'primary', loading, disabled, style }: {
  title: string; onPress: () => void; variant?: 'primary' | 'secondary' | 'danger' | 'link'; loading?: boolean; disabled?: boolean; style?: StyleProp<ViewStyle>
}) {
  const off = disabled || loading
  const bg = variant === 'primary' ? colors.brand : variant === 'danger' ? colors.danger : variant === 'secondary' ? colors.surface : 'transparent'
  const fg = variant === 'secondary' ? colors.text : variant === 'link' ? colors.brand : '#fff'
  return (
    <Pressable accessibilityRole="button" accessibilityState={{ disabled: !!off }} onPress={onPress} disabled={off}
      style={({ pressed }) => [s.btn, variant !== 'link' && { backgroundColor: bg }, variant === 'secondary' && { borderWidth: 1.5, borderColor: colors.border },
        variant === 'link' && { minHeight: 40 }, off && { opacity: 0.5 }, pressed && { opacity: 0.8 }, style]}>
      {loading ? <ActivityIndicator color={fg} /> : <Text style={[s.btnText, { color: fg }]}>{title}</Text>}
    </Pressable>
  )
}

export function Field({ label, error, hint, ...input }: { label: string; error?: string; hint?: string } & TextInputProps) {
  return (
    <View style={{ marginBottom: space.md }}>
      <Text style={s.label}>{label}</Text>
      <TextInput placeholderTextColor="#98a6ac" {...input} accessibilityLabel={label}
        style={[s.input, !!error && { borderColor: colors.danger }, input.multiline && { height: 84, paddingTop: 12, textAlignVertical: 'top' }]} />
      {error ? <Text style={s.error} accessibilityRole="alert">{error}</Text> : hint ? <Text style={s.hint}>{hint}</Text> : null}
    </View>
  )
}

export function Banner({ tone = 'danger', children }: { tone?: 'danger' | 'warning' | 'success' | 'info'; children: ReactNode }) {
  const t = TONES[tone]
  return <View accessibilityRole="alert" style={[s.banner, { backgroundColor: t.bg }]}><Text style={{ color: t.fg, fontSize: 14, lineHeight: 20 }}>{children}</Text></View>
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[s.card, style]}>{children}</View>
}

const s = StyleSheet.create({
  badge: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999, alignSelf: 'flex-start' },
  badgeText: { fontSize: 12, fontWeight: '700' },
  btn: { minHeight: 50, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center', paddingHorizontal: space.lg },
  btnText: { fontSize: 16, fontWeight: '700' },
  label: { fontSize: 14, fontWeight: '600', color: colors.text, marginBottom: 6 },
  input: { minHeight: 50, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 14, fontSize: 16, color: colors.text, backgroundColor: colors.surface },
  error: { color: colors.danger, fontSize: 13, marginTop: 4 },
  hint: { color: colors.muted, fontSize: 13, marginTop: 4 },
  banner: { padding: space.md, borderRadius: radius.md, marginBottom: space.md },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: space.lg, marginBottom: space.md },
})
