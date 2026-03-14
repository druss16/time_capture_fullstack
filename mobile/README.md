# TimeTracker Mobile
**React Native (Expo) · iOS + Android · MavOps**

One-tap time tracking for CPA firms. Shazam-style button + AI auto-fill + voice entry.

---

## What's in this repo

```
timetracker-mobile/
├── App.tsx                          ← Entry point, auth state, timer restore
├── app.json                         ← Expo config, permissions, bundle IDs
├── eas.json                         ← EAS Build profiles (dev/preview/production)
├── src/
│   ├── api/client.ts                ← All API calls to Django backend
│   ├── store/timerStore.ts          ← Zustand global timer (survives app kill)
│   ├── utils/
│   │   ├── theme.ts                 ← Brand colors matching web app exactly
│   │   └── backgroundTimer.ts      ← Background fetch + push notifications
│   ├── hooks/
│   │   ├── useCalendarEvents.ts     ← Reads calendar, matches events → clients
│   │   └── useVoiceEntry.ts         ← Records audio → AI parse
│   ├── components/
│   │   └── ClientPicker.tsx         ← Searchable client bottom sheet
│   ├── navigation/AppNavigator.tsx  ← Stack + bottom tabs
│   ├── screens/
│   │   ├── Auth/LoginScreen.tsx
│   │   ├── Home/HomeScreen.tsx      ← The big button + AI suggestions
│   │   ├── Recording/RecordingScreen.tsx ← Live timer + voice + category chips
│   │   ├── Save/SaveScreen.tsx      ← AI prefilled save form
│   │   ├── History/HistoryScreen.tsx
│   │   └── Settings/SettingsScreen.tsx
│   └── types/index.ts

timetracker-django/mobile/
├── __init__.py
├── urls.py
└── views.py                         ← 6 new endpoints (Start/Stop/Recent/AISuggest/Voice/Calendar)
```

---

## Phase 1 — Local dev setup

### Prerequisites
- Node 20+
- Expo CLI: `npm install -g expo-cli`
- EAS CLI: `npm install -g eas-cli`
- Xcode 15+ (Mac, for iOS simulator)
- Android Studio (for Android emulator) — optional

### Install dependencies
```bash
cd timetracker-mobile
npm install
```

### Configure API URL
Edit `app.json`:
```json
"extra": {
  "apiBaseUrl": "https://app.mavops.ai/api"
}
```
For local dev, use your machine's LAN IP: `"http://192.168.1.x:8000/api"`

### Start the dev server
```bash
npx expo start
```
Press `i` for iOS simulator, `a` for Android emulator, or scan QR with Expo Go app.

---

## Phase 2 — Django backend (3–4 hours)

### 1. Copy the mobile app into your Django project
```bash
cp -r timetracker-django/mobile  your_django_project/mobile/
```

### 2. Register the app in settings.py
```python
INSTALLED_APPS = [
    ...
    'mobile',   # ← add this
]
```

### 3. Add URLs to your main urls.py
```python
# your_project/urls.py
urlpatterns = [
    ...
    path('api/mobile/', include('mobile.urls')),
]
```

### 4. Fix the model imports in mobile/views.py
Open `mobile/views.py` and update the import at the top:
```python
# Change this to match YOUR actual model/serializer paths:
from core.models import TimeEntry, Client, Category
from core.serializers import TimeEntrySerializer
```

### 5. Add `source` field to TimeEntry (if not already there)
```python
# In your TimeEntry model:
source = models.CharField(max_length=20, default='desktop', choices=[
    ('desktop', 'Desktop Agent'),
    ('web', 'Web Manual'),
    ('mobile', 'Mobile App'),
])
```
Then: `python manage.py makemigrations && python manage.py migrate`

### 6. Set your OpenAI API key
```bash
# In your .env or Django settings:
OPENAI_API_KEY=sk-...
```
The views use `openai.OpenAI()` which reads `OPENAI_API_KEY` from the environment automatically.

### 7. Test the endpoints
```bash
# Get a token first
curl -X POST https://app.mavops.ai/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"email":"dan@mavops.ai","password":"yourpassword"}'

# Test recent endpoint
curl https://app.mavops.ai/api/mobile/recent/ \
  -H "Authorization: Bearer YOUR_TOKEN"

# Test AI suggest
curl -X POST https://app.mavops.ai/api/mobile/ai-suggest/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"hour": 9, "day_of_week": 4}'
```

---

## Phase 3 — EAS Build (TestFlight + Google Play)

### 1. Create EAS project
```bash
cd timetracker-mobile
eas login          # log in with your Expo account
eas build:configure
```
This updates `app.json` with your EAS project ID.

### 2. Build for iOS (TestFlight)
```bash
eas build --platform ios --profile production
```
EAS handles signing, provisioning profiles, and notarization automatically.
The build uploads to App Store Connect. Then:
```bash
eas submit --platform ios --profile production
```
Go to App Store Connect → TestFlight → add internal testers (you, TL Wall, D&F CPAs).

### 3. Build for Android (Play internal track)
```bash
eas build --platform android --profile production
eas submit --platform android --profile production
```
Requires a Google Play service account JSON — see: https://expo.dev/accounts/guides/google-play-service-account

### 4. Over-the-air updates (no app store review needed for JS changes)
```bash
eas update --branch production --message "Fix AI suggestion threshold"
```
Users get the update automatically on next app launch. Only native code changes require a full build.

---

## AI features — how each one works

### Smart suggestion (HomeScreen)
On app open → `POST /api/mobile/ai-suggest/` with current hour + day_of_week.
Django pulls last 30 entries, sends to GPT-4o-mini with client list → returns predicted client + reason.
Shown as a green banner: "You usually track Dauphin on Friday mornings — Start?"
Confidence threshold: only shown if confidence > 0.6.

### Voice entry (RecordingScreen)
Tap mic → `expo-av` records M4A audio.
On stop → base64 encode → `POST /api/mobile/voice-parse/`.
Django: Whisper API transcribes → GPT-4o parses transcript against your client/category list.
Returns structured `{client_name, category_name, note, is_billable}`.
Auto-fills the recording screen. Say "meeting with Dauphin about Q1 planning" → done.

### AI save prefill (SaveScreen)
When stop sheet opens, if client wasn't set during recording → calls `ai-suggest` again.
AI fills client, category, and billable toggle. User just hits Save.
"AI filled fields from your tracking patterns" badge shows when AI prefilled.

### Calendar matching (HomeScreen)
`expo-calendar` reads today's events (requires permission).
Event titles sent to `POST /api/mobile/calendar-suggest/`.
GPT matches "D&F Strategy Call" → "Dauphin & Fantacone".
Shows banner: "'D&F Strategy Call' is coming up — Dauphin & Fantacone — Start?"

### 2-hour timer alert (backgroundTimer.ts)
On timer start → `scheduleNotificationAsync` fires after 2h.
Background fetch task also checks every 15 min while app is backgrounded.
Push notification: "Still tracking Dauphin & Fantacone? Tap to stop or keep going."

---

## Background timer — important iOS note

iOS kills background tasks aggressively. The timer uses this resilient pattern:

1. On tap → save `{start_time: Date.now(), entry_id}` to `expo-secure-store` (encrypted)
2. App runs normally in foreground, ticking every second via `setInterval`
3. If app is backgrounded/killed → `start_time` persists in SecureStore
4. On app resume → read `start_time`, calculate `Date.now() - start_time` → accurate elapsed time
5. Live Activity (Dynamic Island / lock screen) shows the timer — uses `expo-live-activities`

This means the timer is always accurate even if the app is killed for hours.

---

## Offline support

Entries saved while offline queue in `expo-sqlite` locally.
On reconnect → sync queue to `POST /api/mobile/stop/` for each pending entry.
The `stopTimer` API call handles both: updating an existing draft entry OR creating a fresh entry
if `entry_id` is unknown (started offline).

---

## Deployment checklist

- [ ] Update `apiBaseUrl` in `app.json` to production URL
- [ ] Update bundle IDs: `ai.mavops.timetracker` (iOS) + `ai.mavops.timetracker` (Android)
- [ ] Add `OPENAI_API_KEY` to Django production env
- [ ] Run Django migrations for `source` field on TimeEntry
- [ ] Register `mobile/` app in Django `INSTALLED_APPS`
- [ ] Add `path('api/mobile/', include('mobile.urls'))` to main urls.py
- [ ] Test all 6 endpoints with curl
- [ ] `eas build --platform ios --profile production`
- [ ] Submit to TestFlight: `eas submit --platform ios`
- [ ] Add testers: you + TL Wall + D&F CPAs
- [ ] `eas build --platform android --profile production`
- [ ] Submit to Play internal track

---

## Estimated build time

| Phase | Task | Hours |
|-------|------|-------|
| 1 | Expo setup + local dev running | 1h |
| 2 | Django 6 endpoints + migrations | 3–4h |
| 3 | Polish HomeScreen + animations | 2h |
| 4 | Polish RecordingScreen + voice | 2h |
| 5 | Polish SaveScreen + offline queue | 2h |
| 6 | Background timer + notifications | 2h |
| 7 | EAS build + TestFlight submission | 2h |
| **Total** | | **~15h** |

---

## Questions / next steps

- Add `expo-live-activities` for iOS Dynamic Island timer display
- Add haptic patterns for start/stop (already using `expo-haptics`)
- Add org-level category customization (pull from `/api/categories/` — already wired)
- Add Stripe seat check before allowing app login (reuse existing subscription gate)
