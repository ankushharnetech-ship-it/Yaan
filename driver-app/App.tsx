import { StatusBar } from 'expo-status-bar'
import { useState } from 'react'
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native'
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context'
import { AuthProvider, useAuth } from './src/auth'
import { ChangePasswordScreen, LoginScreen } from './src/screens/AuthScreens'
import { ProfileScreen } from './src/screens/ProfileScreen'
import { TripsScreen } from './src/screens/TripsScreen'
import { colors } from './src/theme'

type Tab = 'trips' | 'profile'

function TabBar({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  const insets = useSafeAreaInsets()
  const items: [Tab, string][] = [['trips', 'My trips'], ['profile', 'Profile']]
  return (
    <View style={[s.bar, { paddingBottom: Math.max(insets.bottom, 8) }]} accessibilityRole="tablist">
      {items.map(([key, label]) => (
        <Pressable key={key} style={s.tab} onPress={() => onChange(key)} accessibilityRole="tab" accessibilityState={{ selected: tab === key }}>
          <View style={[s.dot, tab === key && { backgroundColor: colors.brand }]} />
          <Text style={[s.tabText, tab === key && { color: colors.brand }]}>{label}</Text>
        </Pressable>
      ))}
    </View>
  )
}

function Root() {
  const { user, loading } = useAuth()
  const [tab, setTab] = useState<Tab>('trips')
  const [changingPassword, setChangingPassword] = useState(false)

  if (loading) return <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View>
  if (!user) return <LoginScreen />
  if (user.must_change_password) return <ChangePasswordScreen forced />
  if (changingPassword) return <ChangePasswordScreen forced={false} onDone={() => setChangingPassword(false)} />
  return (
    <View style={{ flex: 1 }}>
      <View style={{ flex: 1 }}>
        {tab === 'trips' ? <TripsScreen name={user.first_name} /> : <ProfileScreen onChangePassword={() => setChangingPassword(true)} />}
      </View>
      <TabBar tab={tab} onChange={setTab} />
    </View>
  )
}

export default function App() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <StatusBar style="dark" />
        <Root />
      </AuthProvider>
    </SafeAreaProvider>
  )
}

const s = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.bg },
  bar: { flexDirection: 'row', backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 8 },
  tab: { flex: 1, alignItems: 'center', gap: 4, paddingVertical: 4 },
  dot: { width: 22, height: 4, borderRadius: 2, backgroundColor: 'transparent' },
  tabText: { fontSize: 13, fontWeight: '700', color: colors.muted },
})
