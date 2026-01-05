# GSP Events Authentication Deployment Guide

**Date:** January 5, 2026  
**Migration Period:** January 5 - January 31, 2026  
**Legacy Token Removal:** February 1, 2026

## Overview

This guide walks you through deploying Google Firebase authentication with three user roles (admin, host, SMM) to the GSP Events platform.

## Prerequisites

✅ Database migration SQL already executed  
✅ Firebase project created (or existing project ready to use)  
✅ Google Cloud project with Cloud Run and Firebase Admin SDK enabled

---

## Step 1: Firebase Project Setup

### 1.1 Create or Access Firebase Project

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Create new project or select existing GSP Events project
3. Note your **Project ID** (e.g., `gspevents-12345`)

### 1.2 Enable Firebase Authentication

1. In Firebase Console, go to **Authentication** > **Get Started**
2. Click **Sign-in method** tab
3. Enable **Google** provider
4. Add authorized domain: `app.gspevents.com`
5. Save changes

### 1.3 Get Firebase Web Configuration

1. Go to **Project Settings** (gear icon) > **General**
2. Scroll to "Your apps" > **Web apps** section
3. If no web app exists, click **Add app** and create one
4. Copy the `firebaseConfig` object values:
   ```javascript
   {
     apiKey: "AIza...",
     authDomain: "gspevents-12345.firebaseapp.com",
     projectId: "gspevents-12345"
   }
   ```

---

## Step 2: Update Frontend Configuration

### 2.1 Update Firebase Config

Edit `frontend/assets/config.js` and replace the placeholder values:

```javascript
const firebaseConfig = {
  apiKey: "YOUR_ACTUAL_API_KEY",           // Replace this
  authDomain: "YOUR_PROJECT.firebaseapp.com",  // Replace this
  projectId: "YOUR_PROJECT_ID"              // Replace this
};
```

### 2.2 Deploy Frontend to Firebase Hosting

```bash
cd frontend
firebase deploy --only hosting
```

---

## Step 3: Backend Setup

### 3.1 Enable Firebase Admin SDK in Cloud Run

Your Cloud Run service needs permission to verify Firebase tokens. This is automatic if using the same Google Cloud project.

**Verify Service Account Permissions:**

```bash
# Get your Cloud Run service account
gcloud run services describe api-gspevents --region=us-central1 --format="value(spec.template.spec.serviceAccountName)"

# Ensure it has these roles:
# - Firebase Admin SDK Service Agent
# - Cloud Run Service Agent
```

If using a different project for Firebase, add the service account email to Firebase:
1. Go to Firebase Console > Project Settings > Service Accounts
2. Click **Manage service account permissions**
3. Add your Cloud Run SA with role: **Firebase Admin SDK Administrator Service Agent**

### 3.2 Install Dependencies and Deploy Backend

```bash
cd backend

# Deploy with new dependencies
gcloud builds submit --config cloudbuild.yaml .
```

### 3.3 Run Database Migration (if not already done)

```bash
# Trigger migration endpoint
curl -X POST https://api.gspevents.com/migrate

# Check health
curl https://api.gspevents.com/doctor
```

---

## Step 4: Create Initial Users

### 4.1 Update Seed Admin Email

If you haven't yet, update the SQL seed user with your actual admin email:

```sql
UPDATE users 
SET email = 'your-actual-admin-email@gmail.com',
    display_name = 'Your Name'
WHERE email = 'your-email@gmail.com';
```

### 4.2 First Login

1. Visit `https://app.gspevents.com/hosts.html`
2. Click "Sign in with Google"
3. Sign in with your admin email
4. Your user record will be created/updated automatically

### 4.3 Promote to Admin (if needed)

If your account wasn't seeded as admin:

```sql
UPDATE users 
SET role = 'admin' 
WHERE email = 'your-actual-admin-email@gmail.com';
```

---

## Step 5: Add Additional Users

### Option A: Via SQL (Recommended for initial setup)

```sql
-- Add host user
INSERT INTO users (firebase_uid, email, display_name, role, is_active)
VALUES ('PLACEHOLDER', 'host@example.com', 'Host Name', 'host', true)
ON CONFLICT (email) DO UPDATE SET role = 'host';

-- Add SMM user
INSERT INTO users (firebase_uid, email, display_name, role, is_active)
VALUES ('PLACEHOLDER', 'smm@example.com', 'Social Media Manager', 'smm', true)
ON CONFLICT (email) DO UPDATE SET role = 'smm';
```

**Note:** `firebase_uid` will be updated automatically on first login.

### Option B: Via Admin UI (Coming in future release)

Navigate to admin panel and use user management interface.

---

## Step 6: Test Authentication

### 6.1 Test Host Access

1. Visit `https://app.gspevents.com/hosts.html`
2. Sign in with host account
3. Verify you can create events
4. Try accessing `https://app.gspevents.com/admin.html` - should be denied

### 6.2 Test SMM Access

1. Visit `https://app.gspevents.com/smm.html`
2. Sign in with SMM account
3. Verify you can edit AI recaps
4. Try accessing `https://app.gspevents.com/hosts.html` - should be denied

### 6.3 Test Admin Access

1. Visit `https://app.gspevents.com/admin.html`
2. Sign in with admin account
3. Verify you can access all pages
4. Test user management endpoints:

```bash
# Get current user profile
curl -H "Authorization: Bearer YOUR_FIREBASE_TOKEN" \
  https://api.gspevents.com/api/user/me

# List all users (admin only)
curl -H "Authorization: Bearer YOUR_FIREBASE_TOKEN" \
  https://api.gspevents.com/api/users
```

---

## Step 7: Migration Period (Through Jan 31)

### Legacy Token Still Works

The old `HOST_API_TOKEN` authentication will continue working until February 1, 2026. This allows:
- Existing bookmarked URLs with `?t=TOKEN` to work
- Time for all users to migrate to Google Sign-In
- Gradual rollout without breaking existing workflows

### Monitoring Migration

Check which authentication method is being used:

```sql
-- Events created via Firebase vs legacy token
SELECT 
  created_via,
  COUNT(*) as event_count
FROM events
WHERE created_at > '2026-01-05'
GROUP BY created_via;

-- Active users by role
SELECT 
  role,
  COUNT(*) as user_count,
  COUNT(DISTINCT firebase_uid) as unique_logins
FROM users
WHERE is_active = true
GROUP BY role;
```

---

## Step 8: Remove Legacy Token (Feb 1, 2026)

### 8.1 Verify All Users Migrated

```sql
-- Check for recent legacy token usage
SELECT COUNT(*) 
FROM events 
WHERE created_via = 'legacy_token' 
  AND created_at > NOW() - INTERVAL '7 days';
```

If count is 0, proceed with removal.

### 8.2 Update Backend Code

In `backend/app.py`, the legacy token support will automatically stop working after `MIGRATION_END_DATE = datetime(2026, 2, 1)`.

No code changes needed - the system self-disables.

### 8.3 Remove Environment Variable (Optional)

```bash
# Remove HOST_API_TOKEN from Cloud Run environment
gcloud run services update api-gspevents \
  --region=us-central1 \
  --remove-env-vars=HOST_API_TOKEN
```

---

## Troubleshooting

### "Firebase not initialized" Error

**Cause:** Firebase SDK scripts not loaded or config incorrect  
**Fix:** Check browser console, verify script tags in HTML head

### "Unauthorized" on API Calls

**Cause:** Firebase token not being sent or expired  
**Fix:** Check `Authorization: Bearer ...` header in Network tab

### "Access Denied" After Login

**Cause:** User has wrong role for page  
**Fix:** Update user role in database:
```sql
UPDATE users SET role = 'admin' WHERE email = 'user@example.com';
```

### Firebase Token Verification Fails on Backend

**Cause:** Service account lacks Firebase Admin permissions  
**Fix:** Grant service account "Firebase Admin SDK Administrator Service Agent" role

### User Can't Sign In

**Cause:** Email not in users table or is_active = false  
**Fix:** Check user status:
```sql
SELECT * FROM users WHERE email = 'user@example.com';
-- If exists but inactive:
UPDATE users SET is_active = true WHERE email = 'user@example.com';
```

---

## Security Best Practices

✅ **Remove legacy token after migration period**  
✅ **Regularly audit user_activity_log for suspicious activity**  
✅ **Review and update user roles quarterly**  
✅ **Enable Cloud Run ingress controls** (allow only Firebase Hosting)  
✅ **Monitor failed authentication attempts**

```sql
-- Check failed auth attempts (in future with logging)
SELECT 
  action,
  ip_address,
  COUNT(*) as attempts
FROM user_activity_log
WHERE action = 'auth_failed'
  AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY action, ip_address
HAVING COUNT(*) > 10;
```

---

## User Management Reference

### Grant Admin Access
```sql
UPDATE users SET role = 'admin' WHERE email = 'user@example.com';
```

### Revoke Access (Soft Delete)
```sql
UPDATE users SET is_active = false WHERE email = 'user@example.com';
```

### Change User Role
```sql
UPDATE users SET role = 'smm' WHERE email = 'user@example.com';
```

### View User Activity
```sql
SELECT 
  u.email,
  ual.action,
  ual.resource_type,
  ual.created_at
FROM user_activity_log ual
JOIN users u ON ual.user_id = u.id
WHERE u.email = 'user@example.com'
ORDER BY ual.created_at DESC
LIMIT 50;
```

---

## API Endpoints Reference

### User Endpoints

| Endpoint | Method | Role | Description |
|----------|--------|------|-------------|
| `/api/user/me` | GET | Any | Get current user profile |
| `/api/user/me` | PUT | Any | Update display name |
| `/api/users` | GET | Admin | List all users |
| `/api/users/:id` | PUT | Admin | Update user role/status |
| `/api/users/activity` | GET | Admin | View activity log |

### Example: Update User Role (Admin Only)

```bash
curl -X PUT https://api.gspevents.com/api/users/5 \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "smm", "is_active": true}'
```

---

## Support

For issues during deployment:
1. Check [backend logs](https://console.cloud.google.com/run/detail/us-central1/api-gspevents/logs)
2. Review browser console for frontend errors
3. Test with `/doctor` endpoint health check
4. Verify database migrations with `\d users` in psql

**Deployment complete! All pages now protected with Google Sign-In authentication.**
