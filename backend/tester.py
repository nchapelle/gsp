app.py

# --- Imports (no change needed here, assuming the rest of app.py is as before) ---
import os
import re
import json
import gzip
import logging
import time
import random
import ssl
from io import BytesIO
from uuid import uuid4
from urllib.parse import quote
from datetime import datetime

import requests as httpx
import requests as rq
import requests as _req
import pg8000

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge

from google.cloud import storage

from pdfminer.high_level import extract_text
from pypdf import PdfReader

# ------------------------------------------------------------------------------
# App + CORS (unchanged)
# ------------------------------------------------------------------------------
app = Flask(__name__)

raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "https://app.gspevents.com,https://gspevents.web.app,https://www.gspevents.com",
)
for sep in ("|", " "):
    raw_origins = raw_origins.replace(sep, ",")
ALLOWED = [o.strip() for o in raw_origins.split(",") if o.strip()]
CORS(app, resources={r"/*": {"origins": ALLOWED}})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Config (unchanged)
# ------------------------------------------------------------------------------
PGHOST = os.getenv("PGHOST")
PGDATABASE = os.getenv("PGDATABASE")
PGUSER = os.getenv("PGUSER")
PGPASSWORD = os.getenv("PGPASSWORD")
PGPORT = int(os.getenv("PGPORT", "5432"))

GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()
PUBLIC_BASE = os.getenv("PUBLIC_BASE", "https://app.gspevents.com")

storage_client = storage.Client()

# ------------------------------------------------------------------------------
# Optional token gate (unchanged)
# ------------------------------------------------------------------------------
HOST_TOKEN = os.getenv("HOST_API_TOKEN")

def require_host_token():
    if not HOST_TOKEN:
        return True
    tok = request.headers.get("X-GSP-Token") or request.args.get("t")
    return tok == HOST_TOKEN

@app.before_request
def _gate():
    protected = (
        request.path.startswith("/generate-upload-url")
        or request.path.startswith("/create-event")
        or (request.path.startswith("/events/") and request.path.endswith("/add-photo"))
    )
    if protected and not require_host_token():
        return jsonify({"error": "unauthorized"}), 401

# ------------------------------------------------------------------------------
# Runtime SA diagnostics helper (unchanged)
# ------------------------------------------------------------------------------
METADATA_EMAIL_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/email"
)
METADATA_HEADERS = {"Metadata-Flavor": "Google"}

def get_runtime_sa_email() -> str | None:
    try:
        r = _req.get(METADATA_EMAIL_URL, headers=METADATA_HEADERS, timeout=2)
        if r.ok:
            email = (r.text or "").strip()
            if "@" in email and email.endswith(".iam.gserviceaccount.com"):
                return email
    except Exception:
        pass
    try:
        from google.auth import default as ga_default
        creds, _ = ga_default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        email = getattr(creds, "service_account_email", None)
        if email and "@" in email:
            return email
    except Exception:
        pass
    return None

# ------------------------------------------------------------------------------
# DB conn (unchanged)
# ------------------------------------------------------------------------------
def getconn():
    if not all([PGHOST, PGDATABASE, PGUSER, PGPASSWORD]):
        raise RuntimeError("DB env vars missing: PGHOST, PGDATABASE, PGUSER, PGPASSWORD")
    ctx = ssl.create_default_context()
    return pg8000.connect(
        host=PGHOST,
        database=PGDATABASE,
        user=PGUSER,
        password=PGPASSWORD,
        port=PGPORT,
        ssl_context=ctx,
    )

# ------------------------------------------------------------------------------
# Upload helpers (unchanged)
# ------------------------------------------------------------------------------
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "application/octet-stream",
}
MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_IMG_BYTES = 20 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = 35 * 1024 * 1024

def safe_key(file_name: str) -> str:
    if not file_name:
        stem, ext = "file", ""
    else:
        raw = str(file_name).split("/")[-1].split("\\")[-1].strip()
        m = re.match(r"^(.*?)(\.[A-Za-z0-9]{1,6})?$", raw)
        if m:
            stem = (m.group(1) or "file").strip()
            ext = (m.group(2) or "")
        else:
            stem, ext = raw, ""
        stem = re.sub(r"\s+", "_", stem)
        stem = re.sub(r"[^\w\.\-]+", "-", stem)
        if not stem:
            stem = "file"
    stem = quote(stem, safe="._-")
    ext = quote(ext, safe="._-")
    prefix = uuid4().hex[:8]
    datedir = datetime.utcnow().strftime("%Y/%m/%d")
    return f"uploads/{datedir}/{prefix}-{stem}{ext}"

def validate_upload(kind, uploaded_file):
    ctype = (uploaded_file.mimetype or "").lower()
    name = (uploaded_file.filename or "").strip()
    pos = uploaded_file.stream.tell()
    uploaded_file.stream.seek(0, os.SEEK_END)
    size = uploaded_file.stream.tell()
    uploaded_file.stream.seek(pos)

    if kind == "pdf":
        if not ctype.startswith("application/pdf") and not name.lower().endswith(".pdf"):
            raise ValueError("File must be a PDF (application/pdf)")
        if size <= 0:
            raise ValueError("Empty PDF upload")
        if size > MAX_PDF_BYTES:
            raise ValueError("PDF exceeds 30 MB limit")
        return ctype, size

    # image
    ext = (name.split(".")[-1] or "").lower()
    if ctype not in ALLOWED_IMAGE_TYPES:
        if ext not in {"jpg", "jpeg", "png", "webp", "heic", "heif"}:
            raise ValueError(f"Image type not allowed (type={ctype or 'n/a'}, name={name or 'n/a'})")
    if size <= 0:
        raise ValueError("Empty image upload")
    if size > MAX_IMG_BYTES:
        raise ValueError("Image exceeds 12 MB limit")
    return ctype, size

def fetch_with_retry(url, attempts=3, timeout=60):
    last = None
    for i in range(attempts):
        try:
            r = httpx.get(url, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"retryable status {r.status_code}")
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            time.sleep((0.4 + random.random()) * (2 ** i))
    raise last

# ------------------------------------------------------------------------------
# PDF parsing helpers (REVISED)
# ------------------------------------------------------------------------------
HEADER_KEYWORDS = [
    "WEEK ENDING", "TOTAL", "VENUE", "TEAM NAME", "POINTS", "PLAYERS",
    "FALL", "LEADER BOARD", "TOURNAMENT", "GSP", "EVENT DETAILS",
    "QUIZZES", "PRINT DATE", "QUIZ DATE", "QUIZ FILE", "KEYPAD", "TIME (S)"
]

def likely_noise_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    upper = s.upper()
    for kw in HEADER_KEYWORDS:
        if kw in upper:
            return True
    # If the line only contains non-alphanumeric chars or single digit/letter
    if re.fullmatch(r"[\W_]+", s) or re.fullmatch(r"^\d$", s) or re.fullmatch(r"^[A-Z]$", s):
        return True
    return False

def extract_players_and_flags(flag_text: str):
    if not flag_text:
        return None, False, False
    t = re.sub(r"\s+", "", str(flag_text).upper())
    m = re.match(r"(\d+)([A-Z]*)", t)
    if not m:
        # If no number is found, it might still have flags like 'T' or 'V'
        return None, ("T" in t) or ("V" in t), "V" in t
    n = int(m.group(1))
    flags = m.group(2) or ""
    has_v = "V" in flags
    has_t = ("T" in flags) or has_v
    return n, has_t, has_v

# Adjectives and AI recap (unchanged)
AI_ADJECTIVES = [
    "fantastic", "electric", "high‑energy", "unforgettable", "spirited",
    "lively", "jam‑packed", "fun‑filled", "epic", "legendary", "exhilarating",
    "rowdy", "buzzing", "awesome", "memorable", "thrilling", "excellent",
    "super fun", "intense", "breathtaking", "riveting", "captivating",
    "competitive", "dynamic", "playful", "spectacular", "pulse-pounding",
]

def _fmt_event_date_human(dt):
    if not dt:
        return ""
    if isinstance(dt, datetime):
        d = dt.date()
    else:
        d = dt
    try:
        return d.strftime("%A, %b %-d, %Y")
    except Exception:
        return d.strftime("%A, %b %d, %Y").replace(" 0", " ")

def format_ai_recap(event_row, winners, venue_defaults, adjective=None):
    venue = (event_row[8] or "").strip() if len(event_row) > 8 else ""
    host = (event_row[7] or "").strip() if len(event_row) > 7 else ""
    highlights = (event_row[2] or "").strip() if len(event_row) > 2 else ""
    dt = event_row[1] if len(event_row) > 1 else None
    date_str = _fmt_event_date_human(dt)

    adj = (adjective or "").strip() or random.choice(AI_ADJECTIVES)

    w1 = winners[0]["name"] if len(winners) > 0 and winners[0].get("name") else ""
    w2 = winners[1]["name"] if len(winners) > 1 and winners[1].get("name") else ""
    w3 = winners[2]["name"] if len(winners) > 2 and winners[2].get("name") else ""

    next_day = (venue_defaults.get("default_day") or "").strip() if isinstance(venue_defaults, dict) else ""
    event_time = (venue_defaults.get("default_time") or "").strip() if isinstance(venue_defaults, dict) else ""

    lines = []
    brand = "Game Show Palooza"

    if date_str:
        if host:
            lines.append(f"It was a {adj} night of {brand} at {venue} on {date_str} with {host}!")
        else:
            lines.append(f"It was a {adj} night of {brand} at {venue} on {date_str}!")
    else:
        if host:
            lines.append(f"It was a {adj} night of {brand} at {venue} with {host}!")
        else:
            lines.append(f"It was a {adj} night of {brand} at {venue}!")

    if w1 or w2 or w3:
        lines.append("")
        lines.append("Congratulations to our Winning Teams:")
        if w1: lines.append(f"  • 1st: {w1}")
        if w2: lines.append(f"  • 2nd: {w2}")
        if w3: lines.append(f"  • 3rd: {w3}")

    lines.append("")
    if highlights:
        lines.append(f"Special shoutout: {highlights}")
    else:
        lines.append("")

    lines.append("")
    lines.append("Thanks to all the teams who came out and played with us tonight.")

    if next_day and event_time:
        lines.append(f"See you next {next_day} at {event_time}!")
    elif next_day:
        lines.append(f"See you next {next_day}!")
    elif event_time:
        lines.append(f"Join us at {event_time}!")
    else:
        lines.append("See you at the next show!")

    return "\n".join(lines).strip()

@app.errorhandler(RequestEntityTooLarge)
def handle_413(_e):
    return jsonify({"error": "Upload too large. PDF max 30 MB, images max 12 MB."}), 413

# ------------------------------------------------------------------------------
# PDF parsing helpers (REVISED for multi-format parsing)
# ------------------------------------------------------------------------------
def to_direct_download(url: str) -> str:
    if not url:
        return url
    if "drive.google.com" not in url:
        return url
    m = re.search(r"/file/d/([^/]+)/", url)
    if m:
        fid = m.group(1)
        return f"https://drive.google.com/uc?export=download&id={fid}"
    m2 = re.search(r"[?&]id=([^&]+)", url)
    if m2:
        fid = m2.group(1)
        return f"https://drive.google.com/uc?export=download&id={fid}"
    return url

def fetch_pdf_bytes(pdf_url: str) -> bytes:
    url = to_direct_download(pdf_url)
    r = fetch_with_retry(url, attempts=3, timeout=60)
    return r.content

def safe_extract_text(pdf_bytes: bytes) -> str:
    try:
        return extract_text(BytesIO(pdf_bytes)) or ""
    except Exception as e:
        logger.warning("pdfminer failed; falling back to pypdf: %s", e)
        try:
            reader = PdfReader(BytesIO(pdf_bytes))
            return "\n".join([page.extract_text() or "" for page in reader.pages])
        except Exception as e2:
            logger.error("pypdf also failed: %s", e2)
            return ""

def _parse_tabular_format(lines: list[str]):
    """
    Parses PDF text with a clear tabular structure where Rank, Team, and Score
    are often found on the same line, or very close together.
    This handles the "Game Show Palooza Quizzes" format well.
    """
    items = []
    current_position = 0

    # Regex to capture rank, team name (with optional players), and score on one line
    # Flexible with whitespace between columns
    pat_full_row = re.compile(
        r"""^\s*
            (?P<rank>\d+)?                  # Optional rank number at start
            \s+
            (?P<name>[^(\n]+?)             # Team name, non-greedy, until '(' or newline
            \s*(?:\(\s*(?P<flags>[\d\sTVtv]+)\s*\))? # Optional (player flags)
            (?:                                   # Optional score part
                .*?                           # Any chars in between
                (?P<score>-?\d+)              # The actual score number
            )?
            \s*$""",
        re.VERBOSE | re.IGNORECASE,
    )

    # Fallback for teams without player count in parentheses (e.g., "WHAMMY")
    pat_team_only = re.compile(
        r"""^\s*
            (?P<rank>\d+)?                  # Optional rank number
            \s*
            (?P<name>[A-Za-z0-9\s-]{2,})    # Team name, at least 2 chars
            \s*$""",
        re.VERBOSE | re.IGNORECASE,
    )

    for i, ln in enumerate(lines):
        s = (ln or "").strip()
        if not s or likely_noise_line(s):
            continue

        match = pat_full_row.match(s)
        if match:
            name = (match.group("name") or "").strip()
            flags_raw = match.group("flags")
            score_str = match.group("score")
            rank_str = match.group("rank")

            nplayers, is_t, is_v = extract_players_and_flags(flags_raw or "")
            score = int(score_str) if score_str else None
            rank = int(rank_str) if rank_str else None

            # Skip "WHAMMY" or similar non-team entries that are clearly not teams
            if "WHAMMY" in name.upper() and (nplayers is None or nplayers == 0) and not name.upper().startswith("TEAM"):
                continue

            current_position += 1
            items.append({
                "name": name,
                "score": score,
                "playerCount": nplayers or 0,
                "isTournament": bool(is_t),
                "isVisiting": bool(is_v),
                "position": rank if rank is not None else current_position,
                "_raw_line_idx": i # For potential debugging/ordering
            })
        else:
            # Try to catch "WHAMMY" if it's the only thing on the line, but
            # prioritize real teams. This is a fallback to capture generic team-like lines.
            match_team_only = pat_team_only.match(s)
            if match_team_only:
                name = (match_team_only.group("name") or "").strip()
                rank_str = match_team_only.group("rank")
                if "WHAMMY" in name.upper() and not name.upper().startswith("TEAM "):
                    continue # Exclude generic WHAMMY as a team
                
                # Check for duplicates before adding as a generic team
                if not any(t['name'].lower() == name.lower() for t in items):
                    current_position += 1
                    items.append({
                        "name": name,
                        "score": None, # No score on this line
                        "playerCount": 0,
                        "isTournament": False,
                        "isVisiting": False,
                        "position": int(rank_str) if rank_str else current_position,
                        "_raw_line_idx": i
                    })

    return items


def _parse_split_format(lines: list[str]):
    """
    Parses PDF text where team names (with optional player counts) are in one block,
    and scores are in a separate, later block.
    This handles the QuizXpress Analyzer "Name" / "Score" format.
    """
    items = []
    potential_teams = []
    # Team Name (and optional player count) regex
    pat_team_and_flags = re.compile(
        r"""^\s*
            (?P<rank>\d+)?                  # Optional leading rank (e.g., 1)
            \s*
            (?P<name>[^(\n]+?)             # Capture team name (non-greedy)
            \s*\(\s*(?P<flags>[\d\sTVtv]+)\s*\) # Capture (digits/flags)
            \s*$""",
        re.VERBOSE | re.IGNORECASE,
    )

    # General team name regex for cases like "Whammy" without (num)
    pat_loose_team_name = re.compile(
        r"""^\s*
            (?P<rank>\d+)?                  # Optional leading rank (e.g., 1)
            \s*
            (?P<name>[A-Za-z0-9\s-]{2,})    # At least 2 alpha-numeric chars for a name
            \s*$""",
        re.VERBOSE | re.IGNORECASE,
    )

    for i, ln in enumerate(lines):
        s = (ln or "").strip()
        if not s or likely_noise_line(s):
            continue

        match_flags = pat_team_and_flags.match(s)
        if match_flags:
            name = (match_flags.group("name") or "").strip(" -–—\t")
            flags_raw = match_flags.group("flags")
            rank_str = match_flags.group("rank")

            nplayers, is_t, is_v = extract_players_and_flags(flags_raw or "")
            if "WHAMMY" in name.upper() and (nplayers is None or nplayers == 0) and not name.upper().startswith("TEAM"):
                continue

            potential_teams.append({
                "name": name,
                "playerCount": nplayers or 0,
                "isTournament": bool(is_t),
                "isVisiting": bool(is_v),
                "score": None, # Will be filled later
                "position": int(rank_str) if rank_str else None,
                "_raw_line_idx": i
            })
            continue

        # Try to match loose team names (e.g., "Whammy" without parentheses)
        match_loose = pat_loose_team_name.match(s)
        if match_loose:
            name = (match_loose.group("name") or "").strip(" -–—\t")
            rank_str = match_loose.group("rank")

            if "WHAMMY" in name.upper() and not name.upper().startswith("TEAM "):
                continue # Exclude generic WHAMMY as a team

            # Only add if not already captured by pat_team_and_flags (by name)
            if not any(t["name"].lower() == name.lower() for t in potential_teams):
                potential_teams.append({
                    "name": name,
                    "playerCount": 0,
                    "isTournament": False,
                    "isVisiting": False,
                    "score": None,
                    "position": int(rank_str) if rank_str else None,
                    "_raw_line_idx": i
                })

    # Deduplicate and assign final positions
    deduped_teams = []
    seen_names = set()
    for t in sorted(potential_teams, key=lambda x: x.get('position') or x['_raw_line_idx']): # Sort by explicit rank or line order
        if t["name"].lower() not in seen_names:
            seen_names.add(t["name"].lower())
            if t["position"] is None:
                t["position"] = len(deduped_teams) + 1 # Assign sequential if not set
            deduped_teams.append(t)
    items = deduped_teams


    # --- Score Column Alignment ---
    try:
        teams_n = len(items)
        if teams_n == 0:
            raise ValueError("No teams found for score alignment.")

        # Re-parse raw text into segments based on blank lines
        text_full = "\n".join(lines)
        segments = re.split(r"\n\s*\n", text_full)

        def classify_score_block(seg_text: str):
            ls = [ln.strip() for ln in seg_text.split("\n") if ln.strip()]
            if not ls: return None
            
            # Look for a "Score" header indicating a score block
            has_score_header = False
            for header_kw in ["SCORE", "POINTS"]:
                if any(header_kw in s.upper() for s in ls[:2]): # Check first two lines for header
                    has_score_header = True
                    break
            
            # If there's no explicit header, assume it's a score block if it looks like one
            if not has_score_header and not all(re.fullmatch(r"[-+]?\d+", s) for s in ls):
                return None # Must have header or be purely numbers to be considered score block

            ints = []
            int_like_count = 0
            for s in ls:
                m = re.fullmatch(r"[-+]?\d+", s) # Allow '+' for positive scores
                if m:
                    ints.append(int(s))
                    int_like_count += 1
            
            # A block qualifies as scores if a high percentage of lines are numbers
            # And it either has a score header or is almost entirely numbers.
            if len(ls) > 0 and (int_like_count / len(ls) >= 0.7 or has_score_header):
                return { "qualifies": True, "scores": ints, "raw_lines": ls }
            return None

        score_blocks = []
        for seg in segments:
            info = classify_score_block(seg)
            if info and info["qualifies"]:
                score_blocks.append(info)
        
        # Prioritize the largest score block, or the one with a "Score" header.
        best_score_block = None
        if score_blocks:
            # Sort by number of scores (desc), then whether it has a header (desc), then by appearance (asc)
            best_score_block = max(score_blocks, key=lambda x: (len(x['scores']), 'SCORE' in x['raw_lines'][0].upper() or 'POINTS' in x['raw_lines'][0].upper()))


        if best_score_block and best_score_block["scores"]:
            nums = best_score_block["scores"]
            
            # If the number of scores matches the number of teams, assign directly by order.
            if len(nums) == teams_n:
                for j in range(teams_n):
                    items[j]["score"] = nums[j]
            elif len(nums) > teams_n:
                # If more scores than teams, assign the top N scores
                for j in range(teams_n):
                    items[j]["score"] = nums[j]
            else: # Less scores than teams, assign what's available
                for j in range(len(nums)):
                    items[j]["score"] = nums[j]
    except Exception as e:
        logger.warning(f"Error during split format score alignment: {e}")
        pass

    return items


def parse_raw_text(raw: str):
    """
    Primary function to parse raw text from PDF and extract event participation.
    It attempts to detect the PDF format (tabular vs. split blocks) and calls
    the appropriate sub-parser.
    """
    total_players = 0
    if not raw:
        return {"teams": [], "teamCount": 0, "playerCount": 0}

    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    # Heuristic to detect format: Check for lines that strongly resemble a tabular row
    # (Rank + Name(Players) + Score all on one line)
    # This pattern indicates the _parse_tabular_format is likely appropriate.
    tabular_pattern_count = 0
    # Look for a line starting with digit, then name (not starting with digit), then (players), then score
    test_pat = re.compile(
        r"^\s*\d+\s+[^(\d\n][^(\n]*?\s*\(\s*[\d\sTVtv]+\s*\)\s+.*?-?\d+\s*$",
        re.VERBOSE | re.IGNORECASE
    )
    for ln in lines:
        if test_pat.match(ln):
            tabular_pattern_count += 1
            if tabular_pattern_count > 2: # If we find more than 2 such lines, assume tabular
                break

    if tabular_pattern_count > 2 or "Team/player" in text or "Time (s) Score" in text:
        logger.info("Detected tabular format.")
        items = _parse_tabular_format(lines)
    else:
        logger.info("Detected split/block format.")
        items = _parse_split_format(lines)

    # Calculate total players and ensure positions are filled and deduped (if not already handled)
    final_items = []
    seen_names = set()
    # Sort by position (if set) or original line index for consistent ordering
    for team in sorted(items, key=lambda x: (x.get('position') if x.get('position') is not None else float('inf'), x.get('_raw_line_idx', float('inf')))):
        if team['name'].lower() not in seen_names:
            seen_names.add(team['name'].lower())
            final_items.append(team)

    for i, team in enumerate(final_items):
        if team.get("position") is None:
            team["position"] = i + 1
        total_players += team.get("playerCount", 0)
        # Clean up temporary keys
        if '_raw_line_idx' in team:
            del team['_raw_line_idx']
        
        # Ensure 'name' is stripped of leading/trailing junk that might come from regex capture groups
        team['name'] = team['name'].strip(' -–—\t')


    return {"teams": final_items, "teamCount": len(final_items), "playerCount": total_players}


# ------------------------------------------------------------------------------
# Diagnostics (unchanged, but relies on new parse_raw_text)
# ------------------------------------------------------------------------------
@app.get("/version")
def version():
    try:
        import google.cloud.storage as gcs
        gcs_ver = getattr(gcs, "__version__", "unknown")
    except Exception:
        gcs_ver = "unknown"
    try:
        import google.auth as gauth
        ga_ver = getattr(gauth, "__version__", "unknown")
    except Exception:
        ga_ver = "unknown"

    sa_email = get_runtime_sa_email()

    return jsonify({
        "app": "gsp-backend-api",
        "build": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "libs": {
            "google_cloud_storage": gcs_ver,
            "google_auth": ga_ver,
        },
        "runtime_sa": sa_email,
        "env": {
            "pg_host": bool(PGHOST),
            "pg_db": bool(PGDATABASE),
            "pg_user": bool(PGUSER),
            "gcs_bucket": GCS_BUCKET or None,
            "public_base": PUBLIC_BASE or None,
            "cors_origins": ALLOWED,
        },
        "routes": [
            # health
            "GET /doctor",
            # diag
            "GET /version", "GET /diag/sa", "GET /diag/versions", "GET /diag/bucket",
            "POST /diag/parse-pdf-test", "POST /diag/parse-preview",
            # refs
            "GET /hosts", "GET /venues",
            # uploads
            "POST /generate-upload-url", "POST /events/<id>/add-photo", "POST /events/<id>/add-photo-url",
            # events
            "GET /events", "GET /events/<id>", "PUT /events/<id>/status", "PUT /events/<id>/ai",
            "POST /events/<id>/parse-pdf", "POST /events/<id>/import-from-last-parse", "GET /events/<id>/parse-log",
            # admin (events)
            "GET /admin/events", "GET /admin/events/<id>", "PUT /admin/events/<id>",
            "PUT /admin/events/<id>/participation", "POST /admin/events/<id>/photos", "DELETE /admin/events/<id>/photos",
            "POST /admin/migrate-pdf", "POST /admin/parse-all", "POST /admin/parse-sweep",
            # admin (data)
            "POST /admin/hosts", "POST /admin/venues",
            # tournament
            "GET /admin/tournament/weeks", "POST /admin/tournament/weeks",
            "PUT /admin/tournament/scores", "GET /admin/tournament/scores",
            "GET /tournament-teams", "POST /tournament-teams",
            "PUT /tournament-teams/<id>", "DELETE /tournament-teams/<id>"
        ]
    })

@app.get("/adjectives")
def list_adjectives():
    try:
        adjectives = list(AI_ADJECTIVES)
        choice = random.choice(adjectives) if adjectives else None
        return jsonify({"adjectives": adjectives, "random": choice})
    except Exception as e:
        return jsonify({"adjectives": [], "random": None, "error": str(e)}), 500

@app.get("/diag/sa")
def diag_sa():
    email = get_runtime_sa_email()
    return jsonify({"resolved_sa_email": email})

@app.get("/diag/versions")
def diag_versions():
    import google.cloud.storage as gcs
    import google.auth as gauth
    import google.api_core as gapicore
    import requests as req
    return jsonify({
        "gcs": gcs.__version__,
        "google_auth": gauth.__version__,
        "google_api_core": gapicore.__version__,
        "requests": req.__version__,
    })

@app.get("/diag/bucket")
def diag_bucket():
    try:
        if not GCS_BUCKET:
            return jsonify({"bucket": None, "error": "GCS_BUCKET not set"}), 500
        b = storage_client.bucket(GCS_BUCKET)
        exists = False
        try:
            exists = b.exists()
        except Exception:
            pass
        return jsonify({"bucket": GCS_BUCKET, "exists": exists})
    except Exception as e:
        return jsonify({"bucket": GCS_BUCKET, "error": str(e)}), 500

@app.post("/diag/parse-pdf-test")
def diag_parse_pdf_test():
    d = request.json or {}
    pdf_url = (d.get("pdf_url") or "").strip()
    if not pdf_url:
        return jsonify({"error": "pdf_url required"}), 400
    try:
        pdf_bytes = fetch_pdf_bytes(pdf_url)
        raw = safe_extract_text(pdf_bytes)
        parsed = parse_raw_text(raw)
        return jsonify({"status": "ok", "parsed": parsed, "raw_preview": raw[:1000]})
    except Exception as e:
        logger.exception("diag_parse_pdf_test failed")
        return jsonify({"error": str(e)}), 500

@app.post("/diag/parse-preview")
def diag_parse_preview():
    d = request.json or {}
    event_id = d.get("event_id")
    pdf_url_in = (d.get("pdf_url") or "").strip()
    max_chars = int(d.get("max_chars", 4000))

    pdf_url = pdf_url_in
    conn = None
    try:
        if event_id and not pdf_url:
            conn = getconn()
            cur = conn.cursor()
            cur.execute("SELECT pdf_url FROM events WHERE id=%s;", (event_id,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            conn = None
            if not row or not row[0]:
                return jsonify({"error": "event has no pdf_url"}), 400
            pdf_url = row[0]

        pdf_bytes = fetch_pdf_bytes(pdf_url)
        raw = safe_extract_text(pdf_bytes)

        text_norm = raw.replace("\r\n", "\n").replace("\r", "\n")
        lines = text_norm.split("\n")
        from functools import lru_cache
        @lru_cache(maxsize=2048)
        def _noise(s):
            return likely_noise_line(s)

        line_sample = []
        limit_lines = min(250, len(lines))
        for i in range(limit_lines):
            s = lines[i]
            keep = not _noise(s)
            line_sample.append({"i": i, "text": s, "keep": bool(keep)})

        parsed = parse_raw_text(raw)
        payload = {
            "source_url": pdf_url,
            "raw_length": len(raw),
            "raw_text": raw[:max_chars],
            "line_count": len(lines),
            "line_sample": line_sample,
            "parsed": parsed,
            "summary": {
                "teams_found": parsed.get("teamCount", 0),
                "players_total": parsed.get("playerCount", 0)
            }
        }
        return jsonify(payload)
    except Exception as e:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        logger.exception("diag_parse_preview failed")
        return jsonify({"error": str(e)}), 500

@app.get("/diag/ai-preview/<int:eid>")
def diag_ai_preview(eid):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.id, e.event_date, e.highlights, e.pdf_url, e.ai_recap, e.status, e.fb_event_url,
                   h.name, v.name, v.default_day, v.default_time
            FROM events e
            LEFT JOIN hosts h ON e.host_id=h.id
            LEFT JOIN venues v ON e.venue_id=v.id
            WHERE e.id=%s;
        """, (eid,))
        e = cur.fetchone()
        if not e:
            return jsonify({"error":"event not found"}), 404

        cur.execute("""
            SELECT team_name, score, num_players
            FROM event_participation
            WHERE event_id=%s
            ORDER BY position ASC
            LIMIT 3;
        """, (eid,))
        rows = cur.fetchall()
        winners = [{"name": r[0], "score": r[1], "playerCount": r[2]} for r in rows]

        venue_defaults = {"default_day": e[9], "default_time": e[10]}
        preview = format_ai_recap(e, winners, venue_defaults)
        return jsonify({"status":"ok", "ai_preview": preview, "winners": winners})
    finally:
        conn.close()

# ------------------------------------------------------------------------------
# Upload endpoints (proxied) (unchanged)
# ------------------------------------------------------------------------------
@app.post("/generate-upload-url")
def proxied_upload():
    try:
        if not os.environ.get("GCS_BUCKET"):
            return jsonify({"error": "GCS_BUCKET env var missing or empty"}), 500
        bucket_name = os.environ["GCS_BUCKET"]

        uploaded_file = (
            request.files.get("file")
            or request.files.get("photo")
            or (next(iter(request.files.values())) if request.files else None)
        )
        if not uploaded_file:
            logger.warning("[proxied.upload] no file; keys=%s", list(request.files.keys()))
            logger.warning(
                "[upload.photo] empty files; ct=%s cl=%s ua=%s",
                request.headers.get("Content-Type"),
                request.headers.get("Content-Length"),
                request.headers.get("User-Agent"),)
            return jsonify({"error": "No file part in the request"}), 400

        if not uploaded_file.filename:
            uploaded_file.filename = f"upload-{datetime.utcnow():%H%M%S}.bin"

        file_name = uploaded_file.filename
        file_type = uploaded_file.mimetype or "application/octet-stream"
        kind = "pdf" if file_type.startswith("application/pdf") or file_name.lower().endswith(".pdf") else "image"
        try:
            validate_upload(kind, uploaded_file)
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 413

        key = safe_key(file_name)
        blob = storage_client.bucket(bucket_name).blob(key)
        blob.upload_from_file(uploaded_file, content_type=file_type)

        public_url = f"https://storage.googleapis.com/{bucket_name}/{key}"
        logger.info("[proxied.upload] ok key=%s type=%s", key, file_type)
        return jsonify({"status": "ok", "publicUrl": public_url})
    except Exception as e:
        import google.cloud.storage as gcs
        logger.exception("proxied_upload failed (gcs_version=%s)", getattr(gcs, "__version__", "unknown"))
        return jsonify({"error": str(e)}), 500

@app.post("/debug/direct-upload")
def debug_direct_upload():
    try:
        if not os.environ.get("GCS_BUCKET"):
            return jsonify({"error": "GCS_BUCKET env var missing or empty"}), 500
        bucket = storage_client.bucket(os.environ["GCS_BUCKET"])
        blob = bucket.blob(f"debug/{datetime.utcnow():%Y%m%dT%H%M%SZ}.txt")
        blob.upload_from_string(f"hello from cloud run at {datetime.utcnow()}")
        return jsonify({"status": "ok", "name": blob.name, "bucket": os.environ["GCS_BUCKET"]})
    except Exception as e:
        logger.exception("debug/direct-upload failed")
        return jsonify({"error": str(e)}), 500

# ------------------------------------------------------------------------------
# Migrate (MODIFIED to add is_validated columns)
# ------------------------------------------------------------------------------
@app.route("/migrate", methods=["POST"])
def migrate():
    conn = getconn()
    try:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS hosts (
              id SERIAL PRIMARY KEY,
              name TEXT UNIQUE NOT NULL,
              phone TEXT,
              email TEXT
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS venues (
              id SERIAL PRIMARY KEY,
              name TEXT UNIQUE NOT NULL,
              default_day TEXT,
              default_time TEXT
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
              id SERIAL PRIMARY KEY,
              host_id INT REFERENCES hosts(id),
              venue_id INT REFERENCES venues(id),
              event_date DATE NOT NULL,
              highlights TEXT,
              pdf_url TEXT,
              ai_recap TEXT,
              status TEXT DEFAULT 'unposted',
              fb_event_url TEXT,
              created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        # Add is_validated to events if not exists
        cur.execute("""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='events' AND column_name='is_validated'
          ) THEN
            ALTER TABLE events ADD COLUMN is_validated BOOLEAN DEFAULT FALSE;
          END IF;
        END$$;
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS event_photos (
              id SERIAL PRIMARY KEY,
              event_id INT REFERENCES events(id) ON DELETE CASCADE,
              photo_url TEXT
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS event_participation (
              id SERIAL PRIMARY KEY,
              event_id INT REFERENCES events(id) ON DELETE CASCADE,
              team_name TEXT,
              tournament_team_id INT,
              score INT,
              position INT,
              num_players INT,
              is_visiting BOOLEAN DEFAULT FALSE
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS event_parse_log (
              id SERIAL PRIMARY KEY,
              event_id INT REFERENCES events(id) ON DELETE CASCADE,
              raw_text_gz BYTEA,
              parsed_json JSONB,
              status TEXT,
              error TEXT,
              created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tournament_teams (
              id SERIAL PRIMARY KEY,
              name TEXT UNIQUE NOT NULL,
              home_venue_id INT REFERENCES venues(id),
              captain_name TEXT,
              captain_email TEXT,
              captain_phone TEXT,
              player_count INT,
              created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        cur.execute("""
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uniq_venue_date'
              ) THEN
                ALTER TABLE events
                  ADD CONSTRAINT uniq_venue_date UNIQUE (venue_id, event_date);
              END IF;
            END$$;
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tournament_weeks (
              id SERIAL PRIMARY KEY,
              week_ending DATE UNIQUE NOT NULL,
              created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tournament_team_scores (
              id SERIAL PRIMARY KEY,
              team_name TEXT NOT NULL,
              venue_id INT REFERENCES venues(id) NOT NULL,
              week_id INT REFERENCES tournament_weeks(id) NOT NULL,
              points INT DEFAULT 0,
              num_players INT,
              UNIQUE (venue_id, team_name, week_id)
            );
        """)

        # Add is_validated to tournament_team_scores if not exists
        cur.execute("""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='tournament_team_scores' AND column_name='is_validated'
          ) THEN
            ALTER TABLE tournament_team_scores ADD COLUMN is_validated BOOLEAN DEFAULT FALSE;
          END IF;
        END$$;
        """)

        # Add missing column is_tournament if not present
        cur.execute("""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='event_participation' AND column_name='is_tournament'
          ) THEN
            ALTER TABLE event_participation ADD COLUMN is_tournament BOOLEAN DEFAULT FALSE;
          END IF;
        END$$;
        """)

        cur.execute("""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='events' AND column_name='show_type'
          ) THEN
            ALTER TABLE events ADD COLUMN show_type TEXT DEFAULT 'gsp';
            -- optional constraint:
            -- ALTER TABLE events ADD CONSTRAINT chk_events_show_type CHECK (show_type IN ('gsp','musingo','private'));
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='events' AND column_name='updated_at'
          ) THEN
            ALTER TABLE events ADD COLUMN updated_at TIMESTAMP;
          END IF;
        END$$;
        """)

        cur.execute("""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='event_participation' AND column_name='updated_at'
          ) THEN
            ALTER TABLE event_participation ADD COLUMN updated_at TIMESTAMP;
          END IF;
        END$$;
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_event_photos_event ON event_photos(event_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_event_participation_event_pos ON event_participation(event_id, position)")

        conn.commit()
        return jsonify({"status": "ok", "message": "Tables created/verified"})
    except Exception:
        conn.rollback()
        logger.exception("migrate failed")
        return jsonify({"status": "error"}), 500
    finally:
        conn.close()

# ------------------------------------------------------------------------------
# Health (unchanged)
# ------------------------------------------------------------------------------
@app.get("/doctor")
def doctor():
    try:
        if all([PGHOST, PGDATABASE, PGUSER, PGPASSWORD]):
            conn = getconn()
            cur = conn.cursor()
            cur.execute("SELECT 1;")
            val = int(cur.fetchone()[0])
            cur.close()
            conn.close()
        else:
            val = 1
        return jsonify({"status": "ok", "db": val})
    except Exception as e:
        logger.exception("doctor failed")
        return jsonify({"status": "error", "message": str(e)}), 500

# ------------------------------------------------------------------------------
# Reference data (unchanged)
# ------------------------------------------------------------------------------
@app.route("/hosts")
def get_hosts():
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM hosts ORDER BY name;")
        rows = cur.fetchall()
        return jsonify([{"id": r[0], "name": r[1]} for r in rows])
    finally:
        conn.close()

@app.route("/venues")
def get_venues():
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, default_day, default_time FROM venues ORDER BY name;")
        rows = cur.fetchall()
        return jsonify([
            {"id": r[0], "name": r[1], "default_day": r[2], "default_time": r[3]}
            for r in rows
        ])
    finally:
        conn.close()

# ------------------------------------------------------------------------------
# Create Event (NO CHANGES NEEDED - `is_validated` defaults to FALSE in DB)
# ------------------------------------------------------------------------------
def resolve_host_venue(cur, host_name, venue_name):
    host_id = None
    venue_id = None

    if host_name:
        cur.execute("SELECT id FROM hosts WHERE lower(name)=lower(%s)", (host_name,))
        r = cur.fetchone()
        if r:
            host_id = r[0]
        else:
            cur.execute("INSERT INTO hosts (name) VALUES (%s) RETURNING id;", (host_name,))
            host_id = cur.fetchone()[0]

    if venue_name:
        cur.execute("SELECT id FROM venues WHERE lower(name)=lower(%s)", (venue_name,))
        r = cur.fetchone()
        if r:
            venue_id = r[0]
        else:
            cur.execute("INSERT INTO venues (name) VALUES (%s) RETURNING id;", (venue_name,))
            venue_id = cur.fetchone()[0]

    return host_id, venue_id

@app.post("/create-event")
def create_event():
    d = request.json or {}

    host_id = d.get("hostId")
    venue_id = d.get("venueId")
    host_name = d.get("hostName")
    venue_name = d.get("venueName")
    event_date = d.get("eventDate")
    highlights = (d.get("highlights") or "").strip()
    pdf_url = (d.get("pdfUrl") or "").strip()
    photo_urls = d.get("photoUrls") or []

    missing = []
    if not (host_id or host_name):
        missing.append("hostId or hostName")
    if not (venue_id or venue_name):
        missing.append("venueId or venueName")
    if not event_date:
        missing.append("eventDate")
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    conn = getconn()
    try:
        cur = conn.cursor()

        if not host_id and host_name:
            cur.execute("SELECT id FROM hosts WHERE lower(name)=lower(%s)", (host_name,))
            r = cur.fetchone()
            if r:
                host_id = r[0]
            else:
                cur.execute("INSERT INTO hosts (name) VALUES (%s) RETURNING id", (host_name,))
                host_id = cur.fetchone()[0]

        if not venue_id and venue_name:
            cur.execute("SELECT id FROM venues WHERE lower(name)=lower(%s)", (venue_name,))
            r = cur.fetchone()
            if r:
                venue_id = r[0]
            else:
                cur.execute("INSERT INTO venues (name) VALUES (%s) RETURNING id", (venue_name,))
                venue_id = cur.fetchone()[0]

        # `is_validated` column will automatically default to FALSE
        cur.execute(
            """
            INSERT INTO events (host_id, venue_id, event_date, highlights, pdf_url, status)
            VALUES (%s,%s,%s,%s,%s,'unposted')
            ON CONFLICT (venue_id, event_date)
            DO UPDATE SET
              host_id = EXCLUDED.host_id,
              highlights = COALESCE(NULLIF(EXCLUDED.highlights, ''), events.highlights),
              pdf_url = COALESCE(NULLIF(EXCLUDED.pdf_url, ''), events.pdf_url)
            RETURNING id;
            """,
            (host_id, venue_id, event_date, highlights, pdf_url),
        )
        event_id = cur.fetchone()[0]

        for url in set(photo_urls):
            cur.execute(
                """
                INSERT INTO event_photos (event_id, photo_url)
                SELECT %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM event_photos WHERE event_id=%s AND photo_url=%s
                );
                """,
                (event_id, url, event_id, url),
            )

        conn.commit()
        logger.info("Event created id=%s pdf=%s photos=%s", event_id, bool(pdf_url), len(photo_urls))

        try:
            if pdf_url:
                rq.post(f"https://api.gspevents.com/events/{event_id}/parse-pdf", timeout=2)
        except Exception as te:
            logger.warning("Parse trigger failed for event %s: %s", event_id, te)

        return jsonify({
            "status": "ok",
            "eventId": event_id,
            "publicUrl": f"{PUBLIC_BASE}/host-event.html?id={event_id}",
        })
    except Exception as e:
        conn.rollback()
        logger.exception("create-event failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# ------------------------------------------------------------------------------
# Events list/detail/status (MODIFIED to filter by is_validated for SMM)
# ------------------------------------------------------------------------------
@app.get("/events")
def list_events():
    st = request.args.get("status")
    conn = getconn()
    try:
        cur = conn.cursor()
        query_parts = """
            SELECT e.id, e.event_date, e.status, h.name, v.name, e.is_validated
            FROM events e
            LEFT JOIN hosts h ON e.host_id=h.id
            LEFT JOIN venues v ON e.venue_id=v.id
        """
        params = []
        where_clauses = []

        if st:
            where_clauses.append("e.status=%s")
            params.append(st)
            # SMM only sees validated events, so add this filter
            where_clauses.append("e.is_validated=TRUE")
        # If no status is provided, this general /events list will *not* filter by is_validated,
        # allowing admins to see all (validated or not) via this general route if needed,
        # or rely on /admin/events which has explicit filters.

        if where_clauses:
            query_parts += " WHERE " + " AND ".join(where_clauses)
        
        query_parts += " ORDER BY e.event_date DESC;"
        
        cur.execute(query_parts, tuple(params))
        rows = cur.fetchall()
        return jsonify([{
            "id": r[0],
            "date": r[1].isoformat() if r[1] else None,
            "status": r[2],
            "host": r[3],
            "venue": r[4],
            "is_validated": r[5], # New field
        } for r in rows])
    finally:
        conn.close()

@app.get("/events/<int:eid>")
def event_details(eid):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.id,
                   e.event_date,
                   e.highlights,
                   e.pdf_url,
                   e.ai_recap,
                   e.status,
                   e.fb_event_url,
                   h.name AS host_name,
                   v.name AS venue_name,
                   v.default_day,
                   v.default_time,
                   e.is_validated          -- NEW FIELD
            FROM events e
            LEFT JOIN hosts h ON e.host_id = h.id
            LEFT JOIN venues v ON e.venue_id = v.id
            WHERE e.id = %s;
        """, (eid,))
        e = cur.fetchone()
        if not e:
            return jsonify({"error": "not found"}), 404

        cur.execute("SELECT photo_url FROM event_photos WHERE event_id=%s ORDER BY id;", (eid,))
        photos = [r[0] for r in cur.fetchall()]

        has_pdf = bool(e[3])
        has_ai = bool((e[4] or "").strip())
        public_pdf_url = e[3]

        payload = {
            "id": e[0],
            "event_date": e[1].isoformat() if e[1] else None,
            "highlights": e[2],
            "pdf_url": e[3],
            "public_pdf_url": public_pdf_url,
            "ai_recap": e[4],
            "status": e[5],
            "fb_event_url": e[6],
            "host": e[7],
            "venue": e[8],
            "venue_default_day": e[9],
            "venue_default_time": e[10],
            "is_validated": e[11], # NEW FIELD
            "photos": photos,
            "photo_count": len(photos),
            "has_pdf": has_pdf,
            "has_ai": has_ai,
            "public_url": f"{PUBLIC_BASE}/host-event.html?id={eid}",
        }
        return jsonify(payload)
    finally:
        conn.close()

@app.post("/events/<int:eid>/add-photo")
def add_photo_to_event(eid):
    try:
        if not GCS_BUCKET:
            return jsonify({"error": "GCS_BUCKET env var missing"}), 500

        # Verify event exists
        conn = getconn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM events WHERE id=%s;", (eid,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return jsonify({"error": f"Event ID {eid} not found"}), 404

        # Accept standard multipart or fallback to raw body
        uploaded_file = (
            request.files.get("file")
            or request.files.get("photo")
            or (next(iter(request.files.values())) if request.files else None)
        )

        is_raw = False
        raw_stream = None
        filename = None
        content_type = None
        stream_for_upload = None

        if uploaded_file:
            filename = getattr(uploaded_file, "filename", None) or f"photo-{datetime.utcnow():%H%M%S}.jpg"
            content_type = (getattr(uploaded_file, "mimetype", None) or "").lower() or "image/jpeg"
            # Validate and use uploaded_file.stream for size calculations
            try:
                validate_upload("image", uploaded_file)
            except ValueError as ve:
                logger.warning("[upload.photo] rejected: ct=%s name=%s err=%s",
                               (getattr(uploaded_file, "mimetype", None) or "n/a"),
                               filename, str(ve))
                return jsonify({"error": str(ve)}), 413
            stream_for_upload = uploaded_file  # Flask FileStorage is fine here
        else:
            # Fallback: raw binary body (no multipart). Some iOS cases.
            if request.data:
                is_raw = True
                filename = f"photo-{datetime.utcnow():%H%M%S}.jpg"
                content_type = (request.headers.get("Content-Type") or "").lower() or "image/jpeg"
                raw_stream = BytesIO(request.data)
                # Build a tiny shim with attributes our validate_upload expects
                class _RawShim:
                    def __init__(self, fn, ct, stream):
                        self.filename = fn
                        self.mimetype = ct
                        self.stream = stream
                shim = _RawShim(filename, content_type, raw_stream)
                try:
                    validate_upload("image", shim)
                except ValueError as ve:
                    logger.warning("[upload.photo] raw rejected: ct=%s name=%s err=%s",
                                   content_type, filename, str(ve))
                    return jsonify({"error": str(ve)}), 413
                stream_for_upload = raw_stream
            else:
                logger.warning(
                    "[upload.photo] no file field; ct=%s cl=%s ua=%s keys=%s",
                    request.headers.get("Content-Type"),
                    request.headers.get("Content-Length"),
                    request.headers.get("User-Agent"),
                    list(request.files.keys()),
                )
                return jsonify({"error": "No file in request (expect 'file' form field)"}), 400

        # Upload to GCS
        key = safe_key(filename)
        blob = storage_client.bucket(GCS_BUCKET).blob(key)

        # Ensure stream at start and provide size for raw so resumable upload doesn't call tell on wrapper
        if is_raw:
            stream_for_upload.seek(0)
            size = len(request.data)
            blob.upload_from_file(
                stream_for_upload,
                size=size,
                content_type=content_type or "image/jpeg",
            )
        else:
            # FileStorage supports tell/seek internally; let client library handle size
            blob.upload_from_file(
                stream_for_upload,
                content_type=(getattr(uploaded_file, "mimetype", None) or "image/jpeg"),
            )

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{key}"

        # Record in DB
        cur.execute(
            "INSERT INTO event_photos (event_id, photo_url) VALUES (%s, %s) RETURNING id;",
            (eid, public_url),
        )
        photo_db_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        logger.info("[upload.photo] ok event=%s key=%s raw=%s", eid, key, is_raw)
        return jsonify({"status": "ok", "photoId": photo_db_id, "photoUrl": public_url}), 200

    except Exception as e:
        logger.exception("add_photo_to_event failed")
        try:
            if 'conn' in locals() and conn:
                conn.rollback()
                conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

@app.post("/events/<int:eid>/add-photo-url")
def add_photo_by_url(eid):
    d = request.json or {}
    url = (d.get("photoUrl") or "").strip()
    if not url.startswith("http"):
        return jsonify({"error": "photoUrl required"}), 400

    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM events WHERE id=%s;", (eid,))
        if not cur.fetchone():
            return jsonify({"error": "event not found"}), 404

        cur.execute(
            "INSERT INTO event_photos (event_id, photo_url) VALUES (%s, %s) RETURNING id;",
            (eid, url),
        )
        pid = cur.fetchone()[0]
        conn.commit()
        return jsonify({"status": "ok", "photoId": pid, "photoUrl": url})
    except Exception as e:
        conn.rollback()
        logger.exception("add_photo_by_url failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.put("/events/<int:eid>/status")
def update_status(eid):
    d = request.get_json(silent=True) or {}
    new_status = d.get("status")
    fb_url = d.get("fb_event_url")
    if new_status == "posted" and not fb_url:
        return jsonify({"error": "fb_event_url required to mark posted"}), 400

    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE events SET status=%s, fb_event_url=COALESCE(%s, fb_event_url) WHERE id=%s;",
            (new_status, fb_url, eid),
        )
        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        conn.close()

@app.put("/events/<int:eid>/ai")
def update_ai_text(eid):
    d = request.get_json(silent=True) or {}
    text = (d.get("text") or "").strip()
    if not text:
        return jsonify({"error":"text required"}), 400
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE events SET ai_recap=%s WHERE id=%s", (text, eid))
        conn.commit()
        return jsonify({"status":"ok"})
    finally:
        conn.close()

# ------------------------------------------------------------------------------
# Admin events (MODIFIED for admin_event_detail & NEW for validation)
# ------------------------------------------------------------------------------
# Admin List of Events - No change needed here, the `list_events` already returns
# `is_validated`. Admin UI can display/filter based on that.
@app.get("/admin/events")
def admin_list_events():
    q = (request.args.get("q") or "").strip()
    show_type = (request.args.get("show_type") or "").strip()  # 'gsp','musingo','private'
    status_f = (request.args.get("status") or "").strip()
    start = (request.args.get("start") or "").strip()  # YYYY-MM-DD
    end = (request.args.get("end") or "").strip()
    limit = min(int(request.args.get("limit", "200")), 1000)

    conn = getconn()
    try:
        cur = conn.cursor()
        clauses = []
        params = []
        base = """
            SELECT e.id, e.event_date, COALESCE(e.show_type,'gsp') AS show_type,
                   e.status, h.name AS host, v.name AS venue,
                   e.pdf_url, e.ai_recap, e.is_validated -- NEW: include is_validated
            FROM events e
            LEFT JOIN hosts h ON e.host_id=h.id
            LEFT JOIN venues v ON e.venue_id=v.id
        """
        if q:
            clauses.append("(LOWER(h.name) LIKE LOWER(%s) OR LOWER(v.name) LIKE LOWER(%s))")
            params.extend([f"%{q}%", f"%{q}%"])
        if show_type:
            clauses.append("COALESCE(e.show_type,'gsp') = %s")
            params.append(show_type)
        if status_f:
            clauses.append("e.status = %s")
            params.append(status_f)
        if start:
            clauses.append("e.event_date >= %s")
            params.append(start)
        if end:
            clauses.append("e.event_date <= %s")
            params.append(end)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order = " ORDER BY e.event_date DESC, e.id DESC"
        sql = base + where + order + f" LIMIT {limit}"
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        return jsonify([{
            "id": r[0],
            "event_date": r[1].isoformat() if r[1] else None,
            "show_type": r[2],
            "status": r[3],
            "host": r[4],
            "venue": r[5],
            "pdf_url": r[6],
            "has_ai": bool((r[7] or "").strip()),
            "is_validated": r[8], # NEW FIELD
        } for r in rows])
    finally:
        conn.close()

@app.get("/admin/events/<int:eid>")
def admin_event_detail(eid):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.id, e.event_date, COALESCE(e.show_type,'gsp'), e.highlights,
                   e.pdf_url, e.ai_recap, e.status, e.fb_event_url,
                   h.id, h.name, v.id, v.name, v.default_day, v.default_time,
                   e.is_validated         -- NEW FIELD
            FROM events e
            LEFT JOIN hosts h ON e.host_id=h.id
            LEFT JOIN venues v ON e.venue_id=v.id
            WHERE e.id=%s
        """, (eid,))
        e = cur.fetchone()
        if not e:
            return jsonify({"error":"not found"}), 404

        cur.execute("""
            SELECT team_name, score, position, num_players, is_visiting, is_tournament
            FROM event_participation
            WHERE event_id=%s
            ORDER BY position ASC, id ASC
        """, (eid,))
        parts = [{
            "team_name": r[0], "score": r[1], "position": r[2],
            "num_players": r[3], "is_visiting": r[4], "is_tournament": r[5]
        } for r in cur.fetchall()]

        cur.execute("SELECT photo_url FROM event_photos WHERE event_id=%s ORDER BY id", (eid,))
        photos = [r[0] for r in cur.fetchall()]

        return jsonify({
            "id": e[0],
            "event_date": e[1].isoformat() if e[1] else None,
            "show_type": e[2],
            "highlights": e[3],
            "pdf_url": e[4],
            "ai_recap": e[5],
            "status": e[6],
            "fb_event_url": e[7],
            "host": {"id": e[8], "name": e[9]},
            "venue": {"id": e[10], "name": e[11], "default_day": e[12], "default_time": e[13]},
            "is_validated": e[14], # NEW FIELD
            "participation": parts,
            "photos": photos
        })
    finally:
        conn.close()

# Partial update core event fields - ADDED is_validated to allowed fields
@app.put("/admin/events/<int:eid>")
def admin_update_event(eid):
    d = request.json or {}
    allowed = {
        "show_type", "event_date", "host_id", "venue_id",
        "highlights", "pdf_url", "ai_recap", "status", "fb_event_url",
        "is_validated" # NEW: Allow admin to update validation status here too
    }
    sets, params = [], []
    for k, v in d.items():
        if k in allowed:
            sets.append(f"{k} = %s")
            params.append(v)
    if not sets:
        return jsonify({"error":"no fields to update"}), 400
    params.append(eid)

    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM events WHERE id=%s", (eid,))
        if not cur.fetchone():
            return jsonify({"error":"not found"}), 404
        cur.execute(f"UPDATE events SET {', '.join(sets)}, updated_at=NOW() WHERE id=%s", tuple(params))
        conn.commit()
        return jsonify({"status":"ok"})
    except Exception as e:
        conn.rollback()
        logger.exception("admin_update_event failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# NEW ADMIN ENDPOINT: Validate Event (explicit route)
@app.put("/admin/events/<int:eid>/validate")
def admin_validate_event(eid):
    d = request.get_json(silent=True) or {}
    validate_status = bool(d.get("is_validated", True)) # Default to True if not provided

    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE events SET is_validated=%s, updated_at=NOW() WHERE id=%s;",
                    (validate_status, eid))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "event not found"}), 404
        return jsonify({"status": "ok", "is_validated": validate_status})
    except Exception as e:
        conn.rollback()
        logger.exception(f"admin_validate_event for event {eid} failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# Replace participation (rankings) (unchanged)
@app.put("/admin/events/<int:eid>/participation")
def admin_replace_participation(eid):
    d = request.json or {}
    teams = d.get("teams") or []  # [{team_name, score, position, num_players, is_visiting, is_tournament}]
    if not isinstance(teams, list):
        return jsonify({"error":"teams must be an array"}), 400

    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM event_participation WHERE event_id=%s", (eid,))
        for t in teams:
            cur.execute("""
                INSERT INTO event_participation
                (event_id, team_name, score, position, num_players, is_visiting, is_tournament, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
            """, (
                eid, t.get("team_name"), t.get("score"), t.get("position"),
                t.get("num_players"), bool(t.get("is_visiting")), bool(t.get("is_tournament"))
            ))
        conn.commit()
        return jsonify({"status":"ok", "count": len(teams)})
    except Exception as e:
        conn.rollback()
        logger.exception("admin_replace_participation failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# Add/remove photo by URL (unchanged)
@app.post("/admin/events/<int:eid>/photos")
def admin_add_photo_url(eid):
    d = request.json or {}
    url = (d.get("photoUrl") or "").strip()
    if not url.startswith("http"):
        return jsonify({"error":"photoUrl required"}), 400
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO event_photos (event_id, photo_url) VALUES (%s,%s) RETURNING id", (eid, url))
        pid = cur.fetchone()[0]
        conn.commit()
        return jsonify({"status":"ok", "photoId": pid})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.delete("/admin/events/<int:eid>/photos")
def admin_delete_photo_url(eid):
    url = (request.args.get("photoUrl") or "").strip()
    if not url:
        return jsonify({"error":"photoUrl required"}), 400
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM event_photos WHERE event_id=%s AND photo_url=%s", (eid, url))
        conn.commit()
        return jsonify({"status":"ok"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# ------------------------------------------------------------------------------
# Tournament Admin (MODIFIED for PUT, NEW for validation)
# ------------------------------------------------------------------------------
@app.get("/admin/tournament/scores")
def get_tournament_scores():
    venue_id = request.args.get("venue_id")
    week_ending = request.args.get("week_ending")
    if not venue_id or not week_ending:
        return jsonify({"error":"venue_id and week_ending required"}), 400
    conn = getconn()
    try:
        cur = conn.cursor()
        # Ensure week
        cur.execute("SELECT id FROM tournament_weeks WHERE week_ending=%s", (week_ending,))
        w = cur.fetchone()
        if not w:
            return jsonify({"rows": []})
        week_id = w[0]
        cur.execute("""
          SELECT team_name, points, num_players, is_validated -- NEW: Include validation status
          FROM tournament_team_scores
          WHERE venue_id=%s AND week_id=%s
          ORDER BY points DESC NULLS LAST, team_name ASC
        """, (venue_id, week_id))
        rows = [{"team_name": r[0], "points": r[1], "num_players": r[2], "is_validated": r[3]} for r in cur.fetchall()]
        return jsonify({"rows": rows})
    finally:
        conn.close()

@app.post("/admin/parse-all")
def parse_all_events():
    limit = int(request.args.get("limit", "500"))
    conn = getconn()
    results = {"attempted":0, "success":0, "failed":0, "errors":[]}
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM events WHERE pdf_url IS NOT NULL ORDER BY id DESC LIMIT %s;", (limit,))
        ids = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        for eid in ids:
            results["attempted"] += 1
            try:
                r = rq.post(f"https://api.gspevents.com/events/{eid}/parse-pdf", timeout=30)
                if r.ok:
                    js = r.json()
                    if js.get("status") == "success":
                        results["success"] += 1
                    else:
                        results["failed"] += 1
                        results["errors"].append({"event":eid, "msg":"parse non-success"})
                else:
                    results["failed"] += 1
                    results["errors"].append({"event":eid, "msg":f"HTTP {r.status_code}"})
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"event":eid, "msg":str(e)})
        return jsonify(results)
    except Exception as e:
        logger.exception("parse_all_events failed")
        return jsonify({"error": str(e), "partial": results}), 500

@app.put("/admin/tournament/scores")
def put_tournament_scores():
    d = request.json or {}
    venue_id = d.get("venue_id")
    week_ending = d.get("week_ending")
    rows = d.get("rows", [])

    if not venue_id or not week_ending:
        return jsonify({"error": "venue_id and week_ending required"}), 400
    
    conn = getconn()
    try:
        cur = conn.cursor()
        
        # Ensure week_ending exists and get its ID
        cur.execute("SELECT id FROM tournament_weeks WHERE week_ending=%s;", (week_ending,))
        week_row = cur.fetchone()
        if not week_row:
            return jsonify({"error": "week_ending not found"}), 404
        week_id = week_row[0]

        # Delete existing scores for this venue and week before inserting new ones
        cur.execute("DELETE FROM tournament_team_scores WHERE venue_id=%s AND week_id=%s;", (venue_id, week_id))

        for r in rows:
            team_name = (r.get("team_name") or "").strip()
            points = r.get("points")
            num_players = r.get("num_players")

            if team_name: # Only insert if team_name is provided
                cur.execute(
                    """
                    INSERT INTO tournament_team_scores
                      (team_name, venue_id, week_id, points, num_players, is_validated)
                    VALUES (%s,%s,%s,%s,%s,FALSE) -- NEW: Always FALSE by default when scores are updated
                    """,
                    (team_name, venue_id, week_id, points, num_players)
                )
        conn.commit()
        return jsonify({"status": "ok", "count": len(rows)})
    except Exception as e:
        conn.rollback()
        logger.exception("put_tournament_scores failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# NEW ADMIN ENDPOINT: Validate Tournament Scores
@app.put("/admin/tournament/scores/<int:venue_id>/<string:week_ending>/validate")
def admin_validate_tournament_scores(venue_id, week_ending):
    d = request.get_json(silent=True) or {}
    validate_status = bool(d.get("is_validated", True)) # Default to True

    conn = getconn()
    try:
        cur = conn.cursor()
        
        # Ensure week_ending exists and get its ID
        cur.execute("SELECT id FROM tournament_weeks WHERE week_ending=%s;", (week_ending,))
        week_row = cur.fetchone()
        if not week_row:
            return jsonify({"error": "week_ending not found"}), 404
        week_id = week_row[0]

        cur.execute(
            """
            UPDATE tournament_team_scores
            SET is_validated=%s
            WHERE venue_id=%s AND week_id=%s;
            """,
            (validate_status, venue_id, week_id)
        )
        conn.commit()
        return jsonify({"status": "ok", "is_validated": validate_status, "venue_id": venue_id, "week_ending": week_ending})
    except Exception as e:
        conn.rollback()
        logger.exception(f"admin_validate_tournament_scores for venue {venue_id}, week {week_ending} failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# ------------------------------------------------------------------------------
# Public tournament scores (MODIFIED to filter by is_validated)
# ------------------------------------------------------------------------------
@app.get("/pub/tournament/scores")
def pub_scores():
    venue_id = request.args.get("venue_id")
    week_ending = request.args.get("week_ending")
    if not venue_id or not week_ending:
        return jsonify({"error":"venue_id and week_ending required"}), 400
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM tournament_weeks WHERE week_ending=%s", (week_ending,))
        w = cur.fetchone()
        if not w: return jsonify({"venue_id": int(venue_id), "week_ending": week_ending, "rows": []})
        week_id = w[0]
        cur.execute("""
            SELECT team_name, points, num_players
            FROM tournament_team_scores
            WHERE venue_id=%s AND week_id=%s AND is_validated=TRUE -- NEW: Filter by validation
            ORDER BY points DESC NULLS LAST, team_name ASC
        """, (venue_id, week_id))
        rows = [{"team_name": r[0], "points": r[1], "num_players": r[2]} for r in cur.fetchall()]
        return jsonify({"venue_id": int(venue_id), "week_ending": week_ending, "rows": rows})
    finally:
        conn.close()

@app.get("/pub/tournament/venue/<slug>/<date>")
def pub_venue_week(slug, date):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM venues")
        rows = cur.fetchall()
        by_slug = { re.sub(r'[^a-z0-9]+','-', (r[1] or '').lower()).strip('-') : r for r in rows }
        if slug not in by_slug: return jsonify({"error":"not found"}), 404
        vid, vname = by_slug[slug]
        
        cur.execute("SELECT id FROM tournament_weeks WHERE week_ending=%s", (date,))
        w = cur.fetchone()
        if not w: return jsonify({"venue": {"id": vid, "name": vname, "slug": slug}, "week_ending": date, "rows": []})
        week_id = w[0]
        cur.execute("""
            SELECT team_name, points, num_players
            FROM tournament_team_scores
            WHERE venue_id=%s AND week_id=%s AND is_validated=TRUE -- NEW: Filter by validation
            ORDER BY points DESC NULLS LAST, team_name ASC
        """, (vid, week_id))
        rows = [{"team_name": r[0], "points": r[1], "num_players": r[2]} for r in cur.fetchall()]
        return jsonify({"venue": {"id": vid, "name": vname, "slug": slug}, "week_ending": date, "rows": rows})
    finally:
        conn.close()


# ------------------------------------------------------------------------------
# NEW PUBLIC ENDPOINT: Venue Stats for Owners
# ------------------------------------------------------------------------------
@app.get("/pub/venues/<slug>/stats")
def pub_venue_stats(slug):
    conn = getconn()
    try:
        cur = conn.cursor()

        # Find venue by slug
        cur.execute("SELECT id, name, default_day, default_time FROM venues")
        rows = cur.fetchall()
        # This slugify logic should match your frontend's slug generation
        by_slug = { re.sub(r'[^a-z0-9]+','-', (r[1] or '').lower()).strip('-') : r for r in rows }
        if slug not in by_slug:
            return jsonify({"error":"Venue not found"}), 404
        
        venue_id, venue_name, default_day, default_time = by_slug[slug]

        # Get all VALIDATED events for this venue, including host and aggregated participation stats
        cur.execute("""
            SELECT
                e.event_date,
                h.name AS host_name,
                COUNT(ep.id) AS num_teams,
                SUM(ep.num_players) AS num_players_total
            FROM events e
            LEFT JOIN hosts h ON e.host_id = h.id
            LEFT JOIN event_participation ep ON e.id = ep.event_id
            WHERE e.venue_id = %s AND e.is_validated = TRUE -- Filter for validated events
            GROUP BY e.id, e.event_date, h.name
            ORDER BY e.event_date DESC;
        """, (venue_id,))
        
        event_stats = []
        for r in cur.fetchall():
            event_stats.append({
                "event_date": r[0].isoformat() if r[0] else None,
                "host_name": r[1],
                "num_teams": int(r[2]) if r[2] else 0, # Ensure integer conversion for COUNT
                "num_players": int(r[3]) if r[3] else 0, # Ensure integer conversion for SUM
            })
        
        return jsonify({
            "venue_name": venue_name,
            "default_day": default_day,
            "default_time": default_time,
            "events": event_stats,
            "event_count": len(event_stats)
        })
    except Exception as e:
        logger.exception(f"pub_venue_stats for slug {slug} failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# ------------------------------------------------------------------------------
# Entrypoint (unchanged)
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))