/* assets/host-event.js */
/* global CONFIG, GSPAuth */
(function () {
  // Initialize authentication - require host or admin role
  if (typeof GSPAuth !== 'undefined') {
    GSPAuth.init({
      requiredRoles: ['host', 'admin'],
      requireAuth: true,
      onAuthReady: function(user) {
        if (user) {
          console.log('[host-event] Auth ready, user:', user.email, 'role:', user.role);
          initPage();
        }
      }
    });
  } else {
    console.error('[host-event] GSPAuth not loaded');
    document.body.innerHTML = '<div style="padding: 40px; text-align: center;">Authentication system not available</div>';
  }

  function getEl(id) {
    return document.getElementById(id);
  }
  function status(el, type, msg) {
    if (!el) return;
    el.classList.remove("success", "error");
    el.style.display = "block";
    el.textContent = msg || "";
    if (type) el.classList.add(type);
  }
  function clearStatus(el) {
    if (!el) return;
    el.classList.remove("success", "error");
    el.style.display = "none";
    el.textContent = "";
  }
  function j(url, opts) {
    return CONFIG.j(url, opts || {});
  }

  // Optional HEIC→JPEG conversion (only if heic2any is loaded)
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
      console.warn("[host-event] heic2any conversion failed; using original", e);
      return file;
    }
  }

  // Segmented progress helpers
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
  function updateFileRow(idx, statusClass, message) {
    var row = document.getElementById("file-" + idx);
    if (!row) return;
    var badge = row.querySelector(".file-status");
    if (badge) {
      badge.className = "file-status " + (statusClass || "pending");
      badge.textContent = (statusClass || "pending").toUpperCase();
    }
    if (message) row.setAttribute("title", message);
  }

  function renderEvent(e, els) {
    var photos = Array.isArray(e.photos) ? e.photos : [];
    var hasPhotos = photos.length > 0;
    var dateStr = e.event_date ? new Date(e.event_date).toLocaleDateString() : "—";
    var photosHTML = hasPhotos
      ? '<div class="media-grid">' +
        photos.map(function (u) {
          return '<img src="' + u + '" alt="event photo" loading="lazy">';
        }).join("") +
        "</div>"
      : '<div class="p">No photos yet. Use the form below to upload more.</div>';
    if (els.details) {
      els.details.innerHTML =
        '<div class="p"><strong>Date:</strong> ' + dateStr + "</div>" +
        '<div class="p"><strong>Venue:</strong> ' + (e.venue || "—") + "</div>" +
        '<div class="p"><strong>Host:</strong> ' + (e.host || "—") + "</div>" +
        '<div class="section"><h2 class="h2">Current Photos</h2>' + photosHTML + "</div>";
    }
  }

  async function loadEvent(eventId, els) {
    try {
      var e = await j(CONFIG.API_BASE_URL + "/events/" + eventId);
      renderEvent(e, els);
      return e;
    } catch (err) {
      status(els.status, "error", "Failed to load event: " + err.message);
      throw err;
    }
  }

  function renderFileList(files, listEl) {
    if (!listEl) return;
    listEl.innerHTML = "";
    if (!files.length) {
      listEl.style.display = "none";
      return;
    }
    listEl.style.display = "block";
    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      var li = document.createElement("li");
      li.id = "file-" + f._id;
      li.innerHTML =
        "<span>" +
        (f.name || "photo") +
        "</span>" +
        '<span class="file-status ' +
        (f._status || "pending") +
        '">' +
        ((f._status || "pending").toUpperCase()) +
        "</span>";
      listEl.appendChild(li);
    }
  }

  // Upload the file bytes to the backend-proxied GCS endpoint; returns publicUrl
  async function uploadToBucket(file) {
    var fd = new FormData();
    fd.append("file", file, file.name || "photo.jpg");
    var res = await fetch(CONFIG.API_BASE_URL + "/generate-upload-url", {
      method: "POST",
      body: fd,
    });
    if (!res.ok) throw new Error(await res.text());
    var js = await res.json();
    if (!js.publicUrl) throw new Error("No publicUrl returned");
    return js.publicUrl;
  }

  // Link the already-uploaded image to the event (URL-only, no bytes)
  async function linkByUrl(eventId, url) {
    var res = await fetch(CONFIG.API_BASE_URL + "/events/" + eventId + "/add-photo-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ photoUrl: url }),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  function initPage() {
    var details = getEl("event-details-content");
    if (!details) return; // not this page

    var params = new URLSearchParams(location.search);
    var eventId = params.get("id");
    if (!eventId) return;

    var els = {
      details: details,
      form: getEl("addPhotosForm"),
      input: getEl("addPhotosInput"),
      fileList: getEl("fileList"),
      status: getEl("photoUploadStatus"),
      progressBar: getEl("progressBar"),
      progressBarContainer: getEl("progressBarContainer"),
    };

    // Inline filename feedback for the styled file control
    if (els.input) {
      var nameEl = document.getElementById('addPhotosInputName');
      els.input.addEventListener('change', function () {
        if (!nameEl) return;
        var f = this.files;
        if (!f || !f.length) nameEl.textContent = 'No files selected';
        else if (f.length === 1) nameEl.textContent = f[0].name || '1 file selected';
        else nameEl.textContent = f.length + ' files selected';
      });
    }

    loadEvent(eventId, els).catch(function () {});

    if (els.form) {
      els.form.addEventListener("submit", async function (ev) {
        ev.preventDefault();
        clearStatus(els.status);

        var files = Array.prototype.slice.call(
          els.input && els.input.files ? els.input.files : []
        );
        if (!files.length) {
          status(els.status, "error", "Please choose at least one photo.");
          return;
        }
        if (files.length > 50) {
          status(els.status, "error", "Max 50 photos per upload.");
          return;
        }

        var selected = files.map(function (f, i) {
          return Object.assign(f, { _id: i, _status: "pending" });
        });
        renderFileList(selected, els.fileList);

        // Segmented bar
        makeSegments(selected.length);
        if (els.progressBarContainer) els.progressBarContainer.style.display = "block";

        var done = 0;
        for (var i = 0; i < selected.length; i++) {
          var f0 = selected[i];
          try {
            // Early validation
            if (f0 && f0.name && /\.pdf$/i.test(f0.name)) {
              selected[i]._status = "error";
              updateSegment(i, "error", "Bad file: PDF not allowed here");
              updateFileRow(i, "error", "Bad file");
              continue;
            }
            if (f0.size > 12 * 1024 * 1024) {
              selected[i]._status = "error";
              updateSegment(i, "error", "File size too big (>12MB)");
              updateFileRow(i, "error", "Too large");
              continue;
            }

            updateSegment(i, "uploading");

            var f = await normalizeIosImage(f0);
            // Step 1: upload bytes to bucket
            var publicUrl = await uploadToBucket(f);

            // Step 2: link to event by URL
            await linkByUrl(eventId, publicUrl);

            selected[i]._status = "success";
            updateSegment(i, "success");
            updateFileRow(i, "success", "Uploaded!");
            done++;
          } catch (e) {
            selected[i]._status = "error";
            var msg = (e && e.message) ? e.message : "Upload failed";
            if (/No file/.test(msg)) msg = "Upload lost: retry";
            if (/Invalid image payload/.test(msg)) msg = "Invalid image";
            updateSegment(i, "error", msg);
            updateFileRow(i, "error", "Failed");
          }

          // Optional continuous bar if you keep it
          if (els.progressBar) {
            var pct = Math.round(((i + 1) / selected.length) * 100);
            els.progressBar.style.width = pct + "%";
            els.progressBar.textContent = pct + "%";
          }
        }

        hideSegments();
        if (els.progressBarContainer) els.progressBarContainer.style.display = "none";
        if (els.progressBar) {
          els.progressBar.style.width = "0%";
          els.progressBar.textContent = "";
        }

        if (done === selected.length) {
          status(els.status, "success", "Uploaded " + done + " photo(s).");
        } else if (done > 0) {
          status(
            els.status,
            "error",
            "Uploaded " + done + "/" + selected.length + ". Some failed."
          );
        } else {
          status(els.status, "error", "Upload failed.");
        }

        // Refresh event view to show newly linked photos
        loadEvent(eventId, els).catch(function () {});
      });
    }
  }
})();