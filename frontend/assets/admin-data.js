/* assets/admin-data.js */
/* global CONFIG, GSP */
(function () {
  const API = CONFIG.API_BASE_URL;

  // ---------- Utilities ----------
  function debounce(fn, ms) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms);
    };
  }
  async function j(u, o) {
    return CONFIG.j(u, o || {});
  }
  function setList(ul, html, emptyText) {
    if (!ul) return;
    ul.innerHTML = html && html.length ? html : `<li class="item">${emptyText || "No results."}</li>`;
  }
  function slugify(s) {
    return (s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  }
  function buildOwnerLink(name, key) {
    if (!name || !key) return "";
    const slug = slugify(name);
    return `https://app.gspevents.com/venue-owner-portal.html?slug=${encodeURIComponent(slug)}&key=${encodeURIComponent(key)}`;
  }
  function copyToClipboard(text) {
    try { navigator.clipboard.writeText(text); }
    catch (_) {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
  }

  // ---------- CSV Helpers (Bulk Upload) ----------
  function splitCSVLine(line) {
    const out = [];
    let cur = "", inQ = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (inQ && line[i + 1] === '"') { cur += '"'; i++; }
        else { inQ = !inQ; }
      } else if (ch === "," && !inQ) {
        out.push(cur); cur = "";
      } else {
        cur += ch;
      }
    }
    out.push(cur);
    return out;
  }
  function csvToEvents(text) {
    const lines = text.split(/\r?\n/).filter(l => l.trim().length);
    if (!lines.length) return [];
    const header = splitCSVLine(lines[0]).map(h => h.trim());
    const idxDate = header.findIndex(h => /^date$/i.test(h));
    const idxHost = header.findIndex(h => /^host$/i.test(h));
    const idxPeople = header.findIndex(h => /people/i.test(h));
    const idxTeams = header.findIndex(h => /teams/i.test(h));
    const idxComments = header.findIndex(h => /comments/i.test(h));

    const rows = [];
    for (let i = 1; i < lines.length; i++) {
      const cols = splitCSVLine(lines[i]).map(s => s.trim());
      if (!cols.length || !cols.some(Boolean)) continue;
      rows.push({
        Date: idxDate >= 0 ? cols[idxDate] : "",
        Host: idxHost >= 0 ? cols[idxHost] : "",
        "# of people": idxPeople >= 0 ? (cols[idxPeople] || "") : "",
        "# of teams": idxTeams >= 0 ? (cols[idxTeams] || "") : "",
        Comments: idxComments >= 0 ? cols[idxComments] : ""
      });
    }
    return rows;
  }

  // ---------- Searches ----------
  async function searchHosts(getEl, q) {
    const ul = getEl("hostsList"); if (!ul) return;
    setList(ul, null, "Searching…");
    try {
      const rows = await j(`${API}/admin/search/hosts?q=${encodeURIComponent(q || "")}&limit=25`);
      if (!rows.length) return setList(ul, null, "No results.");
      const html = rows.map(h => `
        <li class="item" style="display:flex; gap:12px; align-items:center; flex-wrap:wrap;">
          <strong style="color:var(--text-strong);">${h.name}</strong>
          ${h.email ? `<span class="badge">${h.email}</span>` : ""}
          ${h.phone ? `<span class="badge">${h.phone}</span>` : ""}
          <span style="margin-left:auto; display:flex; gap:8px;">
            <button class="btn btn-ghost" data-id="${h.id}" data-act="edit-host">Edit</button>
            <button class="btn btn-ghost" data-id="${h.id}" data-act="del-host">Delete</button>
          </span>
        </li>
      `).join("");
      setList(ul, html);

      ul.querySelectorAll('button[data-act="edit-host"]').forEach(b => {
        b.addEventListener("click", async () => {
          const id = parseInt(b.dataset.id, 10);
          const h = await j(`${API}/admin/hosts/${id}`);
          getEl("hostId").value = h.id;
          getEl("hostName").value = h.name || "";
          getEl("hostPhone").value = h.phone || "";
          getEl("hostEmail").value = h.email || "";
          const st = getEl("hostFormStatus"); if (st) GSP.status(st, "info", `Editing Host ID: ${h.id}`);
        });
      });
      ul.querySelectorAll('button[data-act="del-host"]').forEach(b => {
        b.addEventListener("click", async () => {
          const id = parseInt(b.dataset.id, 10);
          if (!confirm("Delete this host?")) return;
          try {
            await j(`${API}/admin/hosts/${id}`, { method: "DELETE" });
            searchHosts(getEl, getEl("hostSearch").value || "");
          } catch (e) {
            const gs = getEl("globalStatus"); if (gs) GSP.status(gs, "error", e.message);
          }
        });
      });
    } catch (e) {
      const gs = getEl("globalStatus"); if (gs) GSP.status(gs, "error", "Host search failed: " + e.message);
      setList(ul, null, "Error searching.");
    }
  }

  async function searchVenues(getEl, q) {
    const ul = getEl("venuesList"); if (!ul) return;
    setList(ul, null, "Searching…");
    try {
      const rows = await j(`${API}/admin/search/venues?q=${encodeURIComponent(q || "")}&limit=25`);
      if (!rows.length) return setList(ul, null, "No results.");
      const html = rows.map(v => `
        <li class="item" style="display:flex; gap:12px; align-items:center; flex-wrap:wrap;">
          <strong style="color:var(--text-strong);">${v.name}</strong>
          ${v.default_day ? `<span class="badge">${v.default_day}${v.default_time ? " • " + v.default_time : ""}</span>` : ""}
          <span style="margin-left:auto; display:flex; gap:8px;">
            <button class="btn btn-ghost" data-id="${v.id}" data-act="edit-venue">Edit</button>
            <button class="btn btn-ghost" data-id="${v.id}" data-act="del-venue">Delete</button>
            <button
              class="btn btn-ghost copy-owner-link"
              data-id="${v.id}"
              data-name="${v.name}"
              data-key="${v.access_key || ''}"
              title="Copy Owner Portal Link"
            >
              Copy Owner Link
            </button>
          </span>
        </li>
      `).join("");
      setList(ul, html);

      ul.querySelectorAll('button[data-act="edit-venue"]').forEach(b => {
        b.addEventListener("click", async () => {
          const id = parseInt(b.dataset.id, 10);
          const v = await j(`${API}/admin/venues/${id}`);
          getEl("venueId").value = v.id;
          getEl("venueName").value = v.name || "";
          getEl("defaultDay").value = v.default_day || "";
          getEl("defaultTime").value = v.default_time || "";
          getEl("accessKey").value = v.access_key || "";
          const linkInput = getEl("ownerLink");
          if (linkInput) linkInput.value = buildOwnerLink(v.name, v.access_key);
          const st = getEl("venueFormStatus"); if (st) GSP.status(st, "info", `Editing Venue ID: ${v.id}`);
        });
      });

      // NEW quick action: Copy Owner Link
      ul.querySelectorAll('.copy-owner-link').forEach((b) => {
        b.addEventListener('click', () => {
          const name = b.dataset.name || '';
          const key = b.dataset.key || '';
          const st = getEl('venueFormStatus') || getEl('globalStatus');
          if (!name || !key) {
            st && GSP.status(st, 'error', 'Missing venue name or access key for owner link.');
            return;
          }
          const link = buildOwnerLink(name, key);
          copyToClipboard(link);
          st && GSP.status(st, 'success', 'Owner link copied.');
        });
      });

      ul.querySelectorAll('button[data-act="del-venue"]').forEach(b => {
        b.addEventListener("click", async () => {
          const id = parseInt(b.dataset.id, 10);
          if (!confirm("Delete this venue?")) return;
          try {
            await j(`${API}/admin/venues/${id}`, { method: "DELETE" });
            searchVenues(getEl, getEl("venueSearch").value || "");
          } catch (e) {
            const gs = getEl("globalStatus"); if (gs) GSP.status(gs, "error", e.message);
          }
        });
      });
    } catch (e) {
      const gs = getEl("globalStatus"); if (gs) GSP.status(gs, "error", "Venue search failed: " + e.message);
      setList(ul, null, "Error searching.");
    }
  }

  async function searchTeams(getEl, q) {
    const ul = getEl("teamsList"); if (!ul) return;
    setList(ul, null, "Searching…");
    try {
      const rows = await j(`${API}/admin/search/teams?q=${encodeURIComponent(q || "")}&limit=25`);
      if (!rows.length) return setList(ul, null, "No results.");
      const html = rows.map(t => `
        <li class="item" style="display:flex; gap:12px; align-items:center; flex-wrap:wrap;">
          <strong style="color:var(--text-strong);">${t.name}</strong>
          ${t.home_venue ? `<span class="badge">${t.home_venue}</span>` : ""}
          <span style="margin-left:auto; display:flex; gap:8px;">
            <button class="btn btn-ghost" data-id="${t.id}" data-act="edit-team">Edit</button>
            <button class="btn btn-ghost" data-id="${t.id}" data-act="del-team">Delete</button>
          </span>
        </li>
      `).join("");
      setList(ul, html);

      ul.querySelectorAll('button[data-act="edit-team"]').forEach(b => {
        b.addEventListener("click", async () => {
          const id = parseInt(b.dataset.id, 10);
          const t = await j(`${API}/admin/tournament-teams/${id}`);
          getEl("teamId").value = t.id;
          getEl("teamName").value = t.name || "";
          getEl("teamHomeVenue").value = t.home_venue_id || "";
          getEl("captainName").value = t.captain_name || "";
          getEl("captainEmail").value = t.captain_email || "";
          getEl("captainPhone").value = t.captain_phone || "";
          getEl("playerCount").value = t.player_count || "";
          const st = getEl("teamFormStatus"); if (st) GSP.status(st, "info", `Editing Team ID: ${t.id}`);
        });
      });
      ul.querySelectorAll('button[data-act="del-team"]').forEach(b => {
        b.addEventListener("click", async () => {
          const id = parseInt(b.dataset.id, 10);
          if (!confirm("Delete this team?")) return;
          try {
            await j(`${API}/admin/tournament-teams/${id}`, { method: "DELETE" });
            searchTeams(getEl, getEl("teamSearch").value || "");
          } catch (e) {
            const gs = getEl("globalStatus"); if (gs) GSP.status(gs, "error", e.message);
          }
        });
      });
    } catch (e) {
      const gs = getEl("globalStatus"); if (gs) GSP.status(gs, "error", "Team search failed: " + e.message);
      setList(ul, null, "Error searching.");
    }
  }

  // ---------- Forms ----------
  function wireHostForm(getEl) {
    const form = getEl("hostForm"); if (!form) return;
    const st = getEl("hostFormStatus");
    const clr = getEl("clearHostFormBtn");

    if (clr) clr.addEventListener("click", () => {
      form.reset();
      getEl("hostId").value = "";
      st && GSP.clearStatus(st);
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      st && GSP.clearStatus(st);
      const id = getEl("hostId").value || null;
      const name = (getEl("hostName").value || "").trim();
      const phone = (getEl("hostPhone").value || "").trim();
      const email = (getEl("hostEmail").value || "").trim();
      if (!name) return st && GSP.status(st, "error", "Host name is required.");

      try {
        if (id) {
          await j(`${API}/admin/hosts/${id}`, { method: "PUT", body: JSON.stringify({ name, phone, email }) });
          st && GSP.status(st, "success", "Host updated.");
        } else {
          const r = await j(`${API}/admin/hosts`, { method: "POST", body: JSON.stringify({ name, phone, email }) });
          // FIXED: Pass "info" or "success" as the type, and the message as the third argument.
          if (r.status === "exists") {
            st && GSP.status(st, "info", `Host exists. ID: ${r.id}`);
          } else {
            st && GSP.status(st, "success", `Host created. ID: ${r.id}`);
          }
        }
        // Refresh the search list to show the new/updated entry
        searchHosts(getEl, getEl("hostSearch").value || "");
      } catch (err) {
        st && GSP.status(st, "error", err.message || "Save failed.");
      }
    });
  }

  function wireVenueForm(getEl) {
    const form = getEl("venueForm"); if (!form) return;
    const st = getEl("venueFormStatus");
    const clr = getEl("clearVenueFormBtn");
    const gen = getEl("generateAccessKeyBtn");
    const copyBtn = getEl("copyOwnerLinkBtn");

    if (clr) clr.addEventListener("click", () => { form.reset(); getEl("venueId").value = ""; st && GSP.clearStatus(st); });

    if (copyBtn) {
      copyBtn.addEventListener("click", () => {
        const link = getEl("ownerLink")?.value || "";
        if (!link) { st && GSP.status(st, "error", "No owner link to copy."); return; }
        copyToClipboard(link);
        st && GSP.status(st, "success", "Owner link copied.");
      });
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      st && GSP.clearStatus(st);
      const id = getEl("venueId").value || null;
      const name = (getEl("venueName").value || "").trim();
      const default_day = (getEl("defaultDay").value || "").trim();
      const default_time = (getEl("defaultTime").value || "").trim();
      const access_key = (getEl("accessKey").value || "").trim() || null;
      if (!name) return st && GSP.status(st, "error", "Venue name is required.");
      try {
        if (id) {
          await j(`${API}/admin/venues/${id}`, { method: "PUT", body: JSON.stringify({ name, default_day, default_time, access_key }) });
          const linkInput = getEl("ownerLink");
          if (linkInput) linkInput.value = buildOwnerLink(name, access_key);
          st && GSP.status(st, "success", "Venue updated.");
        } else {
          const r = await j(`${API}/admin/venues`, { method: "POST", body: JSON.stringify({ name, default_day, default_time }) });
          getEl("accessKey").value = r.access_key || "";
          const linkInput = getEl("ownerLink");
          if (linkInput) linkInput.value = buildOwnerLink(name, r.access_key);
          st && GSP.status(st, "success", `Venue created. ID: ${r.id} ${r.access_key ? `(Key: ${r.access_key})` : ""}`);
        }
        searchVenues(getEl, getEl("venueSearch").value || "");
      } catch (err) {
        st && GSP.status(st, "error", err.message || "Save failed.");
      }
    });

    if (gen) gen.addEventListener("click", async () => {
      st && GSP.clearStatus(st);
      const id = getEl("venueId").value;
      if (!id) return st && GSP.status(st, "error", "Load a venue first to generate a key.");
      if (!confirm("Generate a new access key for this venue? Old links will stop working.")) return;
      try {
        const r = await j(`${API}/admin/venues/${id}/generate-access-key`, { method: "PUT" });
        getEl("accessKey").value = r.access_key || "";
        const linkInput = getEl("ownerLink");
        if (linkInput) linkInput.value = buildOwnerLink(getEl("venueName").value, r.access_key);
        st && GSP.status(st, "success", `New key: ${r.access_key?.slice(0, 8)}…`);
        searchVenues(getEl, getEl("venueSearch").value || "");
      } catch (e) {
        st && GSP.status(st, "error", e.message || "Failed to generate key.");
      }
    });
  }

  async function loadVenuesForTeamDropdown(getEl) {
    try {
      const venues = await j(`${API}/venues`);
      const sel = getEl("teamHomeVenue");
      if (sel) {
        sel.innerHTML = '<option value="">Select Home Venue (Optional)</option>' +
                        venues.map(v => `<option value="${v.id}">${v.name}</option>`).join("");
      }
    } catch (e) {
      const gs = getEl("globalStatus");
      if (gs) GSP.status(gs, "error", "Failed to load venues for team form.");
    }
  }

  function wireTeamForm(getEl) {
    const form = getEl("teamForm"); if (!form) return;
    const st = getEl("teamFormStatus");
    const clr = getEl("clearTeamFormBtn");
    if (clr) clr.addEventListener("click", () => { form.reset(); getEl("teamId").value = ""; st && GSP.clearStatus(st); });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      st && GSP.clearStatus(st);
      const id = getEl("teamId").value || null;
      const name = (getEl("teamName").value || "").trim();
      const home_venue_id = getEl("teamHomeVenue").value ? parseInt(getEl("teamHomeVenue").value, 10) : null;
      const captain_name = (getEl("captainName").value || "").trim();
      const captain_email = (getEl("captainEmail").value || "").trim();
      const captain_phone = (getEl("captainPhone").value || "").trim();
      const player_count = getEl("playerCount").value ? parseInt(getEl("playerCount").value, 10) : null;
      if (!name) return st && GSP.status(st, "error", "Team name is required.");
      try {
        if (id) {
          await j(`${API}/admin/tournament-teams/${id}`, { method: "PUT", body: JSON.stringify({ name, home_venue_id, captain_name, captain_email, captain_phone, player_count }) });
          st && GSP.status(st, "success", "Team updated.");
        } else {
          await j(`${API}/admin/tournament-teams`, { method: "POST", body: JSON.stringify({ name, home_venue_id, captain_name, captain_email, captain_phone, player_count }) });
          st && GSP.status(st, "success", "Team created.");
        }
        searchTeams(getEl, getEl("teamSearch").value || "");
      } catch (err) {
        st && GSP.status(st, "error", err.message || "Save failed.");
      }
    });
  }

  // ---------- Bulk Upload ----------
  async function loadVenuesForBulkSelect(getEl) {
    const sel = getEl("bulkVenue");
    const stat = getEl("bulkStatus");
    if (!sel) return;
    try {
      const venues = await j(`${API}/venues`);
      sel.innerHTML = venues.map(v => `<option value="${v.id}">${v.name}</option>`).join("");
    } catch (e) {
      stat && GSP.status(stat, "error", "Failed to load venues for bulk upload.");
    }
  }
  function wireBulkUpload(getEl) {
    const stat = getEl("bulkStatus");
    const sel = getEl("bulkVenue");
    const file = getEl("bulkFile");
    const fileNameEl = getEl('bulkFileName');
    const btn = getEl("bulkUploadBtn");
    const tmpl = getEl("bulkTemplateBtn");
    if (!sel || !btn) return;

    if (file) {
      file.addEventListener('change', function () {
        if (!fileNameEl) return;
        if (!this.files || !this.files.length) fileNameEl.textContent = 'No file selected';
        else fileNameEl.textContent = this.files[0].name || '1 file selected';
      });
    }

    if (tmpl) {
      tmpl.addEventListener("click", () => {
        const csv = "Date,Host,# of people,# of teams,Comments\n";
        const blob = new Blob([csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "gsp_bulk_upload_template.csv";
        a.click();
        URL.revokeObjectURL(url);
      });
    }

    btn.addEventListener("click", async () => {
      try {
        stat && GSP.clearStatus(stat);
        const venueId = parseInt(sel.value, 10);
        if (!venueId) throw new Error("Select a venue.");
        if (!file.files || !file.files[0]) throw new Error("Choose a CSV file.");
        const text = await file.files[0].text();
        const events = csvToEvents(text);
        if (!events.length) throw new Error("No valid rows found in CSV.");
        const payload = {
          venue_id: venueId,
          events,
          options: {
            validated: !!getEl("bulkValidated")?.checked,
            posted: !!getEl("bulkPosted")?.checked
          }
        };
        stat && GSP.status(stat, "info", `Uploading ${events.length} rows…`);
        const res = await j(`${API}/admin/bulk-upload-summary-events`, { method: "POST", body: JSON.stringify(payload) });
        const s = res.summary || res;
        const summary = [
          `Attempted: ${s.total_attempted ?? "n/a"}`,
          `Created: ${s.events_created ?? 0}`,
          `Hosts: ${s.hosts_created ?? 0}`,
          `Skipped: ${s.events_skipped_existing ?? 0}`,
          `Errors: ${s.skipped_errors ?? 0}`,
        ].join(" • ");
        if (s.errors && s.errors.length) console.warn("Bulk upload errors:", s.errors);
        stat && GSP.status(stat, "success", `Done. ${summary}`);
        file.value = "";
      } catch (e) {
        stat && GSP.status(stat, "error", e.message || "Bulk upload failed.");
      }
    });
  }

  // ---------- 12-Week Panel Logic (Module-level) ----------
  let activeTeamIdForScores = null;

  function showScoresModal(getEl, teamId, teamName) {
    activeTeamIdForScores = teamId;
    getEl('scoresModalTitle').textContent = `Manage Scores for ${teamName}`;
    GSP.clearStatus(getEl('scoresModalStatus'));
    getEl('weeklyScoresContainer').innerHTML = '<p>Select a venue to load scores.</p>';
    getEl('scoresModal').style.display = 'flex';
  }

  function hideScoresModal(getEl) {
    getEl('scoresModal').style.display = 'none';
  }

  async function loadWeeklyScores(getEl) {
    const venueId = getEl('scoresVenueSelect').value;
    const container = getEl('weeklyScoresContainer');
    const statusEl = getEl('scoresModalStatus');
    if (!venueId) {
        container.innerHTML = '<p>Select a venue to load scores.</p>';
        return;
    }
    container.innerHTML = '<p>Loading scores...</p>';
    try {
        const scores = await j(`${API}/admin/teams/${activeTeamIdForScores}/weekly-scores?venue_id=${venueId}`);
        container.innerHTML = scores.map(week => `
            <div class="row row-2 week-score-row" data-week-ending="${week.week_ending}">
                <div class="form-group">
                    <label>Week of ${new Date(week.week_ending + 'T00:00:00').toLocaleDateString()}</label>
                    <input type="number" class="input weekly-points" placeholder="Points" value="${week.points}" />
                </div>
                <div class="form-group">
                    <label>Player Count</label>
                    <input type="number" class="input weekly-players" placeholder="Players" value="${week.num_players}" />
                </div>
            </div>
        `).join('');
    } catch (e) {
        GSP.status(statusEl, 'error', `Failed to load scores: ${e.message}`);
    }
  }

  async function saveWeeklyScores(getEl) {
    const venueId = getEl('scoresVenueSelect').value;
    const container = getEl('weeklyScoresContainer');
    const statusEl = getEl('scoresModalStatus');
    if (!activeTeamIdForScores || !venueId) return;

    const scoresToSave = Array.from(container.querySelectorAll('.week-score-row')).map(row => ({
        week_ending: row.dataset.weekEnding,
        points: row.querySelector('.weekly-points').value,
        num_players: row.querySelector('.weekly-players').value
    })).filter(s => s.points || s.num_players);

    try {
        GSP.status(statusEl, 'info', 'Saving...');
        await j(`${API}/admin/teams/${activeTeamIdForScores}/weekly-scores`, {
            method: 'PUT',
            body: JSON.stringify({ venue_id: parseInt(venueId), scores: scoresToSave })
        });
        GSP.status(statusEl, 'success', 'Scores saved successfully.');
    } catch (e) {
        GSP.status(statusEl, 'error', `Save failed: ${e.message}`);
    }
  }

  // ---------- Public init (called by main.js) ----------
  window.AdminData = {
    init: function ({ getEl }) {
      // Searches
      const hInput = getEl("hostSearch"), hBtn = getEl("hostSearchBtn");
      const vInput = getEl("venueSearch"), vBtn = getEl("venueSearchBtn");
      const tInput = getEl("teamSearch"), tBtn = getEl("teamSearchBtn");

      if (hInput) {
        const f = debounce(() => searchHosts(getEl, hInput.value.trim()), 250);
        hInput.addEventListener("input", f);
        hInput.addEventListener("keydown", e => { if (e.key === "Enter") searchHosts(getEl, hInput.value.trim()); });
        if (hBtn) hBtn.addEventListener("click", () => searchHosts(getEl, hInput.value.trim()));
      }
      if (vInput) {
        const f = debounce(() => searchVenues(getEl, vInput.value.trim()), 250);
        vInput.addEventListener("input", f);
        vInput.addEventListener("keydown", e => { if (e.key === "Enter") searchVenues(getEl, vInput.value.trim()); });
        if (vBtn) vBtn.addEventListener("click", () => searchVenues(getEl, vInput.value.trim()));
      }
      if (tInput) {
        const f = debounce(() => searchTeams(getEl, tInput.value.trim()), 250);
        tInput.addEventListener("input", f);
        tInput.addEventListener("keydown", e => { if (e.key === "Enter") searchTeams(getEl, tInput.value.trim()); });
        if (tBtn) tBtn.addEventListener("click", () => searchTeams(getEl, tInput.value.trim()));
      }

      // Forms and dropdowns
      wireHostForm(getEl);
      wireVenueForm(getEl);
      wireTeamForm(getEl);
      loadVenuesForTeamDropdown(getEl);

      // Bulk upload (wire then load venues)
      wireBulkUpload(getEl);
      loadVenuesForBulkSelect(getEl);
      
            // --- Wire 12-Week Panel ---
      const manageScoresBtn = getEl('manageScoresBtn');
      const closeScoresModalBtn = getEl('closeScoresModalBtn');
      const scoresModal = getEl('scoresModal');
      const scoresVenueSelect = getEl('scoresVenueSelect');
      const saveScoresModalBtn = getEl('saveScoresModalBtn');

      manageScoresBtn?.addEventListener('click', () => {
        const teamId = getEl('teamId').value;
        const teamName = getEl('teamName').value;
        if (teamId && teamName) {
            showScoresModal(getEl, teamId, teamName);
        }
      });
      closeScoresModalBtn?.addEventListener('click', () => hideScoresModal(getEl));
      scoresModal?.addEventListener('click', (e) => {
        if (e.target === scoresModal) hideScoresModal(getEl);
      });
      scoresVenueSelect?.addEventListener('change', () => loadWeeklyScores(getEl));
      saveScoresModalBtn?.addEventListener('click', () => saveWeeklyScores(getEl));

      // --- Initial Data Loads ---
      async function initialLoad() {
        const teamHomeVenueSelect = getEl('teamHomeVenue');
        const scoresVenueSelectModal = getEl('scoresVenueSelect');
        try {
            const venues = await j(`${API}/venues`);
            const optionsHtml = '<option value="">Select Home Venue (Optional)</option>' + venues.map(v => `<option value="${v.id}">${v.name}</option>`).join('');
            if(teamHomeVenueSelect) teamHomeVenueSelect.innerHTML = optionsHtml;
            if(scoresVenueSelectModal) scoresVenueSelectModal.innerHTML = optionsHtml;
        } catch (e) {
            GSP.status(getEl('globalStatus'), 'error', 'Failed to load venues for dropdowns.');
        }
      }
      initialLoad();
      
      // Show "Manage Scores" button only when a team is loaded for editing
      const teamIdInput = getEl('teamId');
      if (teamIdInput) {
        new MutationObserver(() => {
            if(manageScoresBtn) manageScoresBtn.style.display = teamIdInput.value ? 'inline-flex' : 'none';
        }).observe(teamIdInput, { attributes: true, childList: true, subtree: true });
      }
    }
  };
})();