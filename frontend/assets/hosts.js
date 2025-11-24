/* assets/hosts.js */
/* global CONFIG, GSP */
(function () {
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
    var adjectiveSel = getEl("adjective");
    var showTypeSel = getEl("showType"); // Get reference to showType dropdown
    var submitButton = getEl("submitButton");
    var resetButton = getEl("resetButton");
    var uploadStatusDiv = getEl("uploadStatus");
    var recentEventsList = getEl("recentEventsList");
    var progressBarContainer = getEl("progressBarContainer");
    var progressBar = getEl("progressBar");
    var fileListUL = getEl("fileList");
    var venueSelect = getEl('venue-select');
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

    loadPhotosBtn.addEventListener('click', async () => {
        const venueId = venueSelect.value;
        if (!venueId) {
            GSP.status('error', 'Select a venue first.');
            return;
        }

        GSP.status('info', 'Generating zip...');
        try {
            const response = await GSP.j(`/venue/${venueId}/recent_photos_zip`, { method: 'GET' });
            const data = await response.json();

            photoZipLinkContainer.innerHTML = '';

            const zipLink = document.createElement('a');
            zipLink.href = data.zip_url;
            zipLink.textContent = 'Download Zip';
            zipLink.download = `venue_${venueId}_recent_photos.zip`;
            photoZipLinkContainer.appendChild(zipLink);

            recentPhotosSection.style.display = 'block';
            GSP.clearStatus();
            GSP.status('success', 'Zip ready for download.');
        } catch (error) {
            GSP.status('error', `Error: ${error.message}`);
        }
    });
    
    // venueSelect.addEventListener('change', () => {
    //     console.log('Venue changed to:', venueSelect.value);  // Debug
    //     if (venueSelect.value) {
    //         loadPhotosBtn.style.display = 'block';
    //     } else {
    //         loadPhotosBtn.style.display = 'none';
    //         recentPhotosSection.style.display = 'none';
    //     }
    // });

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

          hostSel.innerHTML = hosts.map(h => `<option value="${h.id}">${h.name}</option>`).join("");
          if (priorHost) hostSel.value = priorHost;

          venueSel.innerHTML = venues.map(v => `<option value="${v.id}">${v.name}</option>`).join("");
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
    if (venueSel) venueSel.addEventListener("change", function () { applySmartDate("venue change"); applyRecentFilter("venue change"); });

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
        if (pdfFileInput) pdfFileInput.value = "";
        if (photoFilesInput) photoFilesInput.value = "";
        if (showTypeSel) showTypeSel.value = "gsp";
        clearStatus(uploadStatusDiv);
        if (fileListUL) { fileListUL.innerHTML = ""; fileListUL.style.display = "none"; }
        hideSegments();
      });
    }

    initForm();
  });
})();