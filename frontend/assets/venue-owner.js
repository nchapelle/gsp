// assets/venue-owner.js
/* global CONFIG, GSP */

(function () {
  const API = CONFIG.API_BASE_URL;

  function getEl(id) {
    return document.getElementById(id);
  }
  function setStatus(elId, type, message) {
    const el = getEl(elId);
    if (el) {
      GSP.status(el, type, message);
    } else {
      console.warn(`Status element with ID '${elId}' not found.`);
    }
  }
  function clearStatus(elId) {
    const el = getEl(elId);
    if (el) {
      el.style.display = 'none';
      el.className = 'status'; // Reset classes
      el.textContent = '';
    }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const params = new URLSearchParams(location.search);
    const slug = params.get('slug');
    const accessKey = params.get('key');

    const venueNameTitle = getEl('venueNameTitle');
    const venueDetailsEl = getEl('venueDetails');
    const eventsListEl = getEl('eventsList');
    const portalStatusElId = 'portalStatus';

    if (!slug || !accessKey) {
      venueNameTitle.textContent = 'Access Denied';
      setStatus(portalStatusElId, 'error', 'Missing venue slug or access key in URL.');
      return;
    }

    try {
      clearStatus(portalStatusElId);
      venueNameTitle.textContent = 'Loading stats for ' + slug + '...';
      eventsListEl.innerHTML = '<li class="item">Fetching event data...</li>';

      const response = await fetch(`${API}/pub/venues/${slug}/stats?key=${accessKey}`);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || `Failed to fetch stats: ${response.statusText}`);
      }
      const data = await response.json();

      venueNameTitle.textContent = `${data.venue_name} Stats`;
      venueDetailsEl.innerHTML = `Weekly: ${data.default_day || 'N/A'} @ ${data.default_time || 'N/A'}`;

      if (data.event_count === 0) {
        eventsListEl.innerHTML = '<li class="item">No validated events found for this venue.</li>';
      } else {
        eventsListEl.innerHTML = data.events.map(event => `
          <li class="item" style="flex-wrap: wrap;">
            <div>
                <strong>${new Date(event.event_date).toLocaleDateString()}</strong> - Host: ${event.host_name}
            </div>
            <div style="margin-top: 5px; width: 100%; display: flex; justify-content: space-between; font-size: 0.9em; color: var(--text-weak);">
                <span>Teams: ${event.num_teams}</span>
                <span>Players: ${event.num_players}</span>
            </div>
          </li>
        `).join('');
      }
      setStatus(portalStatusElId, 'success', 'Stats loaded successfully.');

    } catch (error) {
      venueNameTitle.textContent = 'Error Loading Stats';
      setStatus(portalStatusElId, 'error', error.message || 'An unknown error occurred while loading venue statistics.');
      eventsListEl.innerHTML = '<li class="item">Failed to load events. Please check the URL and access key.</li>';
      console.error("Venue Owner Portal Error:", error);
    }
  });
})();