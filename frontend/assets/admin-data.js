/* assets/admin-data.js */
/* global CONFIG, GSP, GSPAuth */
(function () {
  const API = CONFIG.API_BASE_URL;
  let hostsCache = [];

  // Initialize authentication - require admin role only
  if (typeof GSPAuth !== 'undefined') {
    GSPAuth.init({
      requiredRoles: ['admin'],
      requireAuth: true,
      onAuthReady: function(user) {
        if (user) {
          console.log('[admin-data] Auth ready, user:', user.email, 'role:', user.role);
          // Page will auto-initialize via DOMContentLoaded
        }
      }
    });
  } else {
    console.error('[admin-data] GSPAuth not loaded');
  }

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
      
      const html = rows.map(v => {
        // Visual logic for inactive venues
        const opacity = v.is_active ? '1' : '0.5';
        const badge = v.is_active 
          ? '' 
          : '<span class="badge" style="background:#444; color:#aaa; border-color:#666;">Inactive</span>';
        
        return `
        <li class="item" style="display:flex; gap:12px; align-items:center; flex-wrap:wrap; opacity: ${opacity}">
          <div style="flex:1">
            <strong style="color:var(--text-strong);">${v.name}</strong>
            ${v.default_day ? `<span class="badge">${v.default_day}${v.default_time ? " • " + v.default_time : ""}</span>` : ""}
            ${badge}
          </div>
          <span style="margin-left:auto; display:flex; gap:8px;">
            <button class="btn btn-ghost" data-id="${v.id}" data-act="edit-venue">Edit</button>
            
            <button class="btn btn-ghost" data-id="${v.id}" data-act="toggle-active">
                ${v.is_active ? 'Deactivate' : 'Activate'}
            </button>
            
            <button class="btn btn-ghost" data-id="${v.id}" data-act="del-venue">Del</button>
          </span>
        </li>
      `}).join("");
      
      setList(ul, html);

      // Wire Edit Button
      ul.querySelectorAll('button[data-act="edit-venue"]').forEach(b => {
        b.addEventListener("click", async () => {
          // We can use the row data directly from 'rows' array to avoid another fetch if we want, 
          // but fetching fresh ensures we have the latest.
          const id = parseInt(b.dataset.id, 10);
          // Just reuse the row data we already fetched to populate form quickly
          const v = rows.find(r => r.id === id); 
          
          getEl("venueId").value = v.id;
          getEl("venueName").value = v.name || "";
          getEl("defaultDay").value = v.default_day || "";
          getEl("defaultTime").value = v.default_time || "";
          // Default host (new)
          try { if (getEl("venueDefaultHost")) getEl("venueDefaultHost").value = v.default_host_id || ""; } catch (e) {}
          getEl("accessKey").value = v.access_key || "";
          
          // Set checkbox
          const chk = getEl("venueIsActive");
          if(chk) chk.checked = (v.is_active !== false); // default true

          const linkInput = getEl("ownerLink");
          if (linkInput) linkInput.value = buildOwnerLink(v.name, v.access_key);
          const st = getEl("venueFormStatus"); if (st) GSP.status(st, "info", `Editing Venue ID: ${v.id}`);
        });
      });

      // Wire Toggle Active Button
      ul.querySelectorAll('button[data-act="toggle-active"]').forEach(b => {
        b.addEventListener("click", async () => {
             const id = parseInt(b.dataset.id, 10);
             const v = rows.find(r => r.id === id);
             const newState = !v.is_active;
             
             if (!confirm(`Mark ${v.name} as ${newState ? 'Active' : 'Inactive'}?`)) return;

             try {
                // Reuse the PUT endpoint
                await j(`${API}/admin/venues/${id}`, { 
                    method: "PUT", 
                    body: JSON.stringify({ 
                        name: v.name, // Name is required by backend validation
                        is_active: newState 
                    }) 
                });
                searchVenues(getEl, getEl("venueSearch").value || "");
             } catch(e) {
                 const gs = getEl("globalStatus"); if (gs) GSP.status(gs, "error", e.message);
             }
        });
      });

      // ... existing copy-link and delete wiring ...
      ul.querySelectorAll('.copy-owner-link').forEach((b) => { /* ... */ });
      ul.querySelectorAll('button[data-act="del-venue"]').forEach(b => { /* ... */ });

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
    
    // Clear also resets checkbox
    if (clr) clr.addEventListener("click", () => { 
        form.reset(); 
        getEl("venueId").value = ""; 
        const chk = getEl("venueIsActive"); if(chk) chk.checked = true;
        st && GSP.clearStatus(st); 
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      st && GSP.clearStatus(st);
      const id = getEl("venueId").value || null;
      const name = (getEl("venueName").value || "").trim();
      const default_day = (getEl("defaultDay").value || "").trim();
      const default_time = (getEl("defaultTime").value || "").trim();
      const default_host_id = getEl("venueDefaultHost")?.value ? parseInt(getEl("venueDefaultHost").value, 10) : null;
      const access_key = (getEl("accessKey").value || "").trim() || null;
      
      // Get Checkbox value
      const is_active = !!getEl("venueIsActive").checked;

      if (!name) return st && GSP.status(st, "error", "Venue name is required.");
      try {
        if (id) {
          await j(`${API}/admin/venues/${id}`, { 
              method: "PUT", 
              body: JSON.stringify({ name, default_day, default_time, access_key, is_active, default_host_id }) 
          });
          // ... update links ...
          st && GSP.status(st, "success", "Venue updated.");
        } else {
          // For Create, backend defaults is_active=True, but we can send it explicitly
          const r = await j(`${API}/admin/venues`, { 
              method: "POST", 
              body: JSON.stringify({ name, default_day, default_time, is_active, default_host_id }) 
          });
          // ... update links ...
          st && GSP.status(st, "success", `Venue created. ID: ${r.id}`);
        }
        searchVenues(getEl, getEl("venueSearch").value || "");
      } catch (err) {
        st && GSP.status(st, "error", err.message || "Save failed.");
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

  // ---------- Hosts Loading ----------
  async function loadHosts(getEl) {
    try {
      const hosts = await j(`${API}/hosts`);
      hostsCache = hosts || [];
      // Populate venue default host select if present
      const vsel = getEl('venueDefaultHost');
      if (vsel) {
        const opts = ['<option value="">(no default host)</option>'].concat(
          hostsCache.map(h => `<option value="${h.id}">${h.name}${h.email ? ` • ${h.email}` : ''}</option>`)
        );
        vsel.innerHTML = opts.join('');
      }
      // Update any schedule builder host selects that may exist
      document.querySelectorAll('.schedule-host-select').forEach(s => {
        const cur = s.value || '';
        s.innerHTML = '<option value="">(no default host)</option>' + hostsCache.map(h => `<option value="${h.id}">${h.name}${h.email ? ` • ${h.email}` : ''}</option>`).join('');
        if (cur) s.value = cur;
      });
    } catch (e) {
      GSP.status(getEl('globalStatus'), 'error', 'Failed to load hosts.');
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

// ---------- Weekly Report ----------
  async function loadWeeklyReport(getEl, weekEnding) {
    const container = getEl('weeklyReportContainer');
    const statusEl = getEl('globalStatus');
    
    try {
      container.innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-weak);">Loading report data...</div>';
      
      const qs = weekEnding ? `?week_ending=${encodeURIComponent(weekEnding)}` : '';
      const payload = await j(`${API}/admin/weekly-report${qs}`);

      // Calculate totals
      const totals = { total: 0, no_submission: 0, unvalidated: 0, validated: 0, posted: 0 };
      (payload.rows || []).forEach(r => { 
          totals.total += 1; 
          totals[r.state] = (totals[r.state] || 0) + 1; 
      });

      // Sort rows by default_day (Mon->Sun) then by venue name
      const dayOrder = { 'Monday':1,'Tuesday':2,'Wednesday':3,'Thursday':4,'Friday':5,'Saturday':6,'Sunday':7 };
      payload.rows = (payload.rows || []).slice().sort((a,b) => {
        const ra = dayOrder[a.default_day] || 99;
        const rb = dayOrder[b.default_day] || 99;
        if (ra !== rb) return ra - rb;
        return (a.venue || '').toLowerCase().localeCompare((b.venue || '').toLowerCase());
      });

      // 1. Build The Stat Cards (Dashboard)
      const statsHtml = `
        <div class="stats-grid">
            <div class="stat-card">
                <div class="num">${totals.total}</div>
                <div class="label">Total Venues</div>
            </div>
            <div class="stat-card posted">
                <div class="num">${totals.posted}</div>
                <div class="label">Posted</div>
            </div>
            <div class="stat-card validated">
                <div class="num">${totals.validated}</div>
                <div class="label">Validated</div>
            </div>
            <div class="stat-card unvalidated">
                <div class="num">${totals.unvalidated}</div>
                <div class="label">Pending</div>
            </div>
            <div class="stat-card missing">
                <div class="num">${totals.no_submission}</div>
                <div class="label">No Submission</div>
            </div>
        </div>
      `;

      // 2. Build Date Range Header
      const metaHtml = `
        <div class="report-meta">
            <span><strong>Report Range:</strong> ${payload.week_start} <span style="color:var(--text-weak); margin:0 6px;">to</span> ${payload.week_end}</span>
            <span>${totals.total} Active Venues Tracked</span>
        </div>
      `;

      // 3. Build Table Rows
      const rowsHtml = (payload.rows || []).map(v => {
        // If no events, row is "missing"
        if (!v.events || v.events.length === 0) {
          return `<tr>
                   <td style="font-weight:600; color:var(--text-strong);">${escapeHtml(v.venue)}</td>
                   <td style="color:var(--text-weak);">—</td>
                   <td><span class="badge unposted">none</span></td>
                   <td><span class="badge">No</span></td>
                   <td><span class="badge" style="background:var(--error-red-bg); color:#ff8884; border-color:var(--error-red);">No Submission</span></td>
                 </tr>`;
        }
        // If events exist, map them
        return v.events.map((ev, idx) => {
          // Visual tweaks for badges
          const isPosted = ev.status === 'posted';
          const isValid = ev.is_validated;
          const statusBadge = isPosted 
            ? `<span class="badge posted">Posted</span>` 
            : `<span class="badge unposted">${ev.status || 'draft'}</span>`;
            
          const validBadge = isValid 
            ? `<span class="badge success">Yes</span>` 
            : `<span class="badge">No</span>`;

          // Venue State Badge logic
          let stateBadge = '';
          if (v.state === 'posted') stateBadge = `<span class="badge posted">Posted</span>`;
          else if (v.state === 'validated') stateBadge = `<span class="badge" style="color:var(--gsp-blue); border-color:var(--gsp-blue); background:rgba(57,160,237,0.12);">Validated</span>`;
          else if (v.state === 'unvalidated') stateBadge = `<span class="badge unposted">Pending</span>`;
          
          // Only show venue name on first row if multiple events (optional, but cleaner)
          const venueName = idx === 0 ? `<strong style="color:var(--text-strong);">${escapeHtml(v.venue)}</strong>` : '';

          return `<tr>
                   <td>${venueName}</td>
                   <td>${ev.event_date || ''}</td>
                   <td>${statusBadge}</td>
                   <td>${validBadge}</td>
                   <td>${stateBadge}</td>
                 </tr>`;
        }).join('');
      }).join('');

      // Combine all parts
      container.innerHTML = `
        ${statsHtml}
        ${metaHtml}
        <div style="overflow-x:auto; border-radius:var(--radius); border:1px solid var(--border);">
            <table class="admin-table" style="min-width:700px; margin-top:0;">
                <thead style="background:var(--panel-2);">
                    <tr>
                        <th style="padding:12px 10px;">Venue</th>
                        <th style="padding:12px 10px;">Event Date</th>
                        <th style="padding:12px 10px;">Status</th>
                        <th style="padding:12px 10px;">Validated</th>
                        <th style="padding:12px 10px;">Overall State</th>
                    </tr>
                </thead>
                <tbody>${rowsHtml}</tbody>
            </table>
        </div>
      `;

    } catch (e) {
      container.innerHTML = '';
      statusEl && GSP.status(statusEl, 'error', `Failed to load weekly report: ${e.message || e}`);
    }
  }

  function escapeHtml(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  async function exportWeeklyReport(getEl) {
    const dateVal = getEl('reportWeekEnding')?.value || '';
    try {
      const qs = dateVal ? `?week_ending=${encodeURIComponent(dateVal)}` : '';
      const payload = await j(`${API}/admin/weekly-report${qs}`);
      const rows = payload.rows || [];
      const hdr = ['venue_id','venue','event_id','event_date','status','is_validated','state'];
      const csvRows = [hdr.join(',')];
      rows.forEach(r => {
        if (!r.events || r.events.length === 0) {
          csvRows.push([r.venue_id, `"${(r.venue||'').replace(/"/g,'""')}"`, '', '', '', '', r.state].join(','));
        } else {
          r.events.forEach(ev => {
            csvRows.push([r.venue_id, `"${(r.venue||'').replace(/"/g,'""')}"`, ev.event_id || '', ev.event_date || '', ev.status || '', ev.is_validated || '', r.state].join(','));
          });
        }
      });
      const csv = csvRows.join('\n');
      const blob = new Blob([csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `weekly_report_${payload.week_start}_to_${payload.week_end}.csv`; a.click(); URL.revokeObjectURL(url);
    } catch (e) {
      const gs = getEl('globalStatus'); if (gs) GSP.status(gs, 'error', `Export failed: ${e.message || e}`);
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

  // ---------- Weekly Schedule Builder ----------
  function buildDayOptions(selected) {
    const days = ['', 'Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
    return days.map(d => `<option value="${d}" ${d===selected? 'selected':''}>${d?d:'—'}</option>`).join('');
  }

  async function renderScheduleBuilder(getEl) {
    const container = getEl('scheduleBuilderContainer');
    const gs = getEl('globalStatus');
    if (!container) return;
    try {
      container.innerHTML = '<div style="padding:16px; color:var(--text-weak);">Loading active venues…</div>';
      // Ensure hosts are loaded
      if (!hostsCache || !hostsCache.length) await loadHosts(getEl);
      const venues = await j(`${API}/venues`);
      const active = (venues || []).filter(v => v.is_active !== false);
      // Sort by day (Mon->Sun) then by name
      const dayOrder = { 'Monday':1,'Tuesday':2,'Wednesday':3,'Thursday':4,'Friday':5,'Saturday':6,'Sunday':7 };
      active.sort((a,b) => {
        const da = (a.default_day || '');
        const db = (b.default_day || '');
        const ra = dayOrder[da] || 99;
        const rb = dayOrder[db] || 99;
        if (ra !== rb) return ra - rb;
        return (a.name || '').toLowerCase().localeCompare((b.name || '').toLowerCase());
      });
      if (!active.length) {
        container.innerHTML = '<div style="padding:12px; color:var(--text-weak);">No active venues found.</div>';
        return;
      }

      const rows = active.map(v => {
        const hostOptions = ['<option value="">(no default host)</option>'].concat(hostsCache.map(h => `<option value="${h.id}" ${String(v.default_host_id)===String(h.id)? 'selected':''}>${h.name}${h.email? ' • ' + h.email : ''}</option>`)).join('');
        const showTypeVal = v.show_type || 'gsp';
        return `
          <div class="schedule-row" data-id="${v.id}" data-name="${escapeHtml(v.name)}" data-show-type="${showTypeVal}" data-original-day="${v.default_day||''}" data-original-time="${v.default_time||''}" data-original-host="${v.default_host_id||''}" data-original-cancelled="false" data-original-cancel-reason="" data-is-active="${v.is_active!==false}" data-cancelled="false" data-cancel-reason="">
            <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
              <div style="flex:1; font-weight:600;">${escapeHtml(v.name)} <span class="badge cancel-badge" style="display:none; background:var(--error-red-bg); color:var(--error-red); border-color:var(--error-red); margin-left:8px;">CANCELED</span></div>
              <div style="width:140px;">
                <select class="input schedule-day-select">${buildDayOptions(v.default_day||'')}</select>
              </div>
              <div style="width:140px;"><input class="input schedule-time-input" value="${v.default_time||''}" placeholder="e.g., 7-9pm" /></div>
              <div style="width:240px;"><select class="input schedule-host-select">${hostOptions}</select></div>
              <div style="width:120px; display:flex; gap:8px;">
                <button class="btn btn-ghost btn-cancel-row">Cancel</button>
                <button class="btn btn-ghost btn-clear-cancel" style="display:none;">Clear</button>
              </div>
            </div>
          </div>
        `;
      }).join('');

      container.innerHTML = rows;
      // Wire cancel buttons for each row
      container.querySelectorAll('.schedule-row').forEach(row => {
        const cancelBtn = row.querySelector('.btn-cancel-row');
        const clearBtn = row.querySelector('.btn-clear-cancel');
        const badge = row.querySelector('.cancel-badge');
        const setCancelledUI = (reason) => {
          row.dataset.cancelled = reason ? 'true' : 'false';
          row.dataset.cancelReason = reason || '';
          if (reason) {
            if (badge) badge.style.display = 'inline-block';
            if (clearBtn) clearBtn.style.display = 'inline-flex';
            if (cancelBtn) cancelBtn.textContent = 'Edit';
          } else {
            if (badge) badge.style.display = 'none';
            if (clearBtn) clearBtn.style.display = 'none';
            if (cancelBtn) cancelBtn.textContent = 'Cancel';
          }
        };

        cancelBtn?.addEventListener('click', (e) => {
          e.preventDefault();
          // open modal and edit reason
          const modal = document.getElementById('cancelReasonModal');
          const title = document.getElementById('cancelModalTitle');
          const txt = document.getElementById('cancelReasonText');
          modal.style.display = 'flex';
          title.textContent = `Cancel: ${row.dataset.name}`;
          txt.value = row.dataset.cancelReason || '';
          // Attach row reference to modal save button
          modal.dataset.targetRowId = row.dataset.id;
          modal.dataset.targetRowName = row.dataset.name;
        });

        clearBtn?.addEventListener('click', (e) => {
          e.preventDefault();
          setCancelledUI('');
        });
      });

      // Modal wiring (single instance)
      const cancelModal = document.getElementById('cancelReasonModal');
      const closeCancelModalBtn = document.getElementById('closeCancelModalBtn');
      const saveCancelReasonBtn = document.getElementById('saveCancelReasonBtn');
      const clearCancelReasonBtn = document.getElementById('clearCancelReasonBtn');
      const cancelReasonText = document.getElementById('cancelReasonText');

      closeCancelModalBtn?.addEventListener('click', () => { if (cancelModal) cancelModal.style.display = 'none'; });
      cancelModal?.addEventListener('click', (e) => { if (e.target === cancelModal) cancelModal.style.display = 'none'; });

      saveCancelReasonBtn?.addEventListener('click', () => {
        const id = cancelModal?.dataset?.targetRowId;
        const reason = (cancelReasonText?.value || '').trim();
        if (!id) { if (cancelModal) cancelModal.style.display = 'none'; return; }
        // find the row with matching data-id
        const row = container.querySelector(`.schedule-row[data-id="${id}"]`);
        if (row) {
          row.dataset.cancelled = reason ? 'true' : 'false';
          row.dataset.cancelReason = reason || '';
          const badge = row.querySelector('.cancel-badge');
          const clearBtn = row.querySelector('.btn-clear-cancel');
          const cancelBtn = row.querySelector('.btn-cancel-row');
          if (reason) {
            if (badge) badge.style.display = 'inline-block';
            if (clearBtn) clearBtn.style.display = 'inline-flex';
            if (cancelBtn) cancelBtn.textContent = 'Edit';
          } else {
            if (badge) badge.style.display = 'none';
            if (clearBtn) clearBtn.style.display = 'none';
            if (cancelBtn) cancelBtn.textContent = 'Cancel';
          }
        }
        if (cancelModal) cancelModal.style.display = 'none';
      });

      clearCancelReasonBtn?.addEventListener('click', () => {
        cancelReasonText.value = '';
      });
    } catch (e) {
      container.innerHTML = '';
      gs && GSP.status(gs, 'error', `Schedule load failed: ${e.message || e}`);
    }
  }

    function generateScheduleText(getEl) {
    const container = getEl('scheduleBuilderContainer');
    if (!container) return;
    // Compute this week's Monday (start) and Saturday (end)
    const today = new Date();
    const dow = today.getDay(); // Sun=0..Sat=6
    // compute Monday of current week: if today is Sunday (0), go back 6 days to Monday
    const daysBackToMonday = (dow === 0) ? 6 : (dow - 1);
    const monday = new Date(today);
    monday.setDate(today.getDate() - daysBackToMonday);
    const saturday = new Date(monday);
    saturday.setDate(monday.getDate() + 5);

    function fmtDate(d) {
      const mm = d.getMonth() + 1;
      const dd = d.getDate();
      const yy = String(d.getFullYear()).slice(-2);
      return `${mm}.${dd}.${yy}`;
    }

    const header = [];
    header.push('***WEEKLY SCHEDULE***');
    header.push(`This week's schedule (Monday ${fmtDate(monday)} through Saturday ${fmtDate(saturday)}) and your free "Mystery Bonus Question".`);
    header.push('***Reply to this post with the correct answer to the "Big Bonus" question by 12pm this Friday and you will be entered into a drawing for a GSP T-Shirt!');
    header.push('-----------------------------------------------------');

    const dayOrder = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
    const groups = {};
    dayOrder.forEach(d => groups[d] = []);

    container.querySelectorAll('.schedule-row').forEach(row => {
      const name = row.dataset.name || '';
      const daySelect = row.querySelector('.schedule-day-select');
      let day = daySelect?.value || '';
      const time = row.querySelector('.schedule-time-input')?.value || '';
      const showType = row.dataset.showType || 'gsp';
      const hostId = row.querySelector('.schedule-host-select')?.value || '';
      const host = hostsCache.find(h => String(h.id) === String(hostId));
      const hostText = host ? ` w/ ${host.name}` : '';
      
      // Debug logging
      console.log('Processing venue:', name, 'day:', day, 'time:', time, 'host:', hostText, 'showType:', showType);
      
      // Check for cancellation
      const isCancelled = row.dataset.cancelled === 'true';
      const cancelReason = row.dataset.cancelReason || '';
      
      let timeText = '';
      if (isCancelled) {
        timeText = cancelReason ? ` ***CANCELED ${cancelReason}***` : ' ***CANCELED***';
      } else {
        timeText = time ? ` (${time})` : '';
      }
      
      const line = { name, hostText, timeText, showType };
      // Add to day group - if no day selected, skip this venue
      if (day && groups[day]) {
        console.log('Adding to', day, ':', line);
        groups[day].push(line);
      } else {
        console.log('Skipping venue (no valid day):', name, 'day value was:', day);
      }
    });

    const out = header.slice();
    // For Monday->Saturday only
    for (let i = 0; i < 6; i++) {
      const dayName = dayOrder[i];
      const d = new Date(monday);
      d.setDate(monday.getDate() + i);
      out.push('');
      out.push(`${dayName.toUpperCase()} ${fmtDate(d)}:`);
      
      const rows = groups[dayName] || [];
      console.log(`Day ${dayName} has ${rows.length} venues:`, rows);
      if (rows.length === 0) {
        out.push('- No scheduled venues');
      } else {
        // Group by show_type (case-insensitive comparison)
        const gspRows = rows.filter(r => (r.showType || '').toLowerCase() === 'gsp').sort((a,b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
        const musingoRows = rows.filter(r => (r.showType || '').toLowerCase() === 'musingo').sort((a,b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
        const privateRows = rows.filter(r => (r.showType || '').toLowerCase() === 'private').sort((a,b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
        
        console.log(`GSP: ${gspRows.length}, Musingo: ${musingoRows.length}, Private: ${privateRows.length}`);
        
        if (gspRows.length) {
          out.push('GAME SHOW PALOOZA');
          gspRows.forEach(r => out.push(`- ${r.name}${r.hostText}${r.timeText}`));
        }
        if (musingoRows.length) {
          out.push('MUSINGO');
          musingoRows.forEach(r => out.push(`- ${r.name}${r.hostText}${r.timeText}`));
        }
        if (privateRows.length) {
          out.push('PRIVATE');
          privateRows.forEach(r => out.push(`- ${r.name}${r.hostText}${r.timeText}`));
        }
      }
    }

    out.push('-----------------------------------------------------');
    out.push('********BONUS QUESTION*******');

    getEl('scheduleBuilderOutput').value = out.join('\n');
  }

  async function saveHostChanges(getEl) {
    const container = getEl('scheduleBuilderContainer');
    const gs = getEl('globalStatus');
    if (!container) return;
    
    const rows = Array.from(container.querySelectorAll('.schedule-row'));
    const toSave = [];
    
    rows.forEach(row => {
      const id = row.dataset.id;
      const name = row.dataset.name;
      const origHost = row.dataset.originalHost || '';
      const hostId = row.querySelector('.schedule-host-select')?.value || '';
      
      // Only save if host changed
      if (String(hostId) !== String(origHost)) {
        toSave.push({ 
          id, 
          name,
          default_host_id: hostId ? parseInt(hostId, 10) : null
        });
      }
    });

    if (!toSave.length) { 
      GSP.status(gs, 'info', 'No host changes to save.'); 
      return; 
    }
    
    try {
      GSP.status(gs, 'info', `Saving ${toSave.length} host changes…`);
      await Promise.all(toSave.map(v => j(`${API}/admin/venues/${v.id}`, { 
        method: 'PUT', 
        body: JSON.stringify({ 
          name: v.name,
          default_host_id: v.default_host_id
        }) 
      })));
      GSP.status(gs, 'success', `Updated default host for ${toSave.length} venue(s).`);
      // Reload to refresh originals
      await renderScheduleBuilder(getEl);
    } catch (e) {
      GSP.status(gs, 'error', `Save failed: ${e.message || e}`);
    }
  }

   async function saveScheduleChanges(getEl) {
    const container = getEl('scheduleBuilderContainer');
    const gs = getEl('globalStatus');
    if (!container) return;
    const rows = Array.from(container.querySelectorAll('.schedule-row'));
    const toSave = [];
    rows.forEach(row => {
      const id = row.dataset.id;
      const name = row.dataset.name;
      const origDay = row.dataset.originalDay || row.dataset.originalDay === '' ? row.dataset.originalDay : row.getAttribute('data-original-day');
      const origTime = row.dataset.originalTime || row.getAttribute('data-original-time');
      const origHost = row.dataset.originalHost || row.getAttribute('data-original-host');
      const origShowType = row.dataset.originalShowType || 'gsp';
      const origCancelled = row.dataset.originalCancelled || 'false';
      const origCancelReason = row.dataset.originalCancelReason || '';
      
      const day = row.querySelector('.schedule-day-select')?.value || '';
      const time = row.querySelector('.schedule-time-input')?.value || '';
      const hostId = row.querySelector('.schedule-host-select')?.value || '';
      const isCancelled = row.dataset.cancelled === 'true' ? 'true' : 'false';
      const cancelReason = row.dataset.cancelReason || '';
      
      // Check if any field changed: day, time, host, or cancellation
      if (String(day) !== String(origDay) || 
          String(time) !== String(origTime) || 
          String(hostId) !== String(origHost) ||
          String(isCancelled) !== String(origCancelled) ||
          String(cancelReason) !== String(origCancelReason)) {
        toSave.push({ 
          id, 
          name, 
          default_day: day || null, 
          default_time: time || null, 
          default_host_id: hostId ? parseInt(hostId,10) : null, 
          is_active: row.dataset.isActive === 'true',
          notes: cancelReason || null // Store cancel reason in notes field (or create a new DB column)
        });
      }
    });

    if (!toSave.length) { GSP.status(gs, 'info', 'No changes to save.'); return; }
    try {
      GSP.status(gs, 'info', `Saving ${toSave.length} venues…`);
      await Promise.all(toSave.map(v => j(`${API}/admin/venues/${v.id}`, { 
        method: 'PUT', 
        body: JSON.stringify({ 
          name: v.name, 
          default_day: v.default_day, 
          default_time: v.default_time, 
          default_host_id: v.default_host_id,
          is_active: v.is_active,
          notes: v.notes
        }) 
      })));
      GSP.status(gs, 'success', 'Schedule updates saved.');
      // Reload builder to refresh originals
      await renderScheduleBuilder(getEl);
    } catch (e) {
      GSP.status(gs, 'error', `Save failed: ${e.message || e}`);
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
            // Load hosts and fill venue default host dropdown
            await loadHosts(getEl);
        } catch (e) {
            GSP.status(getEl('globalStatus'), 'error', 'Failed to load venues for dropdowns.');
        }
      }
      initialLoad();
      // --- Schedule Builder wires ---
      const loadScheduleBtn = getEl('loadScheduleBtn');
      const generateScheduleBtn = getEl('generateScheduleBtn');
      const saveHostChangesBtn = getEl('saveHostChangesBtn');
      loadScheduleBtn?.addEventListener('click', () => renderScheduleBuilder(getEl));
      generateScheduleBtn?.addEventListener('click', () => generateScheduleText(getEl));
      saveHostChangesBtn?.addEventListener('click', () => saveHostChanges(getEl));
        // --- Weekly report wires ---
        const reportBtn = getEl('loadWeeklyReportBtn');
        const exportBtn = getEl('exportWeeklyReportBtn');
        const reportInput = getEl('reportWeekEnding');

        if (reportBtn) reportBtn.addEventListener('click', () => loadWeeklyReport(getEl, reportInput?.value || ''));
        if (exportBtn) exportBtn.addEventListener('click', () => exportWeeklyReport(getEl));
      
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