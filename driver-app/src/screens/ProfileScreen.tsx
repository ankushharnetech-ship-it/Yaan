import { Alert, ScrollView, StyleSheet, Text, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { useAuth } from '../auth'
import { Button, Card } from '../components/ui'
import { API_URL } from '../config'
import { colors, space } from '../theme'

export function ProfileScreen({ onChangePassword }: { onChangePassword: () => void }) {
  const { user, logout } = useAuth()
  if (!user) return null
  const confirmLogout = () => Alert.alert('Sign out?', 'You will need your username and password to sign in again.', [
    { text: 'Cancel', style: 'cancel' }, { text: 'Sign out', style: 'destructive', onPress: () => { logout() } },
  ])
  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView contentContainerStyle={{ padding: space.lg }}>
        <Text style={s.title}>Profile</Text>
        <Card>
          <View style={s.avatar}><Text style={s.avatarText}>{(user.first_name[0] ?? '').toUpperCase()}{(user.last_name[0] ?? '').toUpperCase()}</Text></View>
          <Text style={s.name}>{user.first_name} {user.last_name}</Text>
          <Text style={s.muted}>Driver</Text>
          <View style={s.rows}>
            <Row k="Username" v={user.username} />
            <Row k="Email" v={user.email} />
          </View>
        </Card>
        <Button title="Change password" variant="secondary" onPress={onChangePassword} />
        <Button title="Sign out" variant="danger" onPress={confirmLogout} style={{ marginTop: space.md }} />
        <Text style={[s.muted, { textAlign: 'center', marginTop: space.xl }]}>YAAN Driver · server {API_URL.replace(/\/api$/, '')}</Text>
      </ScrollView>
    </SafeAreaView>
  )
}

const Row = ({ k, v }: { k: string; v: string }) => (
  <View style={s.row}><Text style={s.muted}>{k}</Text><Text style={s.value}>{v}</Text></View>
)

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  title: { fontSize: 26, fontWeight: '800', color: colors.text, marginBottom: space.md },
  avatar: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center', marginBottom: space.md },
  avatarText: { color: '#fff', fontSize: 24, fontWeight: '800' },
  name: { fontSize: 20, fontWeight: '800', color: colors.text },
  muted: { fontSize: 13.5, color: colors.muted },
  rows: { marginTop: space.lg, gap: space.md },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: space.md },
  value: { fontSize: 15, fontWeight: '600', color: colors.text, flexShrink: 1, textAlign: 'right' },
})
