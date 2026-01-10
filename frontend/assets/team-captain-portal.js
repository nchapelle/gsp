/* assets/team-captain-portal.js */
/* global CONFIG, GSP */
(function () {
  const API = CONFIG.API_BASE_URL;

  function renderWeeklySummary(summary, containerEl) {
    if (!summary.length) {
      containerEl.innerHTML = '<div class="card"><p>No weekly points have been recorded for your team yet.</p></div>';
      return;
    }
    
    containerEl.innerHTML = summary.map(week => `
      <div class="card" style="margin-bottom: var(--space-4);">
        <h2 class="h2">Week Ending: ${GSP.formatDateET(week.week_ending)}</h2>
        <p class="p"><strong>Total Points This Week: ${week.weekly_points}</strong></p>
        <table class="admin-table">
          <thead>
            <tr>
              <th>Venue Played</th>
              <th>Points Gained</th>
            </tr>
          </thead>
          <tbody>
            ${week.events.map(e => `
              <tr>
                <td>${e.venue}</td>
                <td>${e.points}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `).join('');
  }

  // This module can also self-initialize
  document.addEventListener("DOMContentLoaded", async () => {
    const titleEl = document.getElementById('teamNameTitle');
    const statusEl = document.getElementById('portalStatus');
    const containerEl = document.getElementById('statsContainer');
    
    const params = new URLSearchParams(location.search);
    const teamId = params.get('id');
    const key = params.get('key');

    if (!teamId || !key) {
      GSP.status(statusEl, 'error', 'Team ID or Access Key missing from URL.');
      titleEl.textContent = 'Access Denied';
      return;
    }

    try {
      const data = await GSP.j(`${API}/pub/teams/${teamId}/stats?key=${key}`);
      titleEl.textContent = `${data.team_name} - Weekly Stats`;
      renderWeeklySummary(data.weekly_summary || [], containerEl);
    } catch (e) {
      GSP.status(statusEl, 'error', `Could not load team stats. Please check the link. Error: ${e.message}`);
      titleEl.textContent = 'Error';
    }
  });
})();