# 🚀 GSP Authentication Quick Start

## Pre-Deployment Checklist

### ✅ Database
- [ ] SQL migration executed successfully
- [ ] `users` table created with seed admin user
- [ ] Seed admin email updated to your actual email
- [ ] `user_activity_log` table created
- [ ] Events and event_photos tables have new user tracking columns

### ✅ Firebase Setup
- [ ] Firebase project created
- [ ] Google Sign-In provider enabled
- [ ] Authorized domain added: `app.gspevents.com`
- [ ] Web app config copied (apiKey, authDomain, projectId)

### ✅ Code Configuration
- [ ] `frontend/assets/config.js` updated with real Firebase config (lines 3-7)
- [ ] Firebase config values NOT placeholders

### ✅ Backend
- [ ] `firebase-admin` added to requirements.txt ✓
- [ ] Service account has Firebase Admin permissions
- [ ] `HOST_API_TOKEN` still set in Cloud Run (for migration period)

---

## Deployment Steps (5 minutes)

### 1️⃣ Deploy Backend
```bash
cd backend
gcloud builds submit --config cloudbuild.yaml .
```
**Wait for:** Build complete, service deployed

### 2️⃣ Deploy Frontend
```bash
cd frontend
firebase deploy --only hosting
```
**Wait for:** Deploy complete

### 3️⃣ Test Health
```bash
# Check backend is up and Firebase initialized
curl https://api.gspevents.com/doctor

# Should see in logs: "Firebase Admin initialized successfully"
```

---

## First Login (2 minutes)

### 1️⃣ Visit Host Portal
Go to: `https://app.gspevents.com/hosts.html`

### 2️⃣ Sign In
Click "Sign in with Google" and use your admin email

### 3️⃣ Verify Role
You should see:
- Your email in the header
- **ADMIN** badge next to your name
- Access to create events

### 4️⃣ Test Permissions
Try visiting these pages - all should work:
- ✅ `https://app.gspevents.com/hosts.html` (host access)
- ✅ `https://app.gspevents.com/admin.html` (admin access)
- ✅ `https://app.gspevents.com/smm.html` (SMM access - admin has all)

---

## Add Users (30 seconds each)

### Method 1: SQL (Fastest)
```sql
-- Add host user
INSERT INTO users (firebase_uid, email, display_name, role, is_active)
VALUES ('TEMP', 'host@example.com', 'Host Name', 'host', true)
ON CONFLICT (email) DO UPDATE SET role = 'host';

-- Add SMM user  
INSERT INTO users (firebase_uid, email, display_name, role, is_active)
VALUES ('TEMP', 'smm@example.com', 'SMM Name', 'smm', true)
ON CONFLICT (email) DO UPDATE SET role = 'smm';
```

### Method 2: After They Sign In
1. User signs in with Google (auto-creates with 'host' role)
2. Change their role:
```sql
UPDATE users SET role = 'admin' WHERE email = 'user@example.com';
```

---

## Testing Checklist (3 minutes)

### Host User Test
- [ ] Sign in to hosts.html
- [ ] See HOST badge in header
- [ ] Can create events
- [ ] Can upload photos
- [ ] CANNOT access admin.html (Access Denied)
- [ ] CANNOT access smm.html (Access Denied)

### SMM User Test
- [ ] Sign in to smm.html
- [ ] See SMM badge in header
- [ ] Can edit AI recaps
- [ ] Can view events
- [ ] CANNOT access admin.html (Access Denied)
- [ ] CANNOT access hosts.html (Access Denied)

### Admin User Test
- [ ] Sign in to admin.html
- [ ] See ADMIN badge in header
- [ ] Can access ALL pages
- [ ] Can create events
- [ ] Can edit AI recaps
- [ ] Can manage data

---

## Verify Database Tracking

```sql
-- Check users created
SELECT id, email, role, is_active, last_login 
FROM users 
ORDER BY created_at DESC;

-- Check events track creators
SELECT 
  e.id,
  e.event_date,
  e.created_via,
  e.created_by_email,
  u.role as creator_role
FROM events e
LEFT JOIN users u ON e.created_by_user_id = u.id
WHERE e.created_at > NOW() - INTERVAL '1 day'
ORDER BY e.created_at DESC;

-- Check activity log working
SELECT 
  u.email,
  ual.action,
  ual.resource_type,
  ual.created_at
FROM user_activity_log ual
JOIN users u ON ual.user_id = u.id
ORDER BY ual.created_at DESC
LIMIT 10;
```

---

## Troubleshooting

### ❌ "Firebase not initialized" 
**Fix:** Check Firebase config in config.js has real values (not placeholders)

### ❌ "Unauthorized" on API calls
**Fix:** Check Authorization header in Network tab. If missing:
1. Ensure you're signed in
2. Refresh page
3. Check browser console for errors

### ❌ "Access Denied" for admin user
**Fix:** Check role in database:
```sql
SELECT email, role FROM users WHERE email = 'your-email@gmail.com';
-- If wrong role:
UPDATE users SET role = 'admin' WHERE email = 'your-email@gmail.com';
```

### ❌ Can't sign in at all
**Fix:** Check Firebase Console:
1. Is Google provider enabled?
2. Is app.gspevents.com in authorized domains?
3. Check browser console for Firebase errors

### ❌ Backend 500 errors
**Fix:** Check Cloud Run logs:
```bash
gcloud run services logs read api-gspevents --region=us-central1 --limit=50
```
Look for "Firebase Admin init failed" or token verification errors

---

## Migration Monitoring

### Check Authentication Usage
```sql
-- Events by auth method (last 7 days)
SELECT 
  created_via,
  COUNT(*) as count
FROM events
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY created_via;

-- Expected to see:
-- firebase: increasing
-- legacy_token: decreasing
```

### When to Remove Legacy Token
Once `legacy_token` count is 0 for a full week, it's safe to remove.

**Auto-Removal:** Legacy token stops working automatically on Feb 1, 2026

---

## Success Criteria ✓

All these should be TRUE:
- ✅ Can sign in with Google on any protected page
- ✅ See email and role badge in header
- ✅ Host users cannot access admin pages
- ✅ SMM users cannot access host pages  
- ✅ Admin users can access everything
- ✅ New events track who created them
- ✅ Photo uploads track who uploaded them
- ✅ Activity log records actions
- ✅ Legacy token still works (until Feb 1)

---

## Timeline

| Date | Milestone |
|------|-----------|
| **Today** | Deploy auth system, test with admin account |
| **Jan 5-10** | Add all host users, have them test |
| **Jan 10-20** | Add SMM users, migrate workflows |
| **Jan 20-31** | Monitor usage, ensure no legacy token dependency |
| **Feb 1** | Legacy token auto-disables |

---

## Support Contacts

**Backend logs:** [Cloud Run Logs](https://console.cloud.google.com/run/detail/us-central1/api-gspevents/logs)  
**Firebase Console:** [Firebase Authentication](https://console.firebase.google.com/)  
**Database:** Connect via Neon console or psql

---

**Ready to deploy! Start with Step 1: Deploy Backend** 🚀
