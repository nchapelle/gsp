# Public Events - Quick Start Guide

## What's New?

GSP now has a **public events page** at `https://www.gspevents.com/events` that automatically displays posted events with links to their Facebook posts.

## For SMM Team

### What Changed in Your Workflow?

**When you mark an event as "posted":**
1. You still enter the Facebook event URL (same as before)
2. You click "Mark as Posted" (same as before)
3. **NEW:** The event **instantly appears on www.gspevents.com** for the public to see
4. Success message now says: "Event marked as posted and published to www.gspevents.com!"

### That's It!

No extra steps. Your posted events are automatically published to the public site.

---

## For Admins/Developers

### 1. Deploy the Backend Update

```bash
cd /path/to/GSP/backend
gcloud builds submit --config cloudbuild.yaml .
```

Verify deployment:
```bash
curl -X POST https://api.gspevents.com/migrate
curl https://api.gspevents.com/doctor
```

### 2. Deploy the Public Page

**Option A: Firebase Hosting** (Easiest)
```bash
cp frontend/public-events.html dist/
cp frontend/assets/public-events.js dist/assets/
firebase deploy --only hosting
```

**Option B: Squarespace** (Most Visual)
- See "Squarespace Integration" in `PUBLIC_EVENTS_SETUP.md`

**Option C: Your Own Hosting**
- Upload `frontend/public-events.html` and `frontend/assets/public-events.js` to your server

### 3. Test It

1. Create an event via Host Portal
2. Validate it via Admin Portal
3. Post it via SMM Dashboard (with FB URL)
4. Check `https://www.gspevents.com/events` - event should appear within seconds

---

## How It Works (High Level)

```
SMM posts event with FB URL
            ↓
Database marks it as "posted"
            ↓
Public API endpoint returns it
            ↓
www.gspevents.com automatically displays it
            ↓
Search engines crawl and index it
            ↓
Facebook/Google users can discover it
```

---

## API Endpoint

```
GET https://api.gspevents.com/public/events
```

Returns all posted events in JSON format:
- Event date & venue
- Host name
- Event recap (AI-generated)
- Photos (up to 5)
- Facebook event URL
- PDF recap document
- Validation status

**No authentication required** - this is public data.

---

## Key Features

✅ **Automatic Updates** - Posted events appear instantly on public page
✅ **SEO Optimized** - Search engines can find and index events
✅ **Social Media Ready** - Facebook post links, Open Graph tags
✅ **Mobile Responsive** - Works on phones, tablets, desktop
✅ **No Extra Work** - SMM just posts as normal
✅ **Squarespace Compatible** - Can embed in Squarespace site
✅ **Cached** - Fast loading with 5-minute browser cache

---

## Environment Variables

Already configured in `env.list`:
```bash
ALLOWED_ORIGINS=https://www.gspevents.com|https://app.gspevents.com|https://gspevents.squarespace.com
```

No changes needed.

---

## Troubleshooting

### Events not showing on public page?

1. **Check API:**
   ```bash
   curl https://api.gspevents.com/public/events
   ```
   Should return JSON array of posted events.

2. **Check database:**
   ```bash
   curl https://api.gspevents.com/admin/events?status=posted
   ```

3. **Check browser console** for JavaScript errors (F12 → Console tab)

### Getting CORS errors?

Add your domain to `ALLOWED_ORIGINS` in `env.list`, then redeploy:
```bash
gcloud builds submit --config backend/cloudbuild.yaml .
```

### Images not loading?

Verify GCS bucket permissions and check `GCS_BUCKET` environment variable.

---

## For More Details

- **Setup Guide**: `PUBLIC_EVENTS_SETUP.md`
- **Technical Implementation**: `PUBLIC_EVENTS_IMPLEMENTATION.md`
- **JavaScript API**: See `frontend/assets/public-events.js`

---

## Deployment Checklist

- [ ] Backend deployed with new endpoint
- [ ] Public page deployed (HTML + JS)
- [ ] Test event posted and appears on public site
- [ ] Team notified of new "posted" confirmation message
- [ ] Squarespace configured (if applicable)
- [ ] Google Search Console updated with new URLs

---

## Questions?

Contact development team or check `PUBLIC_EVENTS_SETUP.md` FAQ section.

---

## One-Minute Summary

**What:** GSP now has a public-facing events page
**Where:** www.gspevents.com/events
**When:** Updates automatically when SMM posts events
**Why:** Better SEO, consistency, public engagement
**How:** No changes needed for SMM - it's automatic!
