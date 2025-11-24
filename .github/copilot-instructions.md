# Copilot / AI agent instructions for the GSP repository

This file contains concise, actionable guidance to help AI coding agents be productive in this codebase.

- Big picture: Full‑stack application. Backend is a Flask API (backend/app.py) deployed on Google Cloud Run; frontend is static HTML/CSS/JS served by Firebase Hosting (frontend/). Primary datastore is a Neon PostgreSQL instance; file uploads live in Google Cloud Storage.

- Important files to read first:
  - backend/app.py — main API implementation, routing, upload validation, PDF parsing, and maintenance endpoints.
  - backend/cloudbuild.yaml & backend/Dockerfile — CI/CD (Cloud Build) and container runtime used to build + deploy.
  - frontend/assets/config.js — sets `API_BASE_URL` and adds the `TOKEN` header for authenticated host API calls.
  - frontend/assets/host-event.js & frontend/assets/main.js — how the frontend uploads bytes to `/generate-upload-url`, links photos, and calls `/create-event`.
  - README.md — authoritative high‑level overview; refer back to it for deployment and troubleshooting commands.

- Highly relevant runtime / API details to preserve and reuse:
  - POST /generate-upload-url  — backend accepts raw file bytes, stores in GCS and returns `publicUrl`. (Frontend: `uploadToBucket` in host-event.js)
  - POST /create-event — final event creation (sends GCS URLs for the uploaded files).
  - POST /events/{id}/parse-pdf — explicit parsing endpoint used in background to extract teams from uploaded PDFs.
  - POST /events/{id}/add-photo-url and POST /events/{id}/add-photo — link photos to events (bytes vs url differences).
  - POST /migrate and GET /doctor — migration and health endpoints used after deploy.

- Security / config specifics:
  - `HOST_API_TOKEN` gates sensitive endpoints (header X-GSP-Token or query param `t`). See `require_host_token` in backend/app.py and how frontend `config.js` attaches it.
  - ALLOWED_ORIGINS can be comma- or pipe-separated and is used to configure CORS (backend/app.py).
  - Upload validation (MAX_PDF_BYTES, MAX_IMG_BYTES and allowed mimetypes) is enforced in backend/app.py — maintain these checks if you change upload logic.

- Developer workflows (explicit commands observed in repo):
  - Deploy backend: gcloud builds submit --config backend/cloudbuild.yaml .
  - After deploy: run `curl -X POST https://api.gspevents.com/migrate` and `curl https://api.gspevents.com/doctor` to ensure migrations/health.
  - Local run: `python backend/app.py` (Flask dev server binds to 0.0.0.0:8080). For production parity, `docker build` with backend/Dockerfile or use the cloudbuild pipeline in backend/cloudbuild.yaml.

- Parsing & data constraints to be conservative about:
  - PDF text extraction uses pdfminer.six with a pypdf fallback; text extraction is lossy and brittle — use `POST /diag/parse-preview` and real PDFs to validate changes.
  - Team parsing functions (likely_noise_line, extract_players_and_flags) contain heuristics tailored to supplied PDFs. Prioritize tests with representative PDF samples before modifying.

- Notable gotchas / conventions to follow:
  - Frontend relies on `CONFIG.j` wrapper and `CONFIG.TOKEN` for API calls — keep these when adding new browser-facing network requests.
  - The repo contains an easily discoverable admin gate (client-side obfuscation) in `frontend/assets/main.js` (password: `GSPevents2020!`). Do not expose secrets or remove checks without coordinating security cleanup.
  - There are few automated tests; use the diagnostic endpoints and integration checks when changing parsing side effects.

If anything here is unclear or missing, tell me which parts you want expanded (examples, code locations, or run/debug commands) and I’ll iterate. 
