(function () {
  const API = CONFIG.API_BASE_URL;

  // --- Internal Module Helpers (No DOM access, No GSP/CONFIG calls here) ---
  function badgeShowType(st) {
    const s = (st || "gsp").toLowerCase();
    const label = s === "musingo" ? "Musingo" : s === "private" ? "Private" : "GSP";
    const cls = `badge st ${s === "musingo" ? "musingo" : s === "private" ? "private" : "gsp"}`;
    return `<span class="${cls}">${label}</span>`;
  }
  function fmtDate(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleDateString();
    } catch {
      return iso;
    }
  }
  function calculateWeekEnding(dateStr) {
  const date = new Date(dateStr);
  const day = date.getDay();  // 0=Sun, 1=Mon, ..., 6=Sat
  const daysToSunday = (7 - day) % 7 || 7;  // If already Sunday, next Sunday
  date.setDate(date.getDate() + daysToSunday);
  return date.toISOString().split('T')[0];  // YYYY-MM-DD
  }
  // --- MODULE FOR: Admin Events List Page ---
  function initAdminList({ getEl }) {
    const q = getEl('q');
    const showType = getEl('showType');
    const statusSel = getEl('status');
    const start = getEl('start');
    const end = getEl('end');
    const searchBtn = getEl('searchBtn');
    const clearBtn = getEl('clearBtn');
    const tbody = getEl('eventsTbody');
    const adminStatus = getEl('adminStatus');

    async function search() {
      GSP.clearStatus(adminStatus);
      tbody.innerHTML = '<tr><td colspan="8">Loading…</td></tr>';
      try {
        const params = new URLSearchParams({ limit: '500' });
        if (q && q.value.trim()) params.set('q', q.value.trim());
        if (showType && showType.value) params.set('show_type', showType.value);
        if (statusSel && statusSel.value) params.set('status', statusSel.value);
        if (start && start.value) params.set('start', start.value);
        if (end && end.value) params.set('end', end.value);
        
        const items = await GSP.j(`${API}/admin/events?${params.toString()}`);
        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="8">No results.</td></tr>';
          return;
        }
        tbody.innerHTML = items.map(e => `
          <tr>
            <td>${fmtDate(e.event_date)}</td>
            <td>${e.host || '—'}</td>
            <td>${e.venue || '—'}</td>
            <td>${badgeShowType(e.show_type)}</td>
            <td>${e.status}</td>
            <td>${e.has_ai ? 'Yes' : 'No'}</td>
            <td>${e.is_validated ? '<span class="badge success">Yes</span>' : '<span class="badge">No</span>'}</td>
            <td class="table-actions">
              <a class="btn btn-ghost" href="/admin/event?id=${e.id}">Edit</a>
              <a class="btn btn-ghost" href="/host/event?id=${e.id}" target="_blank">View</a>
            </td>
          </tr>
        `).join('');
      } catch (err) {
        GSP.status(adminStatus, 'error', err.message);
        tbody.innerHTML = '<tr><td colspan="8">Error.</td></tr>';
      }
    }

    if (searchBtn) searchBtn.addEventListener('click', search);
    if (clearBtn) clearBtn.addEventListener('click', () => {
      if (q) q.value = '';
      if (showType) showType.value = '';
      if (statusSel) statusSel.value = '';
      if (start) start.value = '';
      if (end) end.value = '';
      tbody.innerHTML = '<tr><td colspan="8">Cleared. Click Search.</td></tr>';
      GSP.clearStatus(adminStatus);
    });

    search(); // Initial search on page load
  }

  // --- MODULE FOR: Admin Event Editor Page ---
  function initAdminEvent({ getEl }) {
    const params = new URLSearchParams(location.search);
    const eid = params.get('id');
    const statusEl = getEl('evtStatus');

    if (!eid) {
      GSP.status(statusEl, 'error', 'Missing event id');
      return;
    }

  // --- Drag-and-Drop Logic (Scoped to this function) ---
    function wireDragAndDrop() {
        const container = getEl('partsContainer');
        if (!container) return;

        let dragSourceElement = null;

        container.addEventListener('dragstart', e => {
            const target = e.target.closest('.team-block');
            if (target) {
                dragSourceElement = target;
                e.dataTransfer.effectAllowed = 'move';
                setTimeout(() => target.classList.add('dragging'), 0);
            }
        });

        container.addEventListener('dragend', e => {
            const target = e.target.closest('.team-block');
            if (target) {
                target.classList.remove('dragging');
            }
            dragSourceElement = null;
        });

        container.addEventListener('dragover', e => {
            e.preventDefault();
            const target = e.target.closest('.team-block');
            container.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
            if (target && target !== dragSourceElement) {
                target.classList.add('drag-over');
            }
        });

        container.addEventListener('dragleave', e => {
            e.target.closest('.team-block')?.classList.remove('drag-over');
        });

        container.addEventListener('drop', e => {
            e.preventDefault();
            const dropTargetElement = e.target.closest('.team-block');
            container.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));

            if (!dragSourceElement || !dropTargetElement || dragSourceElement === dropTargetElement) {
                return;
            }

            const allTeamBlocks = Array.from(container.querySelectorAll('.team-block'));
            const sourceIndex = allTeamBlocks.indexOf(dragSourceElement);
            const targetIndex = allTeamBlocks.indexOf(dropTargetElement);

            const getData = (block) => ({
                name: block.querySelector('.part-name').value,
                players: block.querySelector('.part-players').value,
                visiting: block.querySelector('.part-vis').checked,
                tournament: block.querySelector('.part-tour').checked
            });

            const setData = (block, data) => {
                block.querySelector('.part-name').value = data.name;
                block.querySelector('.part-players').value = data.players;
                block.querySelector('.part-vis').checked = data.visiting;
                block.querySelector('.part-tour').checked = data.tournament;
            };

            const sourceData = getData(dragSourceElement);

            if (sourceIndex < targetIndex) {
                // Dragging DOWN: Shift elements UP
                for (let i = sourceIndex; i < targetIndex; i++) {
                    const nextData = getData(allTeamBlocks[i + 1]);
                    setData(allTeamBlocks[i], nextData);
                }
            } else {
                // Dragging UP: Shift elements DOWN
                for (let i = sourceIndex; i > targetIndex; i--) {
                    const prevData = getData(allTeamBlocks[i - 1]);
                    setData(allTeamBlocks[i], prevData);
                }
            }
            setData(allTeamBlocks[targetIndex], sourceData);
        });
    }

    // --- Tournament Scoring Logic (Scoped to this function) ---
    let allTournamentTeams = []; // Cache for fuzzy matching

    function stringSimilarity(s1, s2) {
      let longer = s1, shorter = s2;
      if (s1.length < s2.length) { longer = s2; shorter = s1; }
      const longerLength = longer.length;
      if (longerLength === 0) return 1.0;
      const editDistance = (s1, s2) => {
        s1 = s1.toLowerCase(); s2 = s2.toLowerCase();
        const costs = [];
        for (let i = 0; i <= s1.length; i++) {
          let lastValue = i;
          for (let j = 0; j <= s2.length; j++) {
            if (i === 0) costs[j] = j;
            else if (j > 0) {
              let newValue = costs[j - 1];
              if (s1.charAt(i - 1) !== s2.charAt(j - 1)) newValue = Math.min(newValue, lastValue, costs[j]) + 1;
              costs[j - 1] = lastValue;
              lastValue = newValue;
            }
          }
          if (i > 0) costs[s2.length] = lastValue;
        }
        return costs[s2.length];
      };
      return (longerLength - editDistance(longer, shorter)) / parseFloat(longerLength);
    }

    async function initTournamentScoring(participationData) {
      const container = getEl('tourneyScoresContainer');
      const tourneyStatusEl = getEl('tourneyScoreStatus');
      if (!container) return;

      if (allTournamentTeams.length === 0) {
        try {
          allTournamentTeams = await GSP.j(`${API}/admin/tournament-teams`);
        } catch (e) {
          GSP.status(tourneyStatusEl, 'error', 'Could not load tournament teams for matching.');
          return;
        }
      }

      const tournamentEntries = participationData.filter(p => p.is_tournament);
      if (tournamentEntries.length === 0) {
        container.innerHTML = '<div class="p">No teams were marked for tournament play in the parsed data.</div>';
        return;
      }

      container.innerHTML = tournamentEntries.map(p => {
        let bestMatchId = null;
        let highestSim = 0.0;
        allTournamentTeams.forEach(tt => {
          const sim = stringSimilarity(p.team_name, tt.name);
          if (sim > highestSim && sim > 0.7) {
            highestSim = sim;
            bestMatchId = tt.id;
          }
        });

        const options = allTournamentTeams.map(tt => 
            `<option value="${tt.id}" ${tt.id === bestMatchId ? 'selected' : ''}>${tt.name}</option>`
        ).join('');

        // --- TEMPLATE UPDATED HERE ---
        // Added a 3-column grid and a new form-group for Player Count.
        return `
        <div class="row row-3 tourney-score-row" style="padding: 8px 0; border-bottom: 1px solid var(--border);">
            <div class="form-group">
                <label>Parsed Team: <strong>${p.team_name}</strong></label>
                <select class="input link-team-select">
                    <option value="">-- Link to Official Team --</option>
                    ${options}
                </select>
            </div>
            <div class="form-group">
                <label>Tournament Points</label>
                <input type="number" class="input points-awarded" placeholder="e.g., 10" />
            </div>
            <div class="form-group">
                <label>Player Count</label>
                <input type="number" class="input num-players-awarded" placeholder="# Players" value="${p.num_players || ''}" />
            </div>
        </div>
        `;
        // --- END OF UPDATE ---
      }).join('');
    }

    // --- End of Tournament Scoring Logic ---
    function participationRowTpl(r) {
      return `
      <div class="part-row" style="display: grid; grid-template-columns: 80px 1fr 150px; gap: 12px; align-items: center; margin: 8px 0; padding-bottom: 8px; border-bottom: 1px solid var(--border);">
        
        <!-- Column 1: Position (Not Draggable) -->
        <input class="input part-position" type="number" min="1" placeholder="Pos" value="${r.position || ''}" style="text-align: center; font-weight: bold;" />
        
        <!-- Column 2: Draggable Team Block -->
        <div class="team-block" draggable="true">
            <input class="input part-name" placeholder="Team Name" value="${r.team_name || ''}" />
            <div style="display: flex; gap: 10px; margin-top: 6px; align-items: center; padding-left: 4px;">
                <input class="input part-players" type="number" placeholder="# Players" value="${r.num_players != null ? r.num_players : ''}" style="max-width: 120px;" />
                <label class="kv-inline" style="flex-shrink: 0; white-space: nowrap;"><input type="checkbox" class="part-vis" ${r.is_visiting ? 'checked' : ''}/> Visiting</label>
                <label class="kv-inline" style="flex-shrink: 0; white-space: nowrap;"><input type="checkbox" class="part-tour" ${r.is_tournament ? 'checked' : ''}/> Tournament</label>
            </div>
        </div>

        <!-- Column 3: Score and Delete (Not Draggable) -->
        <div style="display: flex; align-items: center; gap: 8px;">
            <input class="input part-score" type="number" placeholder="Score" value="${r.score != null ? r.score : ''}" />
            <button type="button" class="btn btn-ghost del-part-row" style="flex-shrink: 0; padding: 8px 12px;">X</button>
        </div>
      </div>`;
    }

    async function load() {
      GSP.clearStatus(statusEl);
      try {
        const e = await GSP.j(`${API}/admin/events/${eid}`);
        
        getEl('showType').value = (e.show_type || 'gsp').toLowerCase();
        getEl('eventDate').value = (e.event_date || '').split('T')[0] || '';
        getEl('status').value = e.status || 'unposted';
        getEl('hostId').value = e.host?.id || '';
        getEl('venueId').value = e.venue?.id || '';
        getEl('fbUrl').value = e.fb_event_url || '';
        getEl('highlights').value = e.highlights || '';
        getEl('aiRecap').value = e.ai_recap || '';
        getEl('pdfUrl').value = e.pdf_url || '';
        
        const validationStatusEl = getEl('validationStatus');
        const validateBtn = getEl('validateEventBtn');
        if (e.is_validated) {
          validationStatusEl.textContent = 'Validated';
          validationStatusEl.classList.add('success');
          validateBtn.textContent = 'Unvalidate Event';
        } else {
          validationStatusEl.textContent = 'Not Validated';
          validationStatusEl.classList.remove('success');
          validateBtn.textContent = 'Validate Event';
        }

        getEl('createdAt').textContent = e.created_at ? new Date(e.created_at).toLocaleString() : 'N/A';
        getEl('updatedAt').textContent = e.updated_at ? new Date(e.updated_at).toLocaleString() : 'N/A';

        const partsContainer = getEl('partsContainer');
        partsContainer.innerHTML = (e.participation?.length) ? e.participation.map(participationRowTpl).join('') : participationRowTpl({});
        partsContainer.querySelectorAll('.del-part-row').forEach(button => {
          button.addEventListener('click', (event) => event.target.closest('.part-row')?.remove());
        });

        const photosList = getEl('photosList');
        photosList.innerHTML = (e.photos || []).map(u => `
          <div>
            <img src="${u}" style="width:100%;border-radius:8px;" />
            <div class="small">${u.split('/').pop()}</div>
            <button class="btn btn-ghost" data-del="${encodeURIComponent(u)}" style="margin-top:6px;">Remove</button>
          </div>
        `).join('');
        photosList.querySelectorAll('button[data-del]').forEach(b => {
          b.addEventListener('click', async () => {
            try {
              await GSP.j(`${API}/admin/events/${eid}/photos?photoUrl=${b.dataset.del}`, { method: 'DELETE' });
              b.parentElement.remove();
            } catch (err) {
              GSP.status(statusEl, 'error', 'Remove failed: ' + err.message);
            }
          });
        });

        await initTournamentScoring(e.participation || []);

      } catch (err) {
        GSP.status(statusEl, 'error', err.message);
      }
    }

    // --- Wire All Buttons ---
    getEl('addRowBtn')?.addEventListener('click', () => {
      const partsContainer = getEl('partsContainer');
      partsContainer?.insertAdjacentHTML('beforeend', participationRowTpl({}));
      // Re-wire the new delete button
      partsContainer.querySelector('.part-row:last-child .del-part-row')?.addEventListener('click', (event) => {
        event.target.closest('.part-row')?.remove();
      });
    });

    getEl('savePartsBtn')?.addEventListener('click', async () => {
      const statusEl = getEl('status');  // Assuming you have a status element
      GSP.clearStatus(statusEl);
      try {
        const rows = Array.from(getEl('partsContainer').querySelectorAll('.part-row')).map(div => ({
          position: parseInt(div.querySelector('.part-position')?.value, 10) || null,
          team_name: div.querySelector('.part-name')?.value.trim() || '',
          score: div.querySelector('.part-score')?.value === '' ? null : parseInt(div.querySelector('.part-score')?.value, 10),
          num_players: div.querySelector('.part-players')?.value === '' ? null : parseInt(div.querySelector('.part-players')?.value, 10),
          is_visiting: div.querySelector('.part-vis')?.checked || false,
          is_tournament: div.querySelector('.part-tour')?.checked || false,
        })).filter(r => r.team_name);

        // Existing save to participation endpoint
        await GSP.j(`${API}/admin/events/${eid}/participation`, { method: 'PUT', body: JSON.stringify({ teams: rows }) });
        GSP.status(statusEl, 'success', 'Rankings saved.');

      } catch (err) {
        GSP.status(statusEl, 'error', 'Save failed: ' + err.message);
      }
    });

    getEl('saveBtn')?.addEventListener('click', async () => {
      GSP.clearStatus(statusEl);
      try {
          const body = {
            show_type: getEl('showType').value,
            event_date: getEl('eventDate').value || null,
            status: getEl('status').value || null,
            host_id: getEl('hostId').value ? parseInt(getEl('hostId').value, 10) : null,
            venue_id: getEl('venueId').value ? parseInt(getEl('venueId').value, 10) : null,
            fb_event_url: getEl('fbUrl').value || null,
            highlights: getEl('highlights').value || null,
            ai_recap: getEl('aiRecap').value || null,
            pdf_url: getEl('pdfUrl').value || null,
          };
          Object.keys(body).forEach(k => (body[k] == null) && delete body[k]);
          await GSP.j(`${API}/admin/events/${eid}`, { method: 'PUT', body: JSON.stringify(body) });
          GSP.status(statusEl, 'success', 'Event saved.');
      } catch (err) {
          GSP.status(statusEl, 'error', `Save failed: ${err.message}`);
      }
    });

    // Wire up the save button for tournament scores
    getEl('saveTourneyScoresBtn')?.addEventListener('click', async () => {
        const tourneyStatusEl = getEl('tourneyScoreStatus');
        GSP.clearStatus(tourneyStatusEl);

        try {
            const scoreRows = Array.from(getEl('tourneyScoresContainer').querySelectorAll('.tourney-score-row'));
            
            const teamsPayload = scoreRows.map(row => {
                const teamId = row.querySelector('.link-team-select')?.value;
                const pointsInput = row.querySelector('.points-awarded');
                const points = parseInt(pointsInput?.value, 10) || 0;
                
                // --- NEW CODE HERE ---
                // Read the value from the new num_players input.
                const numPlayersInput = row.querySelector('.num-players-awarded');
                const numPlayers = numPlayersInput?.value ? parseInt(numPlayersInput.value, 10) : null;
                // --- END OF NEW CODE ---

                if (teamId) {
                    return {
                        team_id: parseInt(teamId, 10),
                        points: points,
                        num_players: numPlayers // Add the new value to the payload
                    };
                }
                return null;
            }).filter(Boolean);

            if (teamsPayload.length === 0) {
                GSP.status(tourneyStatusEl, 'info', 'No tournament teams were linked to save.');
                return;
            }

            const payload = { teams: teamsPayload };
            
            console.log("SENDING PAYLOAD:", JSON.stringify(payload, null, 2));
            
            const data = await GSP.j(`${API}/admin/events/${eid}/tournament-scores`, {
                method: 'PUT',
                body: JSON.stringify(payload)
            });

            GSP.status(tourneyStatusEl, 'success', data.message || `Saved ${teamsPayload.length} scores.`);

        } catch (err) {
            GSP.status(tourneyStatusEl, 'error', `Save failed: ${err.message}`);
            console.error("Error during save:", err);
        }
    });

    getEl('parseBtn')?.addEventListener('click', async () => {
      GSP.clearStatus(statusEl);
      GSP.status(statusEl, 'info', 'Parsing PDF and generating AI recap...');
      try {
        const response = await GSP.j(`${API}/events/${eid}/parse-pdf`, { method: 'POST' });
        if (response.status === 'success' && response.ai_recap_generated) {
          getEl('aiRecap').value = response.ai_recap_generated;
          GSP.status(statusEl, 'success', 'Parse triggered and AI recap generated.');
        } else {
          GSP.status(statusEl, 'error', response.error || 'Parse triggered but no teams or AI recap found.');
        }
        load();
      } catch (err) {
        GSP.status(statusEl, 'error', `Parse failed: ${err.message}`);
      }
    });
    getEl('addPhotoUrlBtn')?.addEventListener('click', async () => {
      GSP.clearStatus(statusEl);
      const photoUrlInput = getEl('photoUrlInput');
      const u = (photoUrlInput.value || '').trim();
      if (!u) {
        GSP.status(statusEl, 'error', 'Enter a photo URL.');
        return;
      }
      try {
        await GSP.j(`${API}/admin/events/${eid}/photos`, {
          method: 'POST',
          body: JSON.stringify({ photoUrl: u })
        });
        photoUrlInput.value = '';
        GSP.status(statusEl, 'success', 'Photo linked.');
        load();
      } catch (err) {
        GSP.status(statusEl, 'error', 'Add photo failed: ' + err.message);
      }
    });

    getEl('validateEventBtn')?.addEventListener('click', async () => {
      GSP.clearStatus(statusEl);
      const validateBtn = getEl('validateEventBtn');
      const isCurrentlyValidated = validateBtn.textContent === 'Unvalidate Event';
      try {
        await GSP.j(`${API}/admin/events/${eid}/validate`, {
          method: 'PUT',
          body: JSON.stringify({ is_validated: !isCurrentlyValidated }),
        });
        GSP.status(statusEl, 'success', `Event ${!isCurrentlyValidated ? 'validated' : 'unvalidated'}.`);
        load();
      } catch (err) {
        GSP.status(statusEl, 'error', 'Validation update failed: ' + err.message);
      }
    });

    getEl('viewPdfOriginalBtn')?.addEventListener('click', () => {
      const pdfUrl = getEl('pdfUrl').value;
      if (pdfUrl) {
        window.open(pdfUrl, '_blank');
      } else {
        GSP.status(statusEl, 'error', 'No PDF URL available to view.');
      }
    });
    
    load(); // Initial load for the page
    wireDragAndDrop(); // Wire drag-and-drop listeners ONCE on initialization
  }

  // --- EXPOSE TO GLOBAL SCOPE for main.js router ---
  window.AdminPages = {
    initAdminList: initAdminList,
    initAdminEvent: initAdminEvent
  };
})();