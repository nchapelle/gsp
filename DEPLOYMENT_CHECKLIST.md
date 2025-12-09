# Deployment Checklist - GSP Public Events

## Pre-Deployment

### Verification
- [ ] All files created successfully
  - [ ] `frontend/public-events.html` exists
  - [ ] `frontend/assets/public-events.js` exists
  - [ ] `backend/app.py` has new `/public/events` endpoint
  - [ ] Documentation files created

- [ ] Code reviewed
  - [ ] Python endpoint syntax correct
  - [ ] JavaScript code tested locally
  - [ ] HTML page displays correctly
  - [ ] No console errors in browser

- [ ] Environment verified
  - [ ] `ALLOWED_ORIGINS` includes www.gspevents.com
  - [ ] `GCS_BUCKET` is set
  - [ ] Database credentials valid
  - [ ] Cloud Run service ready

## Deployment - Phase 1: Backend

- [ ] **Build & Deploy Backend**
  ```bash
  cd backend
  gcloud builds submit --config cloudbuild.yaml .
  ```
  - [ ] Build succeeded (check Cloud Build logs)
  - [ ] Deployment succeeded (check Cloud Run console)

- [ ] **Post-Deployment Verification**
  ```bash
  curl -X POST https://api.gspevents.com/migrate
  curl https://api.gspevents.com/doctor
  ```
  - [ ] Migrate succeeded (no errors)
  - [ ] Doctor check passed
  - [ ] Health check shows "ok"

- [ ] **Test Public Endpoint**
  ```bash
  curl https://api.gspevents.com/public/events | jq
  ```
  - [ ] Returns valid JSON array
  - [ ] Response time acceptable
  - [ ] No 500 errors in logs

- [ ] **Test CORS**
  ```bash
  curl -H "Origin: https://www.gspevents.com" \
    https://api.gspevents.com/public/events -v
  ```
  - [ ] `Access-Control-Allow-Origin` header present
  - [ ] Shows `https://www.gspevents.com`

## Deployment - Phase 2: Frontend

### Option A: Firebase Hosting
- [ ] Copy files to dist/
  ```bash
  cp frontend/public-events.html dist/
  cp frontend/assets/public-events.js dist/assets/
  ```

- [ ] Update firebase.json (if needed)
  ```json
  {
    "rewrites": [
      {
        "source": "/events",
        "destination": "/public-events.html"
      }
    ]
  }
  ```

- [ ] Deploy
  ```bash
  firebase deploy --only hosting
  ```
  - [ ] Deployment succeeded
  - [ ] No errors in Firebase console

- [ ] Verify deployment
  - [ ] `https://app.gspevents.com/events` loads
  - [ ] JavaScript loads correctly
  - [ ] No console errors

### Option B: Squarespace
- [ ] Create new page "Events"
- [ ] Add Code Block
- [ ] Paste code snippet:
  ```html
  <div id="gsp-events-widget"></div>
  <script src="https://app.gspevents.com/assets/public-events.js"></script>
  <script>
    GSPPublicEvents.renderEvents('gsp-events-widget', {limit: 50});
  </script>
  ```
- [ ] Publish page
- [ ] Verify at www.gspevents.com/events
  - [ ] Page loads
  - [ ] No console errors
  - [ ] Events display (or empty state if no posted events)

### Option C: Static Hosting
- [ ] Upload `public-events.html` to `/events/index.html`
- [ ] Upload `public-events.js` to `/assets/`
- [ ] Verify files accessible via browser
- [ ] Check permissions (public readable)

## Testing - Phase 3: Integration

### Manual Event Workflow
- [ ] **Create Event** (Host Portal)
  - [ ] Fill form, upload PDF and photos
  - [ ] Confirm event created with ID

- [ ] **Validate Event** (Admin Portal)
  - [ ] Event appears in admin list
  - [ ] Mark as validated

- [ ] **Post Event** (SMM Dashboard)
  - [ ] Event in "Unposted" list
  - [ ] Add Facebook URL
  - [ ] Mark as "posted"
  - [ ] Success message shows "published to www.gspevents.com"

- [ ] **Verify Public Visibility**
  - [ ] Check API endpoint
    ```bash
    curl https://api.gspevents.com/public/events | jq
    ```
    - [ ] Event appears in response

  - [ ] Check www.gspevents.com/events
    - [ ] Event displays in blog-post format
    - [ ] Photos load correctly
    - [ ] FB link is clickable
    - [ ] Recap text displays

### Browser Testing
- [ ] **Desktop Chrome**
  - [ ] Page loads
  - [ ] Events display
  - [ ] No console errors
  - [ ] FB link works

- [ ] **Desktop Firefox**
  - [ ] Page loads
  - [ ] Events display
  - [ ] No console errors

- [ ] **Mobile Chrome**
  - [ ] Page responsive
  - [ ] Events display in mobile layout
  - [ ] Photos visible
  - [ ] Links clickable

- [ ] **Mobile Safari**
  - [ ] Page loads
  - [ ] Responsive layout
  - [ ] Images load

- [ ] **Tablet (iPad/Android)**
  - [ ] Layout looks good
  - [ ] Touch-friendly
  - [ ] No layout issues

### Cache Testing
- [ ] Hard refresh page (Ctrl+Shift+R)
  - [ ] Events still display

- [ ] Wait 5 minutes, post new event
  - [ ] New event appears within 5 minutes

- [ ] Clear browser cache
  - [ ] Page still works

### SEO Testing
- [ ] Inspect page source (Ctrl+U)
  - [ ] `<meta name="description">` present
  - [ ] `<meta property="og:title">` present
  - [ ] `<meta property="og:image">` present
  - [ ] `<meta name="robots" content="index, follow">` present

- [ ] Check structured data (in console)
  - [ ] JSON-LD script tag present
  - [ ] Valid schema.org/Event format

## Post-Deployment

### Team Notification
- [ ] Send `QUICK_START_PUBLIC_EVENTS.md` to SMM team
- [ ] Brief team on new feature
- [ ] Show where events appear
- [ ] Explain no workflow changes needed

### Analytics Setup (Optional)
- [ ] Google Analytics configured
- [ ] Facebook Pixel tracking added
- [ ] Monitor click-through rates

### Monitoring
- [ ] Set up Cloud Run logs monitoring
- [ ] Monitor API response times
- [ ] Watch for errors in past 24 hours
  ```bash
  gcloud logging read \
    "resource.type=cloud_run_revision AND resource.labels.service_name=gsp-backend-api" \
    --limit 100
  ```

- [ ] Check database performance
  - [ ] Query times acceptable
  - [ ] No slow queries

### DNS & Routing (if using custom domain)
- [ ] DNS records configured
  - [ ] A record points to hosting
  - [ ] CNAME configured (if applicable)
  
- [ ] SSL/TLS certificate valid
  - [ ] HTTPS works
  - [ ] No certificate warnings

- [ ] Redirects working
  - [ ] www.gspevents.com/events loads
  - [ ] No mixed content warnings

## Success Criteria

All of these should be true:

- ✅ Backend `/public/events` endpoint returns JSON
- ✅ API endpoint includes recently posted events
- ✅ Public website loads without errors
- ✅ Posted events appear within 5 minutes
- ✅ FB post links are clickable and correct
- ✅ Photos display in gallery
- ✅ Mobile version is responsive
- ✅ No JavaScript errors in console
- ✅ SEO meta tags present in page source
- ✅ CORS headers correct
- ✅ Cache working (5-minute duration)
- ✅ Team confirmed feature works

## Rollback Plan (If Needed)

### If Backend Fails
```bash
# Revert to previous build
gcloud run deploy gsp-backend-api --region us-east1 \
  --image gcr.io/YOUR_PROJECT/gsp-backend-api:PREVIOUS_TAG
```

### If Frontend Fails
```bash
# Firebase: Revert to previous version
firebase hosting:channels:list
firebase hosting:clone PREVIOUS_VERSION_ID production

# Or manually delete the new version
rm dist/public-events.html
firebase deploy --only hosting
```

## Sign-Off

- [ ] Development - Code reviewed
  - Reviewer: _______________
  - Date: _______________

- [ ] Testing - All tests passed
  - Tester: _______________
  - Date: _______________

- [ ] Deployment - Live and working
  - Deployed by: _______________
  - Date: _______________

- [ ] Team - Notified and trained
  - Notified by: _______________
  - Date: _______________

---

## Deployment Date & Time

**Planned Deployment:** _______________

**Actual Backend Deploy:** _______________

**Actual Frontend Deploy:** _______________

**Go-Live Time:** _______________

---

## Notes & Issues Encountered

```
[Document any issues, resolutions, or special notes here]




```

---

## Post-Deployment Monitoring

### First 24 Hours
- [ ] Monitor API response times
- [ ] Check error rate (should be <1%)
- [ ] Verify cache functioning
- [ ] Watch for user issues

### First Week
- [ ] Monitor page analytics
- [ ] Check search console
- [ ] Track click-through rates
- [ ] Gather user feedback

### Weekly
- [ ] Review API logs
- [ ] Check performance metrics
- [ ] Update analytics dashboard
- [ ] Plan enhancements

---

**Deployment Checklist Complete!**

For issues or questions, refer to:
- `PUBLIC_EVENTS_SETUP.md` - Detailed setup guide
- `PUBLIC_EVENTS_IMPLEMENTATION.md` - Technical details
- Cloud Run logs - Error diagnosis
