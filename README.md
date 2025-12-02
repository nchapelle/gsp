# GSP Events Platform: Backend (Cloud Run) + Frontend (Firebase)

This repository contains the full-stack application for managing GSP events, from creation by hosts to social media posting and public tournament tracking.

## Architecture Overview

-   **Backend API**: A Python (Flask) application running on **Google Cloud Run**. It handles all business logic, database interactions, and file processing.
-   **Database**: A managed **Neon PostgreSQL** database serves as the primary data store.
-   **File Storage**: **Google Cloud Storage (GCS)** is used for storing all user-uploaded assets (PDFs, photos).
-   **Frontend**: Static HTML/CSS/JS applications served by **Firebase Hosting**. The frontend is divided into several portals for different user roles (Hosts, SMM, Admin).
-   **Deployment**: The backend is containerized with Docker and deployed automatically via **Google Cloud Build**.

---

## Portals & Base URLs

-   **API (Cloud Run)**: `https://api.gspevents.com`
-   **Assets (Firebase Hosting)**: `https://app.gspevents.com/assets/`
-   **Frontend Pages**:
    -   Host Portal: `https://app.gspevents.com/hosts`
    -   SMM Dashboard: `https://app.gspevents.com/smm`
    -   Admin Portal: `https://app.gspevents.com/admin`
    -   Tournament Scores: `https://app.gspevents.com/tournament/scores`

    New Admin Report:
    - Weekly Post Report (Admin): The admin data page includes a "Weekly Post Report" to visualize which venues had a submitted event during a chosen week (EST Mon–Sun) and whether the event was unvalidated, validated, or posted. Backend endpoint: `GET /admin/weekly-report?week_ending=YYYY-MM-DD` returns a per-venue report for the requested week. Any date may be passed and the server will normalize it to the week-ending Sunday.

---

## Core API Workflow (Host Event Creation)

The primary flow involves a host uploading a recap PDF and photos, which are processed by the backend to create an event and generate social media content.

1.  **Host Fills Form**: The host selects their name, venue, and event date in the Host Portal.
2.  **Host Selects Files**: The host uploads a single PDF recap and multiple photos.
3.  **Client-Side Upload**: The frontend JavaScript uploads each file individually to the backend's `/generate-upload-url` endpoint.
    -   **Note**: This endpoint is a proxy. It receives the file's binary data and uploads it directly to GCS from the server. It does *not* return a signed URL for client-side PUTs.
4.  **Backend Creates Event**: Once all files are uploaded, the frontend sends a final request to `/create-event` with the host/venue IDs, date, and the GCS URLs for the uploaded files.
5.  **Backend Parses PDF**: Upon event creation, a background task is triggered to call the `/events/{id}/parse-pdf` endpoint. This reads the PDF from GCS, extracts team data using `pdfminer`, and populates the `event_participation` table.
6.  **Backend Generates AI Recap**: After parsing, the backend generates a social media recap text and saves it to the event record.
7.  **SMM Review**: The event now appears in the "Unposted" list on the SMM dashboard, ready for review, editing, and posting.

---

## Deployment (via Cloud Build)

The backend is deployed by submitting the `cloudbuild.yaml` configuration to Google Cloud Build.

```bash
gcloud builds submit --config cloudbuild.yaml .
```

The build process performs three main steps:
1.  **Builds** the Docker image.
2.  **Pushes** the image to Google Artifact Registry.
3.  **Deploys** the new image to the `gsp-backend-api` Cloud Run service, injecting the latest environment variables from the `env.list` file defined within the build step.

After a successful deployment, it's wise to run a migration and a health check:

```bash
# Ensure database schema is up-to-date
curl -X POST https://api.gspevents.com/migrate

# Check API and DB connectivity
curl https://api.gspevents.com/doctor
```

---

## Environment Variables (Cloud Run)

The following environment variables must be configured in the Cloud Run service (or in `cloudbuild.yaml` for automated deployments).

| Variable             | Description                                                                     | Example Value                                                  |
| -------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `PGHOST`             | The hostname of the Neon PostgreSQL database pooler.                            | `ep-misty-base-....aws.neon.tech`                              |
| `PGDATABASE`         | The name of the database.                                                       | `gsp_data`                                                     |
| `PGUSER`             | The database username.                                                          | `neondb_owner`                                                 |
| `PGPASSWORD`         | The database password.                                                          | `npg_...`                                                      |
| `PGPORT`             | The database port.                                                              | `5432`                                                         |
| `PGSSLMODE`          | SSL mode for the connection. **Required by Neon.**                              | `require`                                                      |
| `GCS_BUCKET`         | The name of the Google Cloud Storage bucket for file uploads.                   | `gsp-event-uploads`                                            |
| `ALLOWED_ORIGINS`    | Comma or pipe-separated list of origins for CORS.                               | `https://app.gspevents.com,https://www.gspevents.com`           |
| `HOST_API_TOKEN`     | (Optional) A secret token to protect sensitive endpoints (`create-event`, etc.). | `your-secret-token`                                            |

---

## Common Troubleshooting

-   **Styling Missing on a Page**: Ensure the HTML file correctly links to the main stylesheet: `<link rel="stylesheet" href="https://app.gspevents.com/assets/styles.css">`.
-   **CORS Errors**: The `ALLOWED_ORIGINS` environment variable in Cloud Run may not include the origin of the web page making the request. Add the origin and redeploy the backend.
-   **500 Errors on Event Creation**: Check the Cloud Run logs for database connection errors or constraint violations (e.g., duplicate event for the same venue/date). Ensure environment variables are correct and run a `POST /migrate` to verify the schema.
-   **File Uploads Failing**: This is often a permission issue. Verify that the Cloud Run service account has the "Storage Object Admin" (`roles/storage.objectAdmin`) IAM role on the target GCS bucket.
-   **PDF Parsing Fails**: Use the diagnostic endpoint `POST /diag/parse-preview` with an event ID or PDF URL to inspect the raw text extracted from the PDF and see how the parser interprets it.