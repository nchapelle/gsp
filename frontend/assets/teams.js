// teams.js
(async function () {
  async function j(u,o={}){ return CONFIG.j(u,o); }
  function showStatus(node, type, msg){ node.classList.remove('success','error'); node.style.display='block'; node.textContent=msg; if (type) node.classList.add(type); }

  let editId = null;

  async function loadVenues(){
    const v = await j(`${CONFIG.API_BASE_URL}/venues`);
    const sel = document.getElementById('tHomeVenue');
    sel.innerHTML = `<option value="">Select Home Venue (optional)</option>` + v.map(x=>`<option value="${x.id}">${x.name}</option>`).join('');
  }
  async function loadTeams(){
    const t = await j(`${CONFIG.API_BASE_URL}/tournament-teams`);
    const ul = document.getElementById('teams');
    if (!t.length) { ul.innerHTML = `<li class="item">No teams yet.</li>`; return; }
    ul.innerHTML = t.map(tt => `
      <li class="item" style="display:flex; gap:12px; align-items:center; flex-wrap:wrap;">
        <strong style="color:var(--text-strong);">${tt.name}</strong>
        ${tt.home_venue ? `<span class="badge">${tt.home_venue}</span>` : ''}
        <span style="margin-left:auto; display:flex; gap:8px;">
          <button class="btn btn-ghost edit" data-id="${tt.id}">Edit</button>
          <button class="btn btn-ghost del" data-id="${tt.id}">Delete</button>
        </span>
      </li>
    `).join('');

    ul.querySelectorAll('.edit').forEach(b => b.addEventListener('click', () => editTeam(parseInt(b.dataset.id))));
    ul.querySelectorAll('.del').forEach(b => b.addEventListener('click', async () => {
      const id = parseInt(b.dataset.id);
      if (!confirm('Delete this team?')) return;
      await j(`${CONFIG.API_BASE_URL}/tournament-teams/${id}`, { method:'DELETE' });
      if (editId === id){ editId = null; fillForm({}); }
      loadTeams();
    }));
  }
  function readForm(){
    return {
      name: document.getElementById('tName').value.trim(),
      home_venue_id: parseInt(document.getElementById('tHomeVenue').value) || null,
      captain_name: document.getElementById('tCapName').value.trim(),
      captain_email: document.getElementById('tCapEmail').value.trim(),
      captain_phone: document.getElementById('tCapPhone').value.trim()
    };
  }
  function fillForm(t){
    document.getElementById('tName').value = t.name || '';
    document.getElementById('tHomeVenue').value = t.home_venue_id || '';
    document.getElementById('tCapName').value = t.captain_name || '';
    document.getElementById('tCapEmail').value = t.captain_email || '';
    document.getElementById('tCapPhone').value = t.captain_phone || '';
  }

  document.getElementById('saveTeam').addEventListener('click', async ()=>{
    const st = document.getElementById('teamStatus');
    const body = readForm();
    if (!body.name){ showStatus(st,'error','Team name is required.'); return; }
    try {
      if (editId){
        await j(`${CONFIG.API_BASE_URL}/admin/tournament-teams/${editId}`, {
          method:'PUT', body:JSON.stringify(body)
        });
      } else {
        await j(`${CONFIG.API_BASE_URL}/admin/tournament-teams`, {
          method:'POST', body:JSON.stringify(body)
        });
      }
      showStatus(st,'success','Saved.');
      editId = null;
      loadTeams();
    } catch (e) {
      showStatus(st,'error','Error: ' + e.message);
    }
  });

  document.getElementById('resetForm').addEventListener('click', ()=>{
    editId = null; fillForm({}); document.getElementById('teamStatus').style.display='none';
  });

  async function editTeam(id){
    const list = await j(`${CONFIG.API_BASE_URL}/tournament-teams`);
    const t = list.find(x=>x.id===id);
    if (!t) return;
    editId = id; fillForm(t);
  }

  await loadVenues();
  await loadTeams();
})();
