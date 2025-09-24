// assets/smm.js (global, safe to load from header)
document.addEventListener("DOMContentLoaded", () => {
  const grid = document.getElementById('list');
  const search = document.getElementById('searchInput');

  function card(e){
    const date = e.date || '';
    const title = `${e.venue || ''}`;
    const host = e.host ? `Host: ${e.host}` : '';
    return `
      <div class="card">
        <div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap;">
          <strong style="font-size:18px; color: var(--text-strong);">${title}</strong>
          <span class="badge ${e.status==='posted'?'posted':'unposted'}">${e.status}</span>
          <span style="margin-left:auto; color:var(--muted); font-size:13px;">${date}</span>
        </div>
        <div style="margin-top:8px; color:var(--text-weak); font-size:14px;">${host}</div>

        <div style="display:grid; gap:12px; margin-top:16px;">
          <div class="row" style="grid-template-columns:1fr;">
            <input class="input fb-input" data-id="${e.id}" placeholder="Facebook Event URL (https://…)" />
            <div class="help">Required to mark as posted.</div>
          </div>
          <div style="display:flex; gap:12px; flex-wrap:wrap;">
            <a class="btn btn-ghost" href="/smm/event?id=${e.id}${CONFIG.TOKEN ? `&t=${encodeURIComponent(CONFIG.TOKEN)}`:''}">Open Event</a>
            <button class="btn btn-primary mark-posted" data-id="${e.id}">Mark Posted</button>
          </div>
        </div>
      </div>
    `;
  }

  let cached = [];

  async function load() {
    try {
      cached = await CONFIG.j(`${CONFIG.API_BASE_URL}/events?status=unposted`);
      render(cached);
    } catch (e) {
      if (grid) grid.innerHTML = `<div class="card">Error loading events: ${e.message}</div>`;
    }
  }

  function render(list) {
    if (!grid) return;
    if (!list.length) {
      grid.innerHTML = `<div class="card">No unposted events.</div>`;
      return;
    }
    grid.style.gridTemplateColumns = '1fr';
    if (window.matchMedia('(min-width: 880px)').matches) grid.style.gridTemplateColumns = '1fr 1fr';
    if (window.matchMedia('(min-width: 1200px)').matches) grid.style.gridTemplateColumns = '1fr 1fr 1fr';
    grid.innerHTML = list.map(card).join('');

    // wire actions
    grid.querySelectorAll('.mark-posted').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        const fb = grid.querySelector(`.fb-input[data-id="${id}"]`).value.trim();
        if (!fb) { alert('Facebook Event URL is required.'); return; }
        try {
          await CONFIG.j(`${CONFIG.API_BASE_URL}/events/${id}/status`, {
            method: 'PUT',
            body: JSON.stringify({ status: 'posted', fb_event_url: fb })
          });
          load();
        } catch (e) { alert('Failed: ' + e.message); }
      });
    });
  }

  function filter() {
    if (!search) return;
    const q = (search.value || '').toLowerCase();
    const out = cached.filter(e =>
      (e.venue || '').toLowerCase().includes(q) ||
      (e.host || '').toLowerCase().includes(q) ||
      (e.date || '').toLowerCase().includes(q)
    );
    render(out);
  }

  if (search) search.addEventListener('input', filter);
  load();
});