import { Platform } from 'react-native'

/**
 * Where the YAAN backend lives. Set EXPO_PUBLIC_API_URL (see .env.example) for a real phone or a deployed server, e.g.
 *   EXPO_PUBLIC_API_URL=http://192.168.1.20:8000/api      (your computer on the same Wi-Fi)
 *   EXPO_PUBLIC_API_URL=https://api.yaanbooking.in/api     (production — must be HTTPS)
 * Defaults work for emulators: the Android emulator reaches your computer at 10.0.2.2, the iOS simulator at localhost.
 */
const fallback = Platform.OS === 'android' ? 'http://10.0.2.2:8000/api' : 'http://localhost:8000/api'
export const API_URL = (process.env.EXPO_PUBLIC_API_URL || fallback).replace(/\/+$/, '')

/** How often the trip list refreshes itself while the app is open, and how often the live position is sent. */
export const TRIPS_REFRESH_MS = 30_000
export const LOCATION_SEND_MS = 5_000
