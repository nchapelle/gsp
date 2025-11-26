Manual verification for 'Recent Photos Zip' modal fix

Steps to validate in your browser:

1. Open `frontend/hosts.html` in your browser (or navigate to the hosted page).
2. Pick a venue from the "Venue" select (the "Recent Photos Zip" button only appears after selecting a venue).
3. Click the "Recent Photos Zip" button.
   - The modal should open immediately and show "Loading zip packs...".
   - If the API returns packs you should see pack rows with a Download button or thumbnails.
   - If no packs are available an error will show in the modal.
   - Clicking individual "Download" should start a file download in-page (no new tab should open). The browser will save a file named like `venue_<id>_photos_part<N>.zip`.
  - If there are more than 4 packs available, only the 4 most recent packs (48 photos) will be shown. The UI no longer supports a single "Download All Visible Packs" action — each pack must be downloaded individually to avoid rate-limit issues.
  - Server-side safeguards: If a requested pack or event archive would make a very large zip, the server will skip files that exceed per-file limits and will stop when a global zip size cap is reached. If no files can be included, the server responds with HTTP 413 and a friendly message. The UI surfaces that error in the modal status.
4. Click the Close button to dismiss the modal.

If the modal still doesn't show anything, open the browser console and check for network or JS errors, and verify the API endpoint `/venues/:id/recent-photos-zip` (no part param) responds with JSON like { packs: [...] }.

Note: The top-right X on the modal was intentionally disabled because it used to submit the hosting form accidentally and alter the page URL. Use the footer "Close" button to dismiss the modal.
