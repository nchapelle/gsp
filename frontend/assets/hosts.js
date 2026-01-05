/* assets/hosts.js */
/* global CONFIG, GSP, GSPAuth */
(function () {
  // Initialize authentication - require host or admin role
  if (typeof GSPAuth !== 'undefined') {
    GSPAuth.init({
      requiredRoles: ['host', 'admin'],
      requireAuth: true,
      onAuthReady: function(user) {
        if (user) {
          console.log('[hosts] Auth ready, user:', user.email, 'role:', user.role, 'display_name:', user.display_name);
          // Trigger form initialization after auth is ready
          if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function() {
              initFormWhenReady();
            });
          } else {
            initFormWhenReady();
          }
        }
      }
    });
  } else {
    console.error('[hosts] GSPAuth not loaded');
  }

  // --- Start of Re-included Helper Functions ---
  function log() {
    var args = Array.prototype.slice.call(arguments);
    console.log.apply(console, ["[hosts]"].concat(args));
  }
  function getEl(id) {
    return document.getElementById(id);
  }
  function status(el, type, msg) {
    if (el && GSP && GSP.status) {
      GSP.status(el, type, msg);
    }
  }
  function clearStatus(el) {
    if (el && GSP && GSP.clearStatus) {
      GSP.clearStatus(el);
    }
  }
  function capitalize(s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  }

  async function normalizeIosImage(file) {
    var ext = (file.name || "").split(".").pop();
    ext = ext ? ext.toLowerCase() : "";
    var type = (file.type || "").toLowerCase();
    var isHeic =
      ext === "heic" || ext === "heif" || type === "image/heic" || type === "image/heif";
    if (!isHeic) return file;
    if (!window.heic2any) return file;
    try {
      var blob = await window.heic2any({ blob: file, toType: "image/jpeg", quality: 0.92 });
      var name = (file.name || "photo").replace(/\.(heic|heif)$/i, "") + ".jpg";
      return new File([blob], name, { type: "image/jpeg" });
    } catch (e) {
      console.warn("[hosts] heic2any conversion failed; using original", e);
      return file;
    }
  }

  function j(url, opts) {
    return CONFIG.j(url, opts || {});
  }

  function makeSegments(count) {
    var container = document.getElementById("segmentedBarContainer");
    var bar = document.getElementById("segmentedBar");
    if (!container || !bar) return null;
    bar.innerHTML = "";
    for (var i = 0; i < count; i++) {
      var seg = document.createElement("div");
      seg.className = "segment pending";
      var fill = document.createElement("div");
      fill.className = "segment-fill";
      seg.appendChild(fill);
      bar.appendChild(seg);
    }
    container.style.display = "block";
    return bar;
  }
  function updateSegment(index, status, tip) {
    var bar = document.getElementById("segmentedBar");
    if (!bar) return;
    var seg = bar.children[index];
    if (!seg) return;
    seg.className = "segment " + (status || "pending");
    var fill = seg.querySelector(".segment-fill");
    if (!fill) return;
    if (status === "success" || status === "error") fill.style.width = "100%";
    else if (status === "pending") fill.style.width = "30%";
    else if (status === "uploading") fill.style.width = "60%";
    if (tip) {
      seg.classList.add("tooltip");
      seg.setAttribute("data-tip", tip);
    } else {
      seg.classList.remove("tooltip");
      seg.removeAttribute("data-tip");
    }
  }
  function hideSegments() {
    var container = document.getElementById("segmentedBarContainer");
    var bar = document.getElementById("segmentedBar");
    if (container) container.style.display = "none";
    if (bar) bar.innerHTML = "";
  }
  // --- End of Re-included Helper Functions ---


  document.addEventListener("DOMContentLoaded", function () {
    // DOM refs
    var hostSel = getEl("hostName");
    var venueSel = getEl("venueName");
    var eventDate = getEl("eventDate");
    var highlights = getEl("highlights");
    var pdfFileInput = getEl("pdfRecap");
    var photoFilesInput = getEl("photos");
    var pdfRecapNameEl = getEl('pdfRecapName');
    var photosNameEl = getEl('photosName');
    var adjectiveSel = getEl("adjective");
    var showTypeSel = getEl("showType"); // Get reference to showType dropdown
    var submitButton = getEl("submitButton");
    var resetButton = getEl("resetButton");
    var uploadStatusDiv = getEl("uploadStatus");
    var recentEventsList = getEl("recentEventsList");
    var progressBarContainer = getEl("progressBarContainer");
    var progressBar = getEl("progressBar");
    var fileListUL = getEl("fileList");
    var loadPhotosBtn = getEl('load-recent-photos-btn');
    var recentPhotosSection = getEl('recent-photos-section');
    var photoZipLinkContainer = getEl('photo-zip-link');

    var allVenues = [];
    var allEvents = [];

    function getSelectedText(selectEl) {
      if (!selectEl || !selectEl.selectedOptions || !selectEl.selectedOptions[0]) return "";
      var t = selectEl.selectedOptions[0].textContent || "";
      return t.trim();
    }

    function normalizeNight(s) {
      if (!s) return "";
      var map = {
        sun: "Sunday", sunday: "Sunday",
        mon: "Monday", monday: "Monday",
        tue: "Tuesday", tues: "Tuesday", tuesday: "Tuesday",
        wed: "Wednesday", weds: "Wednesday", wednesday: "Wednesday",
        thu: "Thursday", thur: "Thursday", thurs: "Thursday", thursday: "Thursday",
        fri: "Friday", friday: "Friday",
        sat: "Saturday", saturday: "Saturday",
      };
      var k = String(s).toLowerCase();
      return map[k] || s;
    }

    function updateFileStatus(fileName, statusClass, message) {
      if (!fileListUL) return;
      var safeId = (fileName || "file").replace(/[^\w\.-]/g, "_");
      var id = "status-" + safeId;
      var itemId = "item-" + safeId;
      var el = fileListUL.querySelector("#" + id);
      if (!el) {
        var li = document.createElement("li");
        li.id = itemId;
        li.innerHTML =
          "<span>" +
          (fileName || "file") +
          '</span><span class="file-status ' +
          (statusClass || "") +
          '" id="' +
          id +
          '">' +
          (message || "") +
          "</span>";
        fileListUL.appendChild(li);
      } else {
        el.className = "file-status " + (statusClass || "");
        el.textContent = message || "";
      }
    }

    function applySmartDate(trigger) {
        if (!venueSel || !eventDate) return;
        var venueId = venueSel.value;
        var v = allVenues.find(v => String(v.id) === String(venueId));
        log("applySmartDate", { trigger: trigger || "?", venueId: venueId, venue: v });
        if (!v || !v.default_day) return;
        var day = normalizeNight(v.default_day);
        if (day && GSP.dayToIndex.hasOwnProperty(day)) {
            eventDate.value = GSP.mostRecentDayET(day);
        }
    }

    function renderRecent(list) {
      if (!recentEventsList) return;
      if (!list || !list.length) {
        recentEventsList.innerHTML = '<li class="item">No events yet for this selection.</li>';
        return;
      }
      var html = [];
      for (var i = 0; i < list.length; i++) {
        var e = list[i];
        var date = e.date || "";
        var host = e.host || "";
        var venue = e.venue || "";
        var statusCls = e.status === "posted" ? "posted" : "unposted";
        var validationStatus = e.is_validated ? "Validated" : "Not Validated";
        html.push(
          '<li class="item">' +
            "<strong>" +
            date +
            "</strong> — " +
            host +
            " @ " +
            venue +
            '<span class="badge ' +
            statusCls +
            '">' +
            statusCls +
            "</span>" +
            '<span class="badge ' + (e.is_validated ? 'validated' : 'pending') + '">' + validationStatus + '</span>' +
            '<a class="btn btn-ghost" style="margin-left:8px" href="/host/event?id=' +
            e.id +
            '">Open Event</a>' +
            "</li>"
        );
      }
      recentEventsList.innerHTML = html.join("");
    }

    function applyRecentFilter(trigger) {
      if (!hostSel || !venueSel) return;
      var hostName = getSelectedText(hostSel).toLowerCase();
      var venueName = getSelectedText(venueSel).toLowerCase();
      log("applyRecentFilter", {
        trigger: trigger || "?",
        hostName: hostName,
        venueName: venueName,
        total: allEvents.length,
      });
      var filtered = [];
      for (var i = 0; i < allEvents.length; i++) {
        var e = allEvents[i];
        var h = (e.host || "").toLowerCase();
        var v = (e.venue || "").toLowerCase();
        if ((hostName && h === hostName) || (venueName && v === venueName)) filtered.push(e);
      }
      renderRecent(filtered);
    }

    // show/hide the generate button when a venue is selected
    function updateLoadPhotosBtnVisibility() {
      if (!loadPhotosBtn || !venueSel) return;
      if (venueSel.value) loadPhotosBtn.style.display = 'inline-flex';
      else {
        loadPhotosBtn.style.display = 'none';
        if (recentPhotosSection) recentPhotosSection.style.display = 'none';
        if (photoZipLinkContainer) photoZipLinkContainer.innerHTML = '';
        const statusEl = getEl('photoZipStatus'); if (statusEl) GSP.clearStatus(statusEl);
      }
    }

    // ensure button visibility is correct at load
    updateLoadPhotosBtnVisibility();

    // download a zip pack by fetching the response as a blob and triggering a programmatic download
    async function downloadZipPack(urlPath, venueId, part, btnEl, statusEl) {
      if (btnEl) { btnEl.disabled = true; btnEl.textContent = 'Downloading…'; }
      if (statusEl) { statusEl.textContent = ''; }
      try {
      const fullUrl = (String(urlPath || '').startsWith('http') ? urlPath : CONFIG.API_BASE_URL + urlPath);
      const headers = {};
      if (CONFIG.TOKEN) headers['X-GSP-Token'] = CONFIG.TOKEN;
      const res = await fetch(fullUrl, { method: 'GET', headers: headers });
      if (!res.ok) {
        const txt = await res.text().catch(() => res.statusText || 'Failed');
        throw new Error(txt || 'Network error');
      }
      const blob = await res.blob();
      const filename = `venue_${venueId}_photos_part${part}.zip`;
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      if (statusEl) statusEl.textContent = 'Downloaded';
      return true;
      } catch (err) {
      if (statusEl) statusEl.textContent = 'Error: ' + (err.message || 'download failed');
      console.error('downloadZipPack error', err);
      return Promise.reject(err);
      } finally {
      if (btnEl) { btnEl.disabled = false; btnEl.textContent = 'Download'; }
      }
    }

    // main handler: request pack list and open modal with per-pack download buttons
    loadPhotosBtn.addEventListener('click', async (ev) => {
      if (ev && ev.preventDefault) ev.preventDefault();
      const venueId = venueSel.value;
      if (!venueId) {
        status(getEl('photoZipStatus'), 'error', 'Select a venue first.');
        return;
      }

      const statusEl = getEl('photoZipStatus');
      status(statusEl, 'info', 'Generating zip packs...');

      // Make modal visible immediately so users get immediate feedback
      // while we fetch pack data (prevents "nothing happened" UX).
      const modal = getEl('photoZipModal');
      const packsContainer = getEl('photoZipModalPacks');
      const modalStatus = getEl('photoZipModalStatus');
      const downloadAllBtn = getEl('downloadAllPacksBtn');
      if (packsContainer) packsContainer.innerHTML = '';
      if (modal) modal.style.display = 'flex';
      if (recentPhotosSection) recentPhotosSection.style.display = 'block';
      if (modalStatus) status(modalStatus, 'info', 'Loading zip packs...');

      try {
        const res = await j(CONFIG.API_BASE_URL + `/venues/${venueId}/recent-photos-zip`);
        if (!res || !res.packs || !res.packs.length) {
          // Show explicit message in the modal as well so the user sees
          // something even if the top-level status is hidden.
          status(statusEl, 'error', 'No recent photos available for this venue.');
          if (modalStatus) status(modalStatus, 'error', 'No recent photos available for this venue.');
          return;
        }

        // populate the modal
        const modal = getEl('photoZipModal');
        const packsContainer = getEl('photoZipModalPacks');
        const modalStatus = getEl('photoZipModalStatus');
        const downloadAllBtn = getEl('downloadAllPacksBtn');
        packsContainer.innerHTML = '';

        var per = res.per_page || 12;
        var total = res.total || 0;

        // Only show the most recent 4 packs (48 photos) to avoid sending
        // users extremely large downloads and to keep the UI snappy.
        var MAX_PACKS_TO_SHOW = 4;
        var packsToShow = res.packs.slice(0, Math.min(res.packs.length, MAX_PACKS_TO_SHOW));

        if (res.packs.length > packsToShow.length && modalStatus) {
          status(modalStatus, 'info', `Showing most recent ${packsToShow.length * (res.per_page || 12)} photos. Use API or server tools to fetch older photos.`);
        }

        packsToShow.forEach(function(p) {
          var part = p.part || 1;
          var start = (part - 1) * per + 1;
          var end = Math.min(total, part * per);

          var row = document.createElement('div');
          row.style.display = 'flex';
          row.style.justifyContent = 'space-between';
          row.style.alignItems = 'center';
          row.style.gap = '10px';

          var title = document.createElement('div');
          title.textContent = `Photos ${start}-${end}`;

          var controls = document.createElement('div');

          // show small thumbnails for the pack (if server returned photo urls)
          if (p.photos && p.photos.length) {
            var thumbs = document.createElement('div');
            thumbs.style.display = 'flex';
            thumbs.style.gap = '6px';
            thumbs.style.alignItems = 'center';
            thumbs.style.marginRight = '12px';
            // limit preview count to 6 thumbnails to avoid overloading UI
            var preview = p.photos.slice(0, 6);
            preview.forEach(function (url) {
              var img = document.createElement('img');
              img.src = url;
              img.alt = 'photo';
              img.loading = 'lazy';
              img.style.width = '56px';
              img.style.height = '56px';
              img.style.objectFit = 'cover';
              img.style.borderRadius = '6px';
              img.style.border = '1px solid rgba(255,255,255,0.06)';
              thumbs.appendChild(img);
            });
            // controls isn't appended yet, so don't use insertBefore with it
            // (insertBefore requires the reference node to already be a child).
            // Append thumbnails first, then title and controls below.
            row.appendChild(thumbs);
          }

          var packStatus = document.createElement('span');
          packStatus.style.marginRight = '8px';
          // expose a named class so the "Download All" flow can update
          // the per-pack status element when running sequential downloads
          packStatus.className = 'small-text pack-status-' + part;

          var dl = document.createElement('button');
          dl.className = 'btn btn-primary';
          dl.textContent = 'Download';
          dl.type = 'button';

          // Use JS fetch + blob -> createObjectURL to force download in-page
          dl.addEventListener('click', async function (ev) {
            ev && ev.preventDefault && ev.preventDefault();
            if (packStatus) packStatus.textContent = 'Downloading...';
            try {
              var downloadPath = p && p.url ? p.url : `/venues/${venueId}/recent-photos-zip?part=${part}`;
              await downloadZipPack(downloadPath, venueId, part, dl, packStatus);
            } catch (er) {
              console.error('pack download failed', er);
            }
          });

          controls.appendChild(packStatus);
          controls.appendChild(dl);
          row.appendChild(title);
          row.appendChild(controls);
          packsContainer.appendChild(row);
        });



        // Modal is already opened earlier; clear any loading status
        if (modalStatus) GSP.clearStatus(modalStatus);
        status(statusEl, 'success', 'Zips ready — choose a pack to download.');
      } catch (error) {
        // Surface the error in both the small status and in the modal
        status(statusEl, 'error', `Error: ${error.message}`);
        const modalStatusEl = getEl('photoZipModalStatus');
        if (modalStatusEl) status(modalStatusEl, 'error', `Error: ${error.message}`);
      }
    });

    function initForm() {
      if (!hostSel || !venueSel || !eventDate) {
        log("Core elements not found; skipping initForm.");
        return;
      }

      Promise.all([
        j(CONFIG.API_BASE_URL + "/hosts"),
        j(CONFIG.API_BASE_URL + "/venues"),
        j(CONFIG.API_BASE_URL + "/events?status=unposted"),
        j(CONFIG.API_BASE_URL + "/adjectives"),
      ])
        .then(function (res) {
          var hosts = res[0] || [];
          var venues = res[1] || [];
          var events = res[2] || [];
      
          var adjData = res[3] || { adjectives: [], random: null };

          var priorHost = hostSel && hostSel.value ? String(hostSel.value) : "";
          var priorVenue = venueSel && venueSel.value ? String(venueSel.value) : "";
          var priorShowType = showTypeSel && showTypeSel.value ? String(showTypeSel.value) : "gsp";

          hostSel.innerHTML = '<option value="">Select Host (required)</option>' + hosts.map(h => `<option value="${h.id}">${h.name}</option>`).join("");
          
          // Auto-select host if display_name matches a host name (only if no prior selection)
          if (priorHost) {
            hostSel.value = priorHost;
          } else if (GSPAuth.currentUser && GSPAuth.currentUser.display_name) {
            var matchingHost = hosts.find(h => 
              h.name.toLowerCase() === GSPAuth.currentUser.display_name.toLowerCase()
            );
            if (matchingHost) {
              hostSel.value = matchingHost.id;
              log('Auto-selected host:', matchingHost.name, 'for user:', GSPAuth.currentUser.display_name);
            } else {
              log('No matching host found for display name:', GSPAuth.currentUser.display_name);
            }
          }

          venueSel.innerHTML = '<option value="">Select Venue (required)</option>' + venues.map(v => `<option value="${v.id}">${v.name}</option>`).join("");
          if (priorVenue) venueSel.value = priorVenue;
          
          if (showTypeSel) showTypeSel.value = priorShowType;

          if (adjectiveSel) {
            adjectiveSel.innerHTML = ['<option value="">Random</option>'].concat(
              (adjData.adjectives || []).map(a => `<option value="${a}">${capitalize(a)}</option>`)
            ).join("");
          }

          allVenues = venues;
          allEvents = events;

          log("init loaded", { hosts: hosts.length, venues: venues.length, events: events.length, adjectives: (adjData.adjectives || []).length });
          applySmartDate("initForm");
          applyRecentFilter("initForm");
        })
        .catch(function (e) {
          status(uploadStatusDiv, "error", "Failed to load lists: " + e.message);
          console.error(e);
        });
    }

    if (hostSel) hostSel.addEventListener("change", function () { applyRecentFilter("host change"); });
    if (venueSel) venueSel.addEventListener("change", function () { 
      updateLoadPhotosBtnVisibility(); 
      applySmartDate("venue change"); 
      applyRecentFilter("venue change"); 
      // Auto-populate show type based on venue's show_type
      if (showTypeSel) {
        var venueId = venueSel.value;
        var venue = allVenues.find(v => String(v.id) === String(venueId));
        if (venue && venue.show_type) {
          // Normalize to lowercase to match dropdown values
          var normalizedType = (venue.show_type || 'gsp').toLowerCase();
          showTypeSel.value = normalizedType;
          log("Auto-set show_type to:", normalizedType, "(from venue.show_type:", venue.show_type + ")");
        } else {
          // Default to gsp if no show_type
          showTypeSel.value = 'gsp';
        }
      }
    });

    if (submitButton) {
      submitButton.addEventListener("click", async function (evt) {
        evt.preventDefault();
        submitButton.disabled = true;
        status(uploadStatusDiv, null, "Saving…");

        try {
          var hostId = hostSel ? hostSel.value : "";
          var venueId = venueSel ? venueSel.value : "";
          var ymd = eventDate ? eventDate.value : "";
          var notes = highlights ? (highlights.value || "").trim() : "";
          var adjective = adjectiveSel ? (adjectiveSel.value || "") : "";
          var showType = showTypeSel ? showTypeSel.value : "gsp";

          if (!hostId || !venueId || !ymd) {
            throw new Error("Host, venue, and date are required.");
          }

          var pdfUrl = null;
          var photoUrls = [];

          if (pdfFileInput && pdfFileInput.files && pdfFileInput.files[0]) {
            var pf = pdfFileInput.files[0];
            if (pf.size > 30 * 1024 * 1024) throw new Error("PDF too large (>30MB).");
            var fd = new FormData();
            fd.append("file", pf, pf.name || "recap.pdf");
            updateFileStatus(pf.name || "recap.pdf", "pending", "Uploading...");
            var res = await j(CONFIG.API_BASE_URL + "/generate-upload-url", { method: "POST", body: fd });
            pdfUrl = res.publicUrl;
            updateFileStatus(pf.name || "recap.pdf", "success", "PDF Uploaded!");
          }

          if (photoFilesInput && photoFilesInput.files && photoFilesInput.files.length) {
            if (fileListUL) { fileListUL.innerHTML = ""; fileListUL.style.display = "block"; }
            var files = Array.prototype.slice.call(photoFilesInput.files);
            makeSegments(files.length);

            for (var i = 0; i < files.length; i++) {
              var f0 = files[i];
              try {
                if (f0.size > 12 * 1024 * 1024) {
                  updateSegment(i, "error", "Too large");
                  updateFileStatus(f0.name, "error", "Too large");
                  continue;
                }
                updateSegment(i, "uploading");
                var fd2 = new FormData();
                var normalizedFile = await normalizeIosImage(f0);
                fd2.append("file", normalizedFile, normalizedFile.name || "photo.jpg");
                var res2 = await j(CONFIG.API_BASE_URL + "/generate-upload-url", { method: "POST", body: fd2 });
                photoUrls.push(res2.publicUrl);
                updateSegment(i, "success");
                updateFileStatus(f0.name, "success", "Uploaded!");
              } catch (errUp) {
                updateSegment(i, "error", "Upload failed");
                updateFileStatus(f0.name, "error", "Upload failed");
              }
            }
            hideSegments();
          }

          status(uploadStatusDiv, null, "Files processed. Creating event...");

          var body = {
            hostId: hostId,
            venueId: venueId,
            eventDate: ymd,
            highlights: notes,
            pdfUrl: pdfUrl,
            photoUrls: photoUrls,
            showType: showType
          };
          if (adjective) body.adjective = adjective;

          var js3 = await j(CONFIG.API_BASE_URL + "/create-event", {
            method: "POST",
            body: JSON.stringify(body)
          });
          status(uploadStatusDiv, "success", "Event saved. Open: " + js3.publicUrl);

          var evs = await j(CONFIG.API_BASE_URL + "/events?status=unposted");
          allEvents = evs || [];
          applyRecentFilter("after save");
        } catch (err) {
          status(uploadStatusDiv, "error", err.message || "Failed to save event.");
        } finally {
          submitButton.disabled = false;
        }
      });
    }

    if (resetButton) {
      resetButton.addEventListener("click", function () {
        if (eventDate) eventDate.value = "";
        if (highlights) highlights.value = "";
        // Reset host/venue selections to placeholder
        if (hostSel) hostSel.value = "";
        if (venueSel) venueSel.value = "";
        if (pdfFileInput) pdfFileInput.value = "";
        if (photoFilesInput) photoFilesInput.value = "";
        // Update visible filename text
        if (pdfRecapNameEl) pdfRecapNameEl.textContent = 'No file selected';
        if (photosNameEl) photosNameEl.textContent = 'No files selected';
        if (showTypeSel) showTypeSel.value = "gsp";
        clearStatus(uploadStatusDiv);
        if (fileListUL) { fileListUL.innerHTML = ""; fileListUL.style.display = "none"; }
        hideSegments();
      });
    }

    // Show the chosen PDF filename when user selects a file
    if (pdfFileInput) {
      pdfFileInput.addEventListener('change', function () {
        try {
          if (pdfRecapNameEl) {
            if (pdfFileInput.files && pdfFileInput.files.length) {
              pdfRecapNameEl.textContent = pdfFileInput.files[0].name || '1 file selected';
            } else {
              pdfRecapNameEl.textContent = 'No file selected';
            }
          }
        } catch (e) { console.warn('[hosts] failed to update pdfRecapName', e); }
      });
    }

    // Update photos display when multiple files are selected
    if (photoFilesInput) {
      photoFilesInput.addEventListener('change', function () {
        try {
          if (!photosNameEl) return;
          var files = photoFilesInput.files || [];
          if (!files.length) {
            photosNameEl.textContent = 'No files selected';
          } else if (files.length === 1) {
            photosNameEl.textContent = files[0].name || '1 file selected';
          } else {
            photosNameEl.textContent = files.length + ' files selected';
          }
        } catch (e) { console.warn('[hosts] failed to update photosName', e); }
      });
    }

      // modal close behaviour (wired here so DOM refs are available)
      const photoZipModal = getEl('photoZipModal');
      const closeModalBtn = getEl('closePhotoZipModalBtn');
      const closeModalFooterBtn = getEl('closePhotoZipModalFooterBtn');
      const photoZipModalPacks = getEl('photoZipModalPacks');
      const photoZipModalStatus = getEl('photoZipModalStatus');

      function closePhotoModal() {
        if (photoZipModal) photoZipModal.style.display = 'none';
  });
  
  // Wrapper to ensure initForm is defined before calling it
  function initFormWhenReady() {
    if (typeof initForm === 'function') {
      initForm();
    }
  } }

      // Attach the close handler only to an enabled control.
      if (closeModalBtn && !closeModalBtn.disabled) closeModalBtn.addEventListener('click', closePhotoModal);
      if (closeModalFooterBtn) closeModalFooterBtn.addEventListener('click', closePhotoModal);

      initForm();
  });
})();