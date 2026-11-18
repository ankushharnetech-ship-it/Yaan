# YAAN Driver — mobile app

A React Native (Expo + TypeScript) app for **drivers only**. It talks to the existing YAAN backend API; nothing in `backend/` or `frontend/` was changed.

## What it does
- **Sign in** with the driver's username and password. Other roles are refused ("This app is for drivers only").
- **Temporary password**: forced "choose a new password" screen on first login, same rule as the web app (min. 10 characters).
- **Forgot password** (emails a reset link) and **Change password** (Profile tab).
- **My trips**: grouped into *In progress / Today / Upcoming / Completed*, pull to refresh, auto-refresh every 30 s.
- **Trip actions**: Accept → Start → End (End asks for confirmation).
- **Drop-off OTP**: at each stop, type the OTP the employee reads out. Wrong codes are counted by the server (5 tries lock it); a driver can mark an employee **not dropped** with a reason. A trip can only be ended when every employee is verified or marked not dropped.
- **Open route in Maps** (Google Maps / any maps app) and **call** an employee if their number is available.
- **Live location** is sent to the server every 5 s while a trip is *started* (the same endpoint the web app uses).
- The login token is kept in the phone's secure storage (Keychain / Keystore). If the server ends the session, the app returns to the sign-in screen.

## Run it
Prerequisites: Node 20+, and the **Expo Go** app on your phone (or an Android emulator / iOS simulator).

```
cd driver-app
npm install
npm start          # scan the QR code with Expo Go
```

### Point it at the backend
| Where the app runs | `EXPO_PUBLIC_API_URL` |
|---|---|
| Android emulator | nothing to set (defaults to `http://10.0.2.2:8000/api`) |
| iOS simulator | nothing to set (defaults to `http://localhost:8000/api`) |
| **Real phone, same Wi-Fi** | `http://<your-computer-IP>:8000/api` |
| Production | `https://<your-api-domain>/api` (HTTPS is required) |

Copy `.env.example` to `.env`, edit it, and restart `npm start`.

For a real phone, start the backend so it accepts connections from the network, and allow port 8000 through the Windows firewall:
```
cd backend
.\.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000
```
The phone and computer must be on the same Wi-Fi. (CORS does not apply to native apps.)

## Project layout
```
App.tsx                      app shell: auth gate + bottom tabs
src/config.ts                API URL, refresh intervals
src/api.ts                   fetch wrapper, token storage, error handling
src/auth.tsx                 sign-in state (driver-only)
src/screens/AuthScreens.tsx  login, forgot password, change password
src/screens/TripsScreen.tsx  trip list, actions, drop-off OTP
src/screens/ProfileScreen.tsx
src/hooks/useShareLocation.ts
```

## Build an installable app
```
npm install -g eas-cli
eas login
eas build --platform android --profile preview     # an installable .apk
```
Before publishing: replace the placeholder icons in `assets/`, and set a real `EXPO_PUBLIC_API_URL` (HTTPS). The bundle identifiers are `in.yaanbooking.driver` — change them in `app.json` if you prefer another.

## Known limits
- **Location is shared only while the app is open** (foreground). Continuous tracking with the screen off needs background-location setup and store review for the permission; it can be added later.
- Push notifications for newly assigned trips are not included; the list refreshes while the app is open.
- Offline use is not supported: actions need a connection, and the app says so when it cannot reach the server.
