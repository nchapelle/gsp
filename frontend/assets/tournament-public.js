/* assets/tournament-public.js */
/* global CONFIG */
(function () {
  const API = CONFIG.API_BASE_URL;

  async function j(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }
  function setStatus(id, type, msg) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('success','error');
    el.style.display = 'block';
    el.textContent = msg || '';
    if (type) el.classList.add(type);
  }
  function clearStatus(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('success','error');
    el.style.display = 'none';
    el.textContent = '';
  }
  function slugify(s) { return (s || '').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,''); }

  // ---------- Hub (/tournament/scores) ----------
  async function initHub() {
    const venueSelect = document.getElementById('venueSelect');
    const weekSelect = document.getElementById('weekSelect');
    const venuesGrid = document.getElementById('venuesGrid');
    const viewVenueBtn = document.getElementById('viewVenueBtn');
    const viewWeekBtn = document.getElementById('viewWeekBtn');

    try {
      // venues
      const venues = await j(`${API}/pub/tournament/venues`);
      venueSelect.innerHTML = venues.map(v => `<option value="${v.id}" data-slug="${v.slug}">${v.name}</option>`).join('');
      // weeks
      const weeks = await j(`${API}/pub/tournament/weeks`);
      weekSelect.innerHTML = weeks.map(w => `<option value="${w}">${w}</option>`).join('');

      // cards
      venuesGrid.innerHTML = venues.map(v => `
        <div class="card">
          <h3 class="h2">${v.name}</h3>
          <div class="p">Weekly: ${v.default_day || '—'} ${v.default_time ? ' • ' + v.default_time : ''}</div>
          <a class="btn btn-primary" href="/tournament-venue.html?venue=${v.slug}">Open Venue</a>
        </div>
      `).join('');

      viewVenueBtn.addEventListener('click', () => {
        const opt = venueSelect.options[venueSelect.selectedIndex];
        const slug = opt ? opt.getAttribute('data-slug') : null;
        if (slug) location.href = `/tournament/scores/${slug}`;
      });

      viewWeekBtn.addEventListener('click', () => {
        const opt = venueSelect.options[venueSelect.selectedIndex];
        const slug = opt ? opt.getAttribute('data-slug') : null;
        const date = weekSelect.value;
        if (slug && date) location.href = `/tournament-venue-week.html?venue=${slug}&date=${date}`;
      });
    } catch (err) {
      setStatus('hubStatus', 'error', 'Failed to load venues/weeks');
    }
  }

  // ---------- Venue (/tournament/scores/:venue) ----------
  async function initVenue() {
    const parts = location.pathname.split('/').filter(Boolean); // ["tournament","scores",":venue"]
    if (parts.length < 3) return;
    const slug = parts[2];

    const title = document.getElementById('venueTitle');
    const meta = document.getElementById('venueMeta');
    const weeksList = document.getElementById('weeksList');
    const ctaNext = document.getElementById('ctaNext');
    const ctaShare = document.getElementById('ctaShare');

    try {
      const data = await j(`${API}/pub/tournament/venue/${slug}`);
      const v = data.venue;
      title.textContent = `Trivia at ${v.name}`;
      meta.innerHTML = `Weekly: ${v.default_day || '—'} ${v.default_time ? ' • ' + v.default_time : ''}`;

      // build recent weeks
      weeksList.innerHTML = (data.weeks || []).map(w => `
        <li class="item">
          <span><strong>${w.week_ending}</strong> — ${w.count ? w.count + ' results' : 'No scores'}</span>
          <a class="btn btn-ghost" href="/tournament/scores/${slug}/${w.week_ending}">Open</a>
        </li>
      `).join('');

      // CTA links
      // Add to calendar ICS (next occurrence not computed here; simple placeholder)
      ctaNext.href = `data:text/calendar;charset=utf8,${encodeURIComponent(
        `BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Trivia Night at ${v.name}
DESCRIPTION:GSP Events
DTSTART:20250101T000000Z
DTEND:20250101T020000Z
END:VEVENT
END:VCALENDAR`.replace(/\n/g, "\r\n")
      )}`;

      const shareUrl = `${location.origin}/tournament/scores/${slug}`;
      ctaShare.href = `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(shareUrl)}`;
    } catch (err) {
      setStatus('venueStatus', 'error', 'Venue not found');
    }
  }

  // ---------- Venue Week (/tournament/scores/:venue/:date) ----------
  async function initVenueWeek() {
    const parts = location.pathname.split('/').filter(Boolean); // ["tournament","scores",":venue",":date"]
    if (parts.length < 4) return;
    const slug = parts[2];
    const date = parts[3];

    const title = document.getElementById('weekTitle');
    const meta = document.getElementById('weekMeta');
    const tbody = document.getElementById('scoresTbody');
    const photosGrid = document.getElementById('photosGrid');
    const ctaVenue = document.getElementById('ctaVenue');
    const ctaShareWeek = document.getElementById('ctaShareWeek');

    try {
      const detail = await j(`${API}/pub/tournament/venue/${slug}/${date}`);
      title.textContent = `Weekly Results — ${detail.venue.name}`;
      meta.textContent = `Week ending ${date}`;

      // scores (ordered by API)
      const rows = detail.rows || [];
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="4">No results for this week.</td></tr>';
      } else {
        tbody.innerHTML = rows.map((r, idx) => `
          <tr>
            <td>${idx + 1}</td>
            <td>${r.team_name}</td>
            <td>${r.points != null ? r.points : '—'}</td>
            <td>${r.num_players != null ? r.num_players : '—'}</td>
          </tr>
        `).join('');
      }

      // Optional photo render by querying the regular event endpoint if you want to show recap photos
      // If you maintain a mapping from (venue, date) -> eventId, you can fetch /events/{id} and display photos.
      photosGrid.innerHTML = '';

      // links
      ctaVenue.href = `/tournament/scores/${slug}`;
      const shareUrl = `${location.origin}/tournament/scores/${slug}/${date}`;
      ctaShareWeek.href = `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(shareUrl)}`;
    } catch (err) {
      setStatus('weekStatus', 'error', 'Failed to load weekly results');
    }
  }

  // Router for these public tournament pages
  function boot() {
    const path = location.pathname;
    if (path === "/tournament/scores" || path.endsWith("/tournament-scores.html")) {
      initHub();
    } else if (/^\/tournament\/scores\/[^\/]+\/?$/.test(path)) {
      initVenue();
    } else if (/^\/tournament\/scores\/[^\/]+\/\d{4}-\d{2}-\d{2}\/?$/.test(path)) {
      initVenueWeek();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();