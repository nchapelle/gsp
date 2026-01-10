// assets/public-events.js
/**
 * Public Events Module
 * Handles fetching and displaying GSP events for public-facing pages
 * Designed for Squarespace and www.gspevents.com integration
 */

(function(window) {
  'use strict';

  const API_BASE_URL = 'https://api.gspevents.com';
  const CACHE_DURATION = 5 * 60 * 1000; // 5 minutes
  let eventCache = null;
  let cacheTimestamp = 0;

  /**
   * Fetch all posted events from the public endpoint
   * Uses local caching to reduce API calls
   */
  async function fetchEvents(useCache = true) {
    const now = Date.now();
    
    if (useCache && eventCache && (now - cacheTimestamp) < CACHE_DURATION) {
      return Promise.resolve(eventCache);
    }

    try {
      const response = await fetch(`${API_BASE_URL}/public/events`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      eventCache = await response.json();
      cacheTimestamp = now;
      return eventCache;
    } catch (error) {
      console.error('Failed to fetch events:', error);
      throw error;
    }
  }

  /**
   * Get a single event by ID
   */
  async function getEvent(eventId) {
    const events = await fetchEvents();
    return events.find(e => e.id === eventId);
  }

  /**
   * Get recent events (last N events)
   */
  async function getRecentEvents(count = 5) {
    const events = await fetchEvents();
    return events.slice(0, count);
  }

  /**
   * Get events by venue name
   */
  async function getEventsByVenue(venueName) {
    const events = await fetchEvents();
    return events.filter(e => e.venue && e.venue.toLowerCase().includes(venueName.toLowerCase()));
  }

  /**
   * Format date for display
   */
  function formatDate(dateString) {
    if (!dateString) return 'TBA';
    return GSP.formatDateET(dateString, 'long');
  }

  /**
   * Sanitize HTML to prevent XSS
   */
  function escapeHtml(text) {
    if (!text) return '';
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
  }

  /**
   * Generate a blog post HTML snippet for a single event
   * Useful for embedding in Squarespace or other platforms
   */
  function generateBlogPost(event) {
    if (!event) return '';

    const photosHtml = event.photos && event.photos.length > 0
      ? `<div class="gsp-event-photos" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 20px 0;">
           ${event.photos.map(url => 
             `<img src="${escapeHtml(url)}" alt="Event photo" style="width: 100%; height: 200px; object-fit: cover; border-radius: 6px;" />`
           ).join('')}
         </div>`
      : '';

    const recapHtml = event.ai_recap
      ? `<div class="gsp-event-recap" style="background: #f5f5f5; padding: 15px; border-radius: 6px; margin: 15px 0;">
           <h3 style="margin-bottom: 10px;">Event Recap</h3>
           <p style="margin: 0;">${escapeHtml(event.ai_recap)}</p>
         </div>`
      : '';

    const highlightsHtml = event.highlights
      ? `<div class="gsp-event-highlights" style="margin: 15px 0;">
           <h3 style="margin-bottom: 10px;">Highlights</h3>
           <p style="margin: 0;">${escapeHtml(event.highlights)}</p>
         </div>`
      : '';

    const fbLink = event.fb_event_url
      ? `<a href="${escapeHtml(event.fb_event_url)}" target="_blank" style="display: inline-block; background: #667eea; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; margin-right: 10px;">View on Facebook</a>`
      : '';

    return `
      <article class="gsp-event-post" style="margin: 30px 0; padding: 20px; border: 1px solid #ddd; border-radius: 8px; background: white;">
        <h2 style="margin-top: 0;">${escapeHtml(event.venue || 'GSP Event')} - ${event.date_display}</h2>
        <div class="gsp-event-meta" style="color: #666; margin-bottom: 15px; font-size: 0.95em;">
          ${event.host ? `<span style="margin-right: 20px;"><strong>Host:</strong> ${escapeHtml(event.host)}</span>` : ''}
          ${event.photo_count ? `<span><strong>Photos:</strong> ${event.photo_count}</span>` : ''}
          ${event.is_validated ? `<span style="margin-left: 20px; color: green;"><strong>✓ Validated</strong></span>` : ''}
        </div>
        ${photosHtml}
        ${recapHtml}
        ${highlightsHtml}
        <div class="gsp-event-actions" style="margin-top: 20px;">
          ${fbLink}
          ${event.pdf_url ? `<a href="${escapeHtml(event.pdf_url)}" target="_blank" style="display: inline-block; background: #f0f0f0; color: #333; padding: 10px 20px; border-radius: 6px; text-decoration: none; border: 1px solid #ddd;">View PDF</a>` : ''}
        </div>
      </article>
    `;
  }

  /**
   * Render events into a container element
   */
  async function renderEvents(containerId, options = {}) {
    const container = document.getElementById(containerId);
    if (!container) {
      console.error(`Container with id '${containerId}' not found`);
      return;
    }

    try {
      container.innerHTML = '<p style="text-align: center; color: #666;">Loading events...</p>';
      
      const events = await fetchEvents();
      const {
        limit = events.length,
        venue = null,
        template = 'blog-post'
      } = options;

      let filteredEvents = events;
      if (venue) {
        filteredEvents = getEventsByVenue(venue);
      }
      filteredEvents = filteredEvents.slice(0, limit);

      if (!filteredEvents || filteredEvents.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: #999;">No events found.</p>';
        return;
      }

      if (template === 'blog-post') {
        container.innerHTML = filteredEvents.map(e => generateBlogPost(e)).join('');
      } else if (template === 'list') {
        container.innerHTML = `<ul style="list-style: none; padding: 0;">
          ${filteredEvents.map(e => `
            <li style="padding: 10px 0; border-bottom: 1px solid #eee;">
              <strong>${escapeHtml(e.venue || 'TBA')}</strong> - ${e.date_display}
              ${e.fb_event_url ? `<br><a href="${escapeHtml(e.fb_event_url)}" target="_blank" style="color: #667eea; text-decoration: none;">View on Facebook →</a>` : ''}
            </li>
          `).join('')}
        </ul>`;
      }
    } catch (error) {
      container.innerHTML = `<p style="color: #c33;">Error loading events: ${escapeHtml(error.message)}</p>`;
    }
  }

  /**
   * Embed event widget code (for Squarespace code blocks)
   * Usage: Add <div id="gsp-events-widget"></div> and then call GSPPublicEvents.embedWidget('gsp-events-widget')
   */
  function embedWidget(containerId, options = {}) {
    renderEvents(containerId, {
      limit: 10,
      template: 'blog-post',
      ...options
    });
  }

  /**
   * Get structured data for SEO (JSON-LD)
   */
  async function getStructuredData() {
    const events = await fetchEvents();
    
    return {
      '@context': 'https://schema.org',
      '@type': 'ItemList',
      itemListElement: events.map((event, index) => ({
        '@type': 'ListItem',
        position: index + 1,
        item: {
          '@type': 'Event',
          name: `${event.venue || 'GSP Event'} - ${event.date_display}`,
          startDate: event.date,
          location: {
            '@type': 'Place',
            name: event.venue
          },
          url: event.fb_event_url,
          image: event.photos && event.photos[0] ? event.photos[0] : undefined,
          description: event.ai_recap || event.highlights
        }
      }))
    };
  }

  /**
   * Inject structured data into page head for SEO
   */
  async function injectStructuredData() {
    try {
      const data = await getStructuredData();
      const script = document.createElement('script');
      script.type = 'application/ld+json';
      script.textContent = JSON.stringify(data);
      document.head.appendChild(script);
    } catch (error) {
      console.error('Failed to inject structured data:', error);
    }
  }

  /**
   * Setup polling for real-time updates (optional)
   */
  function startPolling(intervalMs = 5 * 60 * 1000, callback) {
    const poll = async () => {
      try {
        const events = await fetchEvents(false); // Force refresh
        if (callback) callback(events);
      } catch (error) {
        console.error('Polling error:', error);
      }
    };

    poll(); // Initial call
    return setInterval(poll, intervalMs);
  }

  /**
   * Export public API
   */
  const API = {
    fetchEvents,
    getEvent,
    getRecentEvents,
    getEventsByVenue,
    formatDate,
    escapeHtml,
    generateBlogPost,
    renderEvents,
    embedWidget,
    getStructuredData,
    injectStructuredData,
    startPolling,
    clearCache: () => {
      eventCache = null;
      cacheTimestamp = 0;
    }
  };

  // Expose to global scope
  if (typeof window !== 'undefined') {
    window.GSPPublicEvents = API;
  }

  // CommonJS export for Node.js/bundlers
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = API;
  }

})(typeof window !== 'undefined' ? window : global);
