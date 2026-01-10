// assets/main.js
// Global helpers + page router for Hosts, SMM, and Admin modules

(function () {
  // ---------- Global status helper ----------
  function status(el, type, msg) {
    if (!el) return;
    el.classList.remove("success", "error"); // Clear existing status classes
    el.classList.remove("info"); // Clear any info class
    el.style.display = "block";
    el.textContent = msg || "";
    if (type) el.classList.add(type);
    else el.classList.add('info'); // Default to info if no type specified
  }

  // ---------- ET date helpers ----------
  function nowInET() {
    return new Date(new Date().toLocaleString("en-US", {timeZone: "America/New_York"}));
  }

  /**
   * Robust date formatter for America/New_York
   * Prevents UTC "off-by-one" day shifts.
   */
  function formatDateET(dateInput, format) {
    if (!dateInput) return "—";
    var d = (typeof dateInput === 'string') ? new Date(dateInput.includes('T') ? dateInput : dateInput + 'T00:00:00') : new Date(dateInput);
    if (isNaN(d.getTime())) return "—";
    
    // Default to MM/DD/YYYY in ET
    var options = { timeZone: "America/New_York" };
    if (format === 'long') {
      options.month = 'long'; options.day = 'numeric'; options.year = 'numeric';
    } else if (format === 'full') {
      options.weekday = 'long'; options.month = 'long'; options.day = 'numeric'; options.year = 'numeric';
    } else {
      options.month = '2-digit'; options.day = '2-digit'; options.year = 'numeric';
    }
    
    return d.toLocaleDateString("en-US", options);
  }

  function formatDateTimeET(dateInput) {
    if (!dateInput) return "—";
    var d = new Date(dateInput);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleString("en-US", { timeZone: "America/New_York" });
  }

  var dayToIndex = {
    Sunday: 0,
    Monday: 1,
    Tuesday: 2,
    Wednesday: 3,
    Thursday: 4,
    Friday: 5,
    Saturday: 6,
  };
  
  function mostRecentDayET(target) {
      var d = nowInET();
      var targetDayIndex = dayToIndex[target];
      var currentDayIndex = d.getDay();

      var diff;
      if (currentDayIndex >= targetDayIndex) {
        diff = currentDayIndex - targetDayIndex;
      } else {
        diff = (currentDayIndex - targetDayIndex + 7);
      }
      
      d.setDate(d.getDate() - diff);
      var y = d.getFullYear();
      var m = String(d.getMonth() + 1).padStart(2, "0");
      var day = String(d.getDate()).padStart(2, "0");
      return y + "-" + m + "-" + day;
  }

  // ---------- GLOBAL HELPERS EXPOSED VIA GSP (CRITICAL FIX) ----------
  function getEl(id) {
    return document.getElementById(id);
  }

  window.GSP = {
    status: status,
    clearStatus: function(el) {
        if (el) {
            el.classList.remove("success", "error", "info");
            el.style.display = "none";
            el.textContent = "";
        }
    },
    dayToIndex: dayToIndex,
    mostRecentDayET: mostRecentDayET,
    formatDateET: formatDateET,
    formatDateTimeET: formatDateTimeET,
    // EXPOSE CONFIG.j AND getEl GLOBALLY THROUGH GSP FOR ALL MODULES
    j: CONFIG.j, // Use CONFIG.j directly
    getEl: getEl // Expose the getEl helper
  };

  // ---------- Page Router ----------
function boot() {
  var path = location.pathname;

  // Hosts
  if (path === "/hosts" || path.endsWith("/hosts.html")) {
    // hosts.js self-initializes
  } else if (path === "/host/event" || path.endsWith("/host-event.html")) {
    // host-event.js self-initializes

  // SMM
  } else if (path === "/smm" || path.endsWith("/smm.html")) {
    // smm.js self-initializes
  } else if (path === "/smm/event" || path.endsWith("/smm-event.html")) {
    if (window.SMMEvent && typeof window.SMMEvent.init === "function") {
      window.SMMEvent.init({ getEl: GSP.getEl });
    }

  // Admin pages (Auth handled by module self-initialization)
  } else if (path === "/admin" || path.endsWith("/admin.html")) {
    if (window.AdminPages && typeof window.AdminPages.initAdminList === "function") {
      window.AdminPages.initAdminList({ getEl: GSP.getEl });
    }
  } else if (path === "/admin/event" || path.endsWith("/admin-event.html")) {
    if (window.AdminPages && typeof window.AdminPages.initAdminEvent === "function") {
      window.AdminPages.initAdminEvent({ getEl: GSP.getEl });
    }
  } else if (path === "/admin/data" || path.endsWith("/admin-data.html")) {
    if (window.AdminData && typeof window.AdminData.init === "function") {
      window.AdminData.init({ getEl: GSP.getEl });
    }

  // Tournament admin/teams
  } else if (path === "/tournament/admin" || path.endsWith("/tournament-admin.html")) {
    // Assuming tournament-admin.js will expose an init, if not, it self-initializes
    if (window.TournamentAdmin && typeof window.TournamentAdmin.init === 'function') {
        window.TournamentAdmin.init({ getEl: GSP.getEl });
    }
  } else if (path === "/tournament/teams" || path.endsWith("/tournament-teams.html")) {
    // Assuming tournament-teams.js will expose an init
    if (window.TournamentTeams && typeof window.TournamentTeams.init === 'function') {
        window.TournamentTeams.init({ getEl: GSP.getEl });
    }

  // NEW: Tournament Public Pages (explicit init)
  } else if (path === "/tournament/standings" || path.endsWith("/tournament-standings.html")) {
    if (window.TournamentStandings && typeof window.TournamentStandings.init === "function") {
      window.TournamentStandings.init({ getEl: GSP.getEl });
    }
  } else if (path === "/team/portal" || path.endsWith("/team-captain-portal.html")) {
    if (window.TeamCaptainPortal && typeof window.TeamCaptainPortal.init === "function") {
      window.TeamCaptainPortal.init({ getEl: GSP.getEl });
    }
  }
}

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();