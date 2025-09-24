# Path on your machine
$teams = Get-Content -Raw -Path ".\teams.json"
$events = Get-Content -Raw -Path ".\events.json"

# Make sure the JSON is either:
# - an array of rows: [ { ... }, { ... } ]
# - or an object with { "rows": [ ... ] }

Invoke-RestMethod -Uri "https://gsp-backend-api-332508315215.us-east1.run.app/admin/seed-tournament-teams" `
  -Method POST `
  -Body $teams `
  -ContentType "application/json"

Invoke-RestMethod -Uri "https://gsp-backend-api-332508315215.us-east1.run.app/admin/seed-events" `
  -Method POST `
  -Body $events `
  -ContentType "application/json"