// assets/smm-event.js
/* global CONFIG, GSP */

(function () {
  // Aliases for global helpers exposed by main.js
  const j = GSP.j;
  const status = GSP.status;
  const clearStatus = GSP.clearStatus;
  const getEl = GSP.getEl;

  const API_BASE_URL = CONFIG.API_BASE_URL;

  function renderEvent(e, els) {
    const aiInput = getEl("aiRecapInput");
    const openPdfBtn = getEl("openPdfBtn");
    const fbUrlInput = getEl("fbUrlInput");
    const details = getEl("smmEventDetails");
    const photosContainer = getEl("smmPhotosContainer"); // Container for photo buttons

    if (aiInput) aiInput.value = e.ai_recap || "";
    if (fbUrlInput) fbUrlInput.value = e.fb_event_url || "";
    if (openPdfBtn) {
      openPdfBtn.href = e.pdf_url || "#";
      openPdfBtn.style.display = e.pdf_url ? "inline-flex" : "none";
    }
    if (!details) return;

    const photos = Array.isArray(e.photos) ? e.photos : [];
    const hasPhotos = photos.length > 0;
    const dateStr = e.event_date ? new Date(e.event_date).toLocaleDateString() : "—";

    const photosHTML = hasPhotos
      ? `<div class="media-grid">${photos.map(u => `<img src="${u}" style="margin-top: var(--space-3); display:flex; gap:12px; flex-wrap:wrap;" alt="event photo" loading="lazy">`).join("")}</div>`
      : `<div class="p">No photos uploaded yet.</div>`;
    
    // RENDER MAIN DETAILS
    details.innerHTML = `
      <div class="p"><strong>Date:</strong> ${dateStr}</div>
      <div class="p"><strong>Venue:</strong> ${e.venue || "—"}</div>
      <div class="p"><strong>Host:</strong> ${e.host || "—"}</div>
      <div class="p">
        <span class="badge ${e.status === "posted" ? "posted" : "unposted"}">${e.status}</span>
        ${e.pdf_url ? '<span class="badge">PDF</span>' : ""}
        ${hasPhotos ? `<span class="badge">Photos: ${photos.length}</span>` : ""}
        ${e.ai_recap && e.ai_recap.trim() ? '<span class="badge">AI</span>' : ""}
        ${e.is_validated ? '<span class="badge success">Validated</span>' : '<span class="badge">Not Validated</span>'}
      </div>
      <div class="section">
        <h2 class="h2">Preview</h2>
        ${photosHTML}
      </div>
    `;

    // --- BATCHING UI LOGIC ---
    if (photosContainer) {
      const photoCount = photos.length;
      const batchSize = 12;
      let buttonsHtml = '';

      if (photoCount > 0) {
        if (photoCount <= batchSize) {
          // Render a single download button
          buttonsHtml = `<a class="btn btn-primary" href="${API_BASE_URL}/events/${e.id}/download-photos">Download All Photos (.zip)</a>`;
        } else {
          // Render multiple batch download buttons
          const numBatches = Math.ceil(photoCount / batchSize);
          for (let i = 1; i <= numBatches; i++) {
            const start = (i - 1) * batchSize + 1;
            const end = Math.min(i * batchSize, photoCount);
            buttonsHtml += `<a class="btn btn-primary" href="${API_BASE_URL}/events/${e.id}/download-photos?batch=${i}">Zip Batch ${i} (${start} - ${end})</a>`;
          }
        }
      }

      // Add the Open PDF button to the buttonsHtml string
      buttonsHtml += `<a class="btn btn-ghost" id="openPdfBtn" href="${e.pdf_url || '#'}" target="_blank" style="display: ${e.pdf_url ? 'inline-flex' : 'none'};">Open PDF</a>`;
      photosContainer.innerHTML = buttonsHtml;
    }
  }

  async function loadEvent(eventId, els) {
    const statusBox = getEl("smmEventStatus");
    clearStatus(statusBox);
    try {
      const e = await j(`${API_BASE_URL}/events/${eventId}`);
      renderEvent(e, els);
      return e;
    } catch (err) {
      status(statusBox, "error", `Failed to load event: ${err.message}`);
      throw err;
    }
  }

  function wire(eventId, els) {
    const actionStatus = getEl("smmActionStatus");
    const aiInput = getEl("aiRecapInput");
    const markPostedBtn = getEl("markPostedBtn");
    const fbUrlInput = getEl("fbUrlInput");
    const loadNewestAiBtn = getEl("loadNewestAiBtn");

    if (loadNewestAiBtn) loadNewestAiBtn.onclick = async () => {
      clearStatus(actionStatus);
      status(actionStatus, "info", "Loading newest AI recap from server…");
      try {
        const eventData = await j(`${API_BASE_URL}/events/${eventId}`);
        if (aiInput) aiInput.value = eventData.ai_recap || "";
        status(actionStatus, "success", "Newest AI recap loaded.");
      } catch (err) {
        status(actionStatus, "error", `Failed to load newest AI recap: ${err.message}`);
      }
    };

    if (markPostedBtn) markPostedBtn.onclick = async () => {
      clearStatus(actionStatus);
      const fbUrl = fbUrlInput ? fbUrlInput.value.trim() : "";
      if (!fbUrl) {
        status(actionStatus, "error", "Facebook Event URL is required to mark as posted.");
        return;
      }
      status(actionStatus, "info", "Marking event as posted…");
      try {
        await j(`${API_BASE_URL}/events/${eventId}/status`, {
          method: "PUT",
          body: JSON.stringify({ status: "posted", fb_event_url: fbUrl })
        });
        status(actionStatus, "success", "Event marked as posted and published to www.gspevents.com!");
        await loadEvent(eventId, els);
      } catch (err) {
        status(actionStatus, "error", `Failed to mark posted: ${err.message}`);
      }
    };
  }

  window.SMMEvent = {
    init: function ({ getEl }) {
      const params = new URLSearchParams(location.search);
      const eventId = params.get("id");

      if (!eventId) {
        const statusBox = getEl("smmEventStatus");
        status(statusBox, "error", "Missing event ID.");
        return;
      }

      const els = { getEl };
      loadEvent(eventId, els).catch(() => {});
      wire(eventId, els);
    }
  };
})();