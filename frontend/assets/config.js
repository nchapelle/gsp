window.CONFIG = {
  API_BASE_URL: "https://api.gspevents.com",
  TOKEN: (function() { try { return new URL(window.location.href).searchParams.get("t"); } catch { return null; }})(),
  j: async function j(u,o={}) {
    o.headers = Object.assign({}, o.headers || {});
    if (o.body && typeof o.body === "string" && !o.headers["Content-Type"]) {
      o.headers["Content-Type"] = "application/json";
    }
    if (window.CONFIG && window.CONFIG.TOKEN) {
      o.headers["X-GSP-Token"] = window.CONFIG.TOKEN;
    }
    const r = await fetch(u, o);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }
};