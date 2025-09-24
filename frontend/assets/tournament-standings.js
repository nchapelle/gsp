/* assets/tournament-standings.js */
/* global CONFIG, GSP */
(function () {
  const API = CONFIG.API_BASE_URL;

  async function loadVenues(getEl) {
    const selectEl = getEl('venueSelect');
    const statusEl = getEl('standingsStatus');
    try {
      const venues = await GSP.j(`${API}/venues`);
      selectEl.innerHTML = '<option value="">-- Select a Venue --</option>' + 
        venues.map(v => `<option value="${v.id}">${v.name}</option>`).join('');
    } catch (e) {
      GSP.status(statusEl, 'error', 'Failed to load venues.');
    }
  }

  async function loadStandings(getEl, venueId, venueName) {
    const tbodyEl = getEl('standingsTbody');
    const statusEl = getEl('standingsStatus');
    const titleEl = getEl('standingsTitle');
    
    GSP.clearStatus(statusEl);
    titleEl.textContent = `Loading standings for ${venueName}...`;
    tbodyEl.innerHTML = '<tr><td colspan="3">Loading...</td></tr>';
    try {
      const standings = await GSP.j(`${API}/pub/tournament-standings?venue_id=${venueId}`);
      if (!standings.length) {
        tbodyEl.innerHTML = '<tr><td colspan="3">No tournament points recorded for this venue yet.</td></tr>';
        return;
      }
      tbodyEl.innerHTML = standings.map((s, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>${s.team_name}</td>
          <td>${s.total_points}</td>
        </tr>
      `).join('');
      titleEl.textContent = `Standings for ${venueName}`;
    } catch (e) {
      GSP.status(statusEl, 'error', `Failed to load standings: ${e.message}`);
      tbodyEl.innerHTML = '<tr><td colspan="3">Could not load standings.</td></tr>';
    }
  }
  
  // EXPOSED INIT FUNCTION (Called by main.js)
  window.TournamentStandings = {
    init: function({ getEl }) {
      const venueSelect = getEl('venueSelect');
      
      if (venueSelect) {
        loadVenues(getEl);
        venueSelect.addEventListener('change', () => {
          const venueId = venueSelect.value;
          const standingsTbody = getEl('standingsTbody');
          const standingsTitle = getEl('standingsTitle');
          if (venueId) {
            const venueName = venueSelect.options[venueSelect.selectedIndex].text;
            loadStandings(getEl, venueId, venueName);
          } else {
            standingsTbody.innerHTML = '<tr><td colspan="3">Select a venue above.</td></tr>';
            standingsTitle.textContent = 'Select a venue to view standings';
          }
        });
      }
    }
  };
})();