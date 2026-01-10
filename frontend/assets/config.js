// Firebase configuration - get these values from Firebase Console
// Project Settings > General > Your apps > Web app
const firebaseConfig = {
  apiKey: "AIzaSyAxPVa2rzSk_UdMrsxV0w6DX2gZ5Mat_dU",
  authDomain: "app.gspevents.com",
  projectId: "gsp-app-project"
};

// Initialize Firebase
if (typeof firebase !== 'undefined') {
  try {
    const app = firebase.initializeApp(firebaseConfig);
    console.log('[GSP Auth] Firebase initialized');
    
    // CRITICAL: Set persistence synchronously before any auth operations
    // This must complete before auth.js runs any auth state checks
    const auth = firebase.auth();
    
    // Set to LOCAL persistence (survives browser restarts)
    auth.setPersistence(firebase.auth.Auth.Persistence.LOCAL)
      .catch((error) => {
        console.error('[GSP Auth] Persistence setting failed:', error);
      });
    
  } catch (e) {
    console.error('[GSP Auth] Firebase init failed:', e);
  }
} else {
  console.warn('[GSP Auth] Firebase SDK not loaded');
}

window.CONFIG = {
  API_BASE_URL: "https://api.gspevents.com",
  
  // Legacy token support (until Feb 1, 2026) - for backwards compatibility
  TOKEN: (function() { 
    try { 
      return new URL(window.location.href).searchParams.get("t"); 
    } catch { 
      return null; 
    }
  })(),
  
  // Main fetch wrapper with automatic authentication
  j: async function j(u,o={}) {
    o.headers = Object.assign({}, o.headers || {});
    
    // Wait for Firebase auth to be ready
    if (typeof firebase !== 'undefined' && firebase.auth) {
      try {
        // Wait up to 5 seconds for auth to be ready
        let attempts = 0;
        while (attempts < 100) {
          const user = firebase.auth().currentUser;
          if (user) {
            const token = await user.getIdToken();
            o.headers["Authorization"] = `Bearer ${token}`;
            break;
          }
          await new Promise(resolve => setTimeout(resolve, 50));
          attempts++;
        }
      } catch (e) {
        console.warn('[CONFIG.j] Failed to get Firebase token:', e);
      }
    }
    
    // Fallback to legacy token during migration period
    if (!o.headers["Authorization"] && window.CONFIG && window.CONFIG.TOKEN) {
      o.headers["X-GSP-Token"] = window.CONFIG.TOKEN;
    }
    
    if (o.body && typeof o.body === "string" && !o.headers["Content-Type"]) {
      o.headers["Content-Type"] = "application/json";
    }
    
    const r = await fetch(u, o);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }
};