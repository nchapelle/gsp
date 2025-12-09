# Public Events Page Setup Guide

This guide explains how to set up the public-facing GSP Events page on `www.gspevents.com` with Squarespace and enable automatic updates when the SMM posts events.

## Overview

The public events page displays posted events with:
- Event date, venue, and host information
- Event photos in a responsive grid
- AI-generated recap text
- Links to Facebook posts
- PDF recap documents
- SEO-optimized structured data for search engines

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  www.gspevents.com (Squarespace or Firebase Hosting)            │
│  ├── public-events.html (SEO-optimized landing page)            │
│  └── assets/public-events.js (API client + rendering)           │
└────────────────────────────────┬────────────────────────────────┘
                                 │ Fetches events via API
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│  api.gspevents.com/public/events (Public API Endpoint)          │
│  ├── Returns only events with status='posted'                   │
│  ├── Includes FB URLs for links                                 │
│  ├── Cached for 5 minutes (browser-side)                        │
│  └── No authentication required                                 │
└────────────────────────────────┬────────────────────────────────┘
                                 │ Queries
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│  PostgreSQL (Neon)                                              │
│  └── events table (status, fb_event_url, ai_recap, photos)     │
└────────────────────────────────────────────────────────────────┘
```

## Step 1: Update Backend Environment Variables

Ensure your Cloud Run environment includes the following in `env.list`:

```bash
# CORS: Allow both app.gspevents.com and www.gspevents.com
ALLOWED_ORIGINS=https://www.gspevents.com|https://app.gspevents.com|https://gspevents.squarespace.com

# Base URL for public links (keep this as-is)
PUBLIC_BASE=https://app.gspevents.com
```

**Deploy these changes:**

```bash
gcloud builds submit --config backend/cloudbuild.yaml .

# After deployment, verify:
curl -X POST https://api.gspevents.com/migrate
curl https://api.gspevents.com/doctor
```

## Step 2: Deploy the Public Events Page

### Option A: Firebase Hosting (Recommended)

Add the public page to your Firebase hosting:

```bash
# Copy the public events page
cp frontend/public-events.html dist/
cp frontend/assets/public-events.js dist/assets/

# Deploy to Firebase
firebase deploy --only hosting
```

Then configure a redirect or subdomain in Firebase to serve it at `/events`:

In `firebase.json`:
```json
{
  "hosting": {
    "public": "dist",
    "rewrites": [
      {
        "source": "/events",
        "destination": "/public-events.html"
      }
    ]
  }
}
```

### Option B: Squarespace Integration

1. **Create a new page** in Squarespace called "Events"
2. **Add a Code Block** to the page
3. **Paste this code:**

```html
<div id="gsp-events-widget"></div>
<script src="https://app.gspevents.com/assets/public-events.js"></script>
<script>
  GSPPublicEvents.renderEvents('gsp-events-widget', {
    limit: 50,
    template: 'blog-post'
  });
</script>
```

4. **Optional:** For SEO meta tags, update Squarespace page settings:
   - Title: "GSP Events - Tournament Results & Highlights"
   - Meta Description: "Discover the latest recreational softball tournament results and highlights from GSP Events."

### Option C: Static Hosting (www.gspevents.com)

Deploy `frontend/public-events.html` directly to your web host:

```bash
# Upload to web server
scp frontend/public-events.html user@www.gspevents.com:/var/www/html/events/index.html
```

## Step 3: Update SMM Dashboard Confirmation

When the SMM marks an event as "posted" with a Facebook URL, they'll see:

```
✓ Event marked as posted and published to www.gspevents.com!
```

The event **automatically appears on the public page** within seconds due to:
1. Real-time status update in the database
2. Public API returns only posted events
3. Client-side caching refreshes every 5 minutes

## Step 4: Enable Real-Time Updates (Optional)

For live updates without page refresh, add polling to your public page:

```javascript
// In your HTML page, after GSPPublicEvents is loaded:
const pollInterval = GSPPublicEvents.startPolling(60000, (events) => {
  console.log('Events updated:', events.length);
  // Re-render if needed
  GSPPublicEvents.renderEvents('container-id');
});

// Stop polling when page unloads
window.addEventListener('beforeunload', () => clearInterval(pollInterval));
```

## API Reference

### Public Events Endpoint

```
GET https://api.gspevents.com/public/events
```

**Response:**
```json
[
  {
    "id": 123,
    "date": "2024-12-15",
    "date_display": "December 15, 2024",
    "venue": "Central Park",
    "host": "John Smith",
    "ai_recap": "Great tournament with competitive teams...",
    "highlights": "Team A won in overtime",
    "fb_event_url": "https://facebook.com/events/...",
    "pdf_url": "https://storage.googleapis.com/...",
    "photos": ["url1", "url2", "url3"],
    "photo_count": 3,
    "is_validated": true,
    "status": "posted"
  }
]
```

### JavaScript Library

```javascript
// Load all posted events
const events = await GSPPublicEvents.fetchEvents();

// Get recent events (last 5)
const recent = await GSPPublicEvents.getRecentEvents(5);

// Get events for a specific venue
const venueEvents = await GSPPublicEvents.getEventsByVenue('Central Park');

// Render events into a container
GSPPublicEvents.renderEvents('container-id', {
  limit: 10,
  venue: 'Central Park',  // optional filter
  template: 'blog-post'   // or 'list'
});

// Get SEO structured data (JSON-LD)
const schemaData = await GSPPublicEvents.getStructuredData();

// Inject schema directly into page
GSPPublicEvents.injectStructuredData();

// Start real-time polling
const pollInterval = GSPPublicEvents.startPolling(
  5 * 60 * 1000,  // 5 minutes
  (events) => console.log('Updated events:', events)
);
```

## SEO Best Practices

The public events page includes:

### Meta Tags
- `<meta name="robots" content="index, follow">` - Allow search indexing
- Open Graph tags for social sharing
- Twitter Card tags for Twitter sharing

### Structured Data
- JSON-LD schema using `https://schema.org/Event`
- Automatically injected by `public-events.js`

### Performance
- Client-side caching (5 minutes)
- Image lazy loading
- Optimized CSS and minimal dependencies

## Troubleshooting

### Events not appearing on public page

1. **Check backend:**
   ```bash
   # Verify CORS settings
   curl -H "Origin: https://www.gspevents.com" https://api.gspevents.com/public/events -v
   
   # Check for posted events
   curl https://api.gspevents.com/public/events | jq
   ```

2. **Check database:**
   ```sql
   SELECT id, venue, status, fb_event_url FROM events 
   WHERE status='posted' ORDER BY event_date DESC;
   ```

3. **Check browser console** for JavaScript errors

### CORS errors

Add the domain to `ALLOWED_ORIGINS` in `env.list`:

```bash
ALLOWED_ORIGINS=https://www.gspevents.com|https://app.gspevents.com|https://new-domain.com
```

Then redeploy:
```bash
gcloud builds submit --config backend/cloudbuild.yaml .
```

### Images not loading

- Verify Google Cloud Storage bucket permissions
- Check that `GCS_BUCKET` is correctly set
- Ensure service account has `roles/storage.objectViewer` role

## Monitoring

Track public page performance:

```javascript
// Add to public-events.html
window.addEventListener('error', (event) => {
  console.error('Page error:', event.error);
  // Send to analytics/error tracking
});

// Track API call performance
const start = performance.now();
GSPPublicEvents.fetchEvents().then(() => {
  console.log('API call took', performance.now() - start, 'ms');
});
```

## FAQ

**Q: Can I customize the event display?**
A: Yes! Use the `public-events.js` library. See the API Reference section above.

**Q: How often do events update on the public page?**
A: Browser-side cache refreshes every 5 minutes. You can reduce this or enable polling.

**Q: Do I need authentication for the public API?**
A: No! `/public/events` requires no token. It only shows posted events (status='posted').

**Q: Can I embed this on external websites?**
A: Yes! Use the iframe approach or include the JavaScript library and call `GSPPublicEvents.renderEvents()`.

**Q: What if I want to show only certain venues?**
A: Use the venue filter in JavaScript:
   ```javascript
   GSPPublicEvents.renderEvents('container', { venue: 'Central Park' });
   ```

## Next Steps

1. Deploy backend with updated `ALLOWED_ORIGINS`
2. Copy `public-events.html` and `public-events.js` to your web host
3. Test at `https://www.gspevents.com/events` (or your domain)
4. Configure SMM to include FB URLs when posting
5. Monitor the public page for updates

For questions or issues, check the API logs:

```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=gsp-backend-api" --limit 50
```
