/* assets/tournament-admin.js */
/* global CONFIG */
(function () {
  const API = CONFIG.API_BASE_URL;
  const els = {
    status: null,
    venue: null,
    week: null,
    newWeekBtn: null,
    loadBtn: null,
    teamsGrid: null,
    newTeamName: null,
    addTeamBtn: null,
    saveBtn: null,
  };

  function status(el, type, msg) {
    if (!el) return;
    el.classList.remove("success", "error");
    el.style.display = "block";
    el.textContent = msg || "";
    if (type) el.classList.add(type);
  }
  function clearStatus(el) { if (el){ el.classList.remove('success','error'); el.style.display='none'; el.textContent=''; } }

  async function j(url, opts = {}) {
    const res = await fetch(url, {
      ...opts,
      headers: {
        ...(opts.headers || {}),
        ...(opts.body && typeof opts.body === "string" ? { "Content-Type": "application/json" } : {}),
      },
    });
    if (!res.ok) {
      const t = await res.text().catch(()=> "");
      throw new Error(`${res.status} ${res.statusText}: ${t}`);
    }
    const ct = res.headers.get("Content-Type") || "";
    if (ct.includes("application/json")) return res.json();
    return res.text();
  }

  function rowTpl(r) {
    return `
      <div class="grid-3" style="grid-template-columns: 2fr 120px 120px; gap:10px;">
        <input class="input team-name" placeholder="Team name" value="${r.team_name || ''}" />
        <input class="input team-points" type="number" placeholder="Points" value="${r.points != null ? r.points : ''}" />
        <input class="input team-players" type="number" placeholder="# Players" value="${r.num_players != null ? r.num_players : ''}" />
      </div>
    `;
  }

  async function loadVenues() {
    const venues = await j(`${API}/venues`);
    els.venue.innerHTML = venues.map(v => `<option value="${v.id}">${v.name}</option>`).join('');
  }
  async function loadWeeks() {
    const weeks = await j(`${API}/admin/tournament/weeks`);
    els.week.innerHTML = weeks.map(w => `<option value="${w.week_ending}">${w.week_ending}</option>`).join('');
  }

  async function newWeek() {
    clearStatus(els.status);
    const d = GSP.nowInET();
    // Set to next Sunday
    const dow = d.getDay();
    const delta = (7 - dow) % 7; // next Sunday
    d.setDate(d.getDate() + delta);
    const y = d.getFullYear();
    const m = String(d.getMonth()+1).padStart(2,'0');
    const day = String(d.getDate()).padStart(2,'0');
    const week_ending = `${y}-${m}-${day}`;
    try {
      const out = await j(`${API}/admin/tournament/weeks`, {
        method:'POST',
        body: JSON.stringify({ week_ending })
      });
      status(els.status, 'success', `Week created: ${out.week_ending}`);
      loadWeeks();
    } catch (err) {
      status(els.status, 'error', 'Create week failed: ' + err.message);
    }
  }

  async function loadScores() {
    clearStatus(els.status);
    const vid = els.venue.value;
    const wk = els.week.value;
    if (!vid || !wk) { status(els.status, 'error', 'Select a venue and week'); return; }
    try {
      const out = await j(`${API}/admin/tournament/scores?venue_id=${encodeURIComponent(vid)}&week_ending=${encodeURIComponent(wk)}`);
      const rows = (out.rows || []);
      if (!rows.length) {
        els.teamsGrid.innerHTML = '<p class="p">No scores yet — add teams below.</p>';
      } else {
        els.teamsGrid.innerHTML = rows.map(rowTpl).join('');
      }
    } catch (err) {
      status(els.status, 'error', 'Load failed: ' + err.message);
    }
  }

  function addTeamRow(name) {
    els.teamsGrid.insertAdjacentHTML('beforeend', rowTpl({ team_name: name || '' }));
  }

  async function saveScores() {
    clearStatus(els.status);
    const vid = parseInt(els.venue.value, 10);
    const wk = els.week.value;
    if (!vid || !wk) { status(els.status, 'error', 'Select a venue and week'); return; }

    const rows = Array.from(els.teamsGrid.querySelectorAll('.grid-3')).map(div => ({
      team_name: div.querySelector('.team-name').value.trim(),
      points: div.querySelector('.team-points').value === '' ? null : parseInt(div.querySelector('.team-points').value, 10),
      num_players: div.querySelector('.team-players').value === '' ? null : parseInt(div.querySelector('.team-players').value, 10),
    })).filter(r => r.team_name);

    try {
      await j(`${API}/admin/tournament/scores`, {
        method: 'PUT',
        body: JSON.stringify({ venue_id: vid, week_ending: wk, rows }),
      });
      status(els.status, 'success', 'Scores saved.');
    } catch (err) {
      status(els.status, 'error', 'Save failed: ' + err.message);
    }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    els.status = document.getElementById('taStatus');
    els.venue = document.getElementById('venueSelect');
    els.week = document.getElementById('weekSelect');
    els.newWeekBtn = document.getElementById('newWeekBtn');
    els.loadBtn = document.getElementById('loadBtn');
    els.teamsGrid = document.getElementById('teamsGrid');
    els.newTeamName = document.getElementById('newTeamName');
    els.addTeamBtn = document.getElementById('addTeamBtn');
    els.saveBtn = document.getElementById('saveBtn');

    await loadVenues();
    await loadWeeks();

    els.newWeekBtn.addEventListener('click', newWeek);
    els.loadBtn.addEventListener('click', loadScores);
    els.addTeamBtn.addEventListener('click', () => addTeamRow(els.newTeamName.value.trim()));
    els.saveBtn.addEventListener('click', saveScores);
  });
})();