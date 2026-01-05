/* assets/auth.js - Shared authentication component for GSP Events */
/* global CONFIG, firebase */

(function() {
  'use strict';

  // GSP Auth Manager - handles user authentication and role-based access
  window.GSPAuth = {
    currentUser: null,
    
    /**
     * Initialize auth system and set up listeners
     * @param {Object} options - Configuration options
     * @param {string[]} options.requiredRoles - Roles allowed to access this page (admin, host, smm)
     * @param {function} options.onAuthReady - Callback when auth state is determined
     * @param {boolean} options.requireAuth - Whether this page requires authentication (default: true)
     */
    init: function(options = {}) {
      const opts = {
        requiredRoles: options.requiredRoles || null,
        onAuthReady: options.onAuthReady || null,
        requireAuth: options.requireAuth !== false
      };
      
      if (typeof firebase === 'undefined' || !firebase.auth) {
        console.error('[GSP Auth] Firebase not loaded');
        if (opts.requireAuth) {
          this.showAuthError('Firebase authentication not available');
        }
        return;
      }
      
      // Handle redirect result first (required for signInWithRedirect to work)
      firebase.auth().getRedirectResult()
        .then((result) => {
          console.log('[GSP Auth] Redirect result:', result);
          if (result.user) {
            console.log('[GSP Auth] Redirect sign-in successful:', result.user.email);
          } else if (result.credential) {
            console.log('[GSP Auth] Redirect had credential but no user:', result.credential);
          } else {
            console.log('[GSP Auth] No redirect result (normal page load or redirect not completed)');
          }
        })
        .catch((error) => {
          console.error('[GSP Auth] Redirect error:', error);
          if (error.code && error.code !== 'auth/popup-blocked') {
            alert('Sign in failed: ' + error.message);
          }
        });
      
      // Set up auth state listener
      firebase.auth().onAuthStateChanged(async (firebaseUser) => {
        console.log('[GSP Auth] Auth state changed. User:', firebaseUser ? firebaseUser.email : 'null');
        
        // Show loading state
        this.showLoadingState();
        
        if (firebaseUser) {
          // User is signed in, fetch their profile from backend
          try {
            console.log('[GSP Auth] Fetching user profile for:', firebaseUser.email);
            const response = await CONFIG.j(`${CONFIG.API_BASE_URL}/api/user/me`);
            console.log('[GSP Auth] User profile loaded:', response);
            this.currentUser = {
              ...response,
              firebaseUser: firebaseUser
            };
            
            // Check if user has required role
            if (opts.requiredRoles && !opts.requiredRoles.includes(this.currentUser.role)) {
              console.warn('[GSP Auth] Access denied - user role:', this.currentUser.role, 'required:', opts.requiredRoles);
              this.showAccessDenied(this.currentUser.role, opts.requiredRoles);
              return;
            }
            
            // Update UI
            this.renderAuthUI(this.currentUser);
            
            // Call ready callback
            if (opts.onAuthReady) {
              console.log('[GSP Auth] Calling onAuthReady with user:', this.currentUser.email);
              opts.onAuthReady(this.currentUser);
            }
            
          } catch (e) {
            console.error('[GSP Auth] Failed to fetch user profile:', e);
            console.error('[GSP Auth] Error details:', e.message, e.stack);
            await firebase.auth().signOut();
            this.showAuthError('Failed to load user profile. Please sign in again.');
          }
          
        } else {
          // User is signed out
          console.log('[GSP Auth] User is signed out');
          this.currentUser = null;
          
          if (opts.requireAuth) {
            console.log('[GSP Auth] Auth required, showing sign in UI');
            this.showSignInUI();
          } else {
            console.log('[GSP Auth] Auth not required, calling onAuthReady with null');
            this.renderAuthUI(null);
            if (opts.onAuthReady) {
              opts.onAuthReady(null);
            }
          }
        }
      });
    },
    
    /**
     * Sign in with Google - uses popup for most browsers, redirect for Safari
     */
    signInWithGoogle: async function() {
      try {
        const provider = new firebase.auth.GoogleAuthProvider();
        
        // Detect Safari (which has issues with popups)
        const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
        
        if (isSafari) {
          console.log('[GSP Auth] Using redirect method for Safari');
          await firebase.auth().signInWithRedirect(provider);
        } else {
          console.log('[GSP Auth] Using popup method');
          await firebase.auth().signInWithPopup(provider);
        }
      } catch (error) {
        console.error('[GSP Auth] Sign in failed:', error);
        alert('Sign in failed: ' + error.message);
      }
    },
    
    /**
     * Sign out
     */
    signOut: async function() {
      try {
        await firebase.auth().signOut();
        this.currentUser = null;
      } catch (error) {
        console.error('[GSP Auth] Sign out failed:', error);
      }
    },
    
    /**
     * Render auth UI (sign in button or user profile)
     */
    renderAuthUI: function(user) {
      const authContainer = document.getElementById('gspAuthContainer');
      if (!authContainer) return;
      
      if (user) {
        // Show user profile
        authContainer.innerHTML = `
          <div class="gsp-auth-profile">
            <span class="gsp-auth-email">${this.escapeHtml(user.email)}</span>
            <span class="gsp-auth-role badge-${user.role}">${user.role.toUpperCase()}</span>
            <button id="gspSignOutBtn" class="button-secondary">Sign Out</button>
          </div>
        `;
        
        document.getElementById('gspSignOutBtn').addEventListener('click', () => {
          this.signOut();
        });
        
        // Show protected content
        const protectedContent = document.querySelectorAll('.gsp-protected-content');
        protectedContent.forEach(el => el.style.display = '');
        
      } else {
        // Show sign in button
        authContainer.innerHTML = `
          <div class="gsp-auth-signin">
            <p>Please sign in to continue</p>
            <button id="gspSignInBtn" class="button">
              <svg width="18" height="18" style="vertical-align: middle; margin-right: 8px;">
                <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z"/>
                <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332C2.438 15.983 5.482 18 9 18z"/>
                <path fill="#FBBC05" d="M3.964 10.71c-.18-.54-.282-1.117-.282-1.71s.102-1.17.282-1.71V4.958H.957C.347 6.173 0 7.548 0 9s.348 2.827.957 4.042l3.007-2.332z"/>
                <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0 5.482 0 2.438 2.017.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"/>
              </svg>
              Sign in with Google
            </button>
          </div>
        `;
        
        document.getElementById('gspSignInBtn').addEventListener('click', () => {
          this.signInWithGoogle();
        });
        
        // Hide protected content
        const protectedContent = document.querySelectorAll('.gsp-protected-content');
        protectedContent.forEach(el => el.style.display = 'none');
      }
    },
    
    /**
     * Show sign-in UI for protected pages
     */
    showSignInUI: function() {
      const body = document.body;
      body.innerHTML = `
        <div style="max-width: 500px; margin: 100px auto; padding: 40px; text-align: center; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
          <h1 style="color: #333; margin-bottom: 20px;">GSP Events</h1>
          <p style="color: #666; margin-bottom: 30px;">Sign in to access this page</p>
          <div id="gspAuthContainer"></div>
        </div>
      `;
      this.renderAuthUI(null);
    },
    
    /**
     * Show access denied message when user lacks required role
     */
    showAccessDenied: function(userRole, requiredRoles) {
      const body = document.body;
      body.innerHTML = `
        <div style="max-width: 600px; margin: 100px auto; padding: 40px; text-align: center; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
          <h1 style="color: #d32f2f; margin-bottom: 20px;">Access Denied</h1>
          <p style="color: #666; font-size: 16px; margin-bottom: 20px;">
            Your account role (<strong>${userRole}</strong>) does not have permission to access this page.
          </p>
          <p style="color: #999; font-size: 14px; margin-bottom: 30px;">
            Required role(s): ${requiredRoles.join(', ')}
          </p>
          <button onclick="GSPAuth.signOut()" class="button-secondary" style="padding: 12px 24px; background: #666; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px;">
            Sign Out
          </button>
          <br><br>
          <a href="/" style="color: #1976d2; text-decoration: none;">← Back to Home</a>
        </div>
      `;
    },
    
    /**
     * Show authentication error
     */
    showAuthError: function(message) {
      const authContainer = document.getElementById('gspAuthContainer');
      if (authContainer) {
        authContainer.innerHTML = `
          <div style="color: #d32f2f; padding: 15px; background: #ffebee; border-radius: 4px; margin: 20px 0;">
            ${this.escapeHtml(message)}
          </div>
        `;
      }
    },
    
    /**
     * Show loading state during authentication
     */
    showLoadingState: function() {
      const authContainer = document.getElementById('gspAuthContainer');
      if (authContainer && !authContainer.querySelector('.gsp-auth-loading')) {
        authContainer.innerHTML = `
          <div class="gsp-auth-loading">
            <div class="spinner"></div>
          </div>
        `;
      }
      
      // Also show loading on protected content
      const protectedContent = document.querySelectorAll('.gsp-protected-content');
      protectedContent.forEach(el => el.style.display = 'none');
    },
    
    /**
     * Check if current user has specified role(s)
     * @param {string|string[]} roles - Role(s) to check
     * @returns {boolean}
     */
    hasRole: function(roles) {
      if (!this.currentUser) return false;
      const roleArray = Array.isArray(roles) ? roles : [roles];
      return roleArray.includes(this.currentUser.role);
    },
    
    /**
     * Show/hide elements based on user role
     */
    applyRoleVisibility: function() {
      // Show elements for specific roles
      document.querySelectorAll('[data-role]').forEach(el => {
        const requiredRoles = el.dataset.role.split(',').map(r => r.trim());
        el.style.display = this.hasRole(requiredRoles) ? '' : 'none';
      });
      
      // Hide elements from specific roles
      document.querySelectorAll('[data-hide-role]').forEach(el => {
        const hiddenRoles = el.dataset.hideRole.split(',').map(r => r.trim());
        el.style.display = this.hasRole(hiddenRoles) ? 'none' : '';
      });
    },
    
    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml: function(text) {
      const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
      };
      return text.replace(/[&<>"']/g, m => map[m]);
    }
  };
  
  // Auto-initialize auth container if present
  document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('gspAuthContainer') && !window.GSPAuth.currentUser) {
      console.log('[GSP Auth] Auth container found, waiting for manual init');
    }
  });
  
})();
