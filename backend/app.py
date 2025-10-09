# app.py
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
import difflib
import zipfile
from datetime import date, timedelta

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
# App + CORS
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
# Config
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
# Optional token gate (disable by leaving HOST_API_TOKEN unset)
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
# Runtime SA diagnostics helper
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
# DB conn
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
# Upload helpers
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

# Adjectives and AI recap (unchanged)
AI_ADJECTIVES = [
    "a fantastic", "an electric", "a high‑energy", "an unforgettable", "a spirited",
    "a lively", "a jam‑packed", "a fun‑filled", "an epic", "a legendary", "an exhilarating",
    "a rowdy", "a buzzing", "a memorable", "a thrilling", "an excellent",
    "a super fun", "an intense", "a breathtaking", "a riveting", "an awesome", "a captivating",
    "a competitive", "a dynamic", "a playful", "a spectacular", "a pulse-pounding",
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

def format_ai_recap(event_data: dict, winners: list, venue_defaults: dict, adjective=None):
    """
    Generates an AI recap.
    event_data is expected to be a dictionary with keys like 'venue_name', 'host_name', etc.
    The 'brand' in the recap is now dynamically determined by 'show_type'.
    """
    venue = (event_data.get("venue_name") or "").strip()
    host = (event_data.get("host_name") or "").strip()
    highlights = (event_data.get("highlights") or "").strip()
    dt = event_data.get("event_date")
    date_str = _fmt_event_date_human(dt)
    # fb_event_url is intentionally ignored here (no longer printed in recap)
    show_type = (event_data.get("show_type") or "gsp").lower()

    brand_map = {
        "gsp": "Game Show Palooza",
        "musingo": "Musingo",
        "private": "A Private Event",
    }
    brand = brand_map.get(show_type, "Game Show Palooza")

    adj = (adjective or "").strip() or random.choice(AI_ADJECTIVES)

    w1 = winners[0]["name"] if len(winners) > 0 and winners[0].get("name") else ""
    w2 = winners[1]["name"] if len(winners) > 1 and winners[1].get("name") else ""
    w3 = winners[2]["name"] if len(winners) > 2 and winners[2].get("name") else ""

    next_day = (venue_defaults.get("default_day") or "").strip() if isinstance(venue_defaults, dict) else ""
    event_time = (venue_defaults.get("default_time") or "").strip() if isinstance(venue_defaults, dict) else ""

    lines = []

    if date_str:
        if host:
            lines.append(f"It was {adj} night of {brand} at {venue} on {date_str} with host {host}!")
        else:
            lines.append(f"It was {adj} night of {brand} at {venue} on {date_str}!")
    else:
        if host:
            lines.append(f"It was {adj} night of {brand} at {venue} with host {host}!")
        else:
            lines.append(f"It was {adj} night of {brand} at {venue}!")

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

    # IMPORTANT: Do NOT append any Facebook link here. That belongs on the web page UI, not in the recap text.

    return "\n".join(lines).strip()

@app.errorhandler(RequestEntityTooLarge)
def handle_413(_e):
    return jsonify({"error": "Upload too large. PDF max 30 MB, images max 12 MB."}), 413

# ------------------------------------------------------------------------------
# PDF parsing helpers 
# ------------------------------------------------------------------------------
HEADER_KEYWORDS = [
    "WEEK ENDING", "TOTAL", "VENUE", "TEAM NAME", "POINTS", "PLAYERS",
    "FALL", "LEADER BOARD", "TOURNAMENT", "GSP", "EVENT DETAILS",
    "QUIZZES", "PRINT DATE", "QUIZ DATE", "QUIZ FILE", "KEYPAD", "TIME (S)",
    "RANK", "SCORE", "PAGE 1" # Added "PAGE 1" to filter out footer
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
    # New: Aggressively filter lines that contain mostly numbers but are too short for scores,
    # or look like column headers
    if len(s.split()) >= 3 and all(word.isdigit() or re.match(r"[A-Z]\d?", word) for word in s.split()) and "KEYPAD" in upper:
        return True # Looks like a column header line
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
    r = fetch_with_retry(to_direct_download(pdf_url), attempts=3, timeout=60)
    return r.content

def safe_extract_text(pdf_bytes: bytes) -> str:
    try:
        return extract_text(BytesIO(pdf_bytes)) or ""
    except Exception as e:
        logger.warning("pdfminer failed; falling back to pypdf: %s", e)
        try:
            reader = PdfReader(BytesIO(pdf_bytes))
            return "\n".join([p.extract_text() or "" for p in reader.pages])
        except Exception as e2:
            logger.error("pypdf also failed: %s", e2)
            return ""

def extract_players_and_flags(flag_text: str):
    """
    Extracts number of players, and boolean flags for is_tournament (T)
    and is_visiting (V) from a string like "(6T)" or "(4V)".
    A team is considered 'isTournament' if it has either 'T' or 'V' explicitly.
    'isVisiting' implies 'isTournament'.
    """
    if not flag_text:
        return None, False, False # num_players, is_tournament, is_visiting

    t = re.sub(r"\s+", "", str(flag_text).upper())
    m = re.match(r"(\d*)([A-Z]*)", t) # Use \d* for optional digits

    if not m:
        return None, False, False

    num_str = m.group(1)
    flags_str = m.group(2)

    n_players = int(num_str) if num_str else None
    
    has_v = "V" in flags_str
    has_t = ("T" in flags_str) or has_v 

    return n_players, has_t, has_v

def _parse_tabular_format(lines: list[str]):
    """
    Parses PDF text with a clear tabular structure, specifically designed
    for formats like "QuizXpress Analyzer" with "Keypad" and "Time (s)" columns.
    Example line: "1 Jeneral Knowledge (6T) 4 174.37 1967"
    """
    items = []
    
    # NEW PRECISE Regex: Explicitly matches Rank, Team, Flags, then skips the next two number/decimal groups (Keypad, Time(s)), then captures Score.
    pat_full_row_precise = re.compile(
        r"""^\s*
            (?P<rank>\d+)                  # 1. REQUIRED Rank (e.g., '1')
            \s+                            # Whitespace
            (?P<name>[^(\n]+?)             # 2. Team name (e.g., 'Jeneral Knowledge') - non-greedy
            \s*                            # Optional whitespace
            (?:\(\s*(?P<flags>[\d\sTVtv]*)\s*\))? # 3. Optional (Flags) (e.g., '(6T)') - flags can be empty (e.g. ())
            \s*                            # Whitespace
            (?:[\d.]+)?                    # Optional Keypad value (e.g., '4') - non-capturing
            \s*                            # Whitespace
            (?:[\d.]+)?                    # Optional Time (s) value (e.g., '174.37') - non-capturing
            \s*                            # Whitespace
            (?P<score>-?\d+)              # 4. REQUIRED Score (e.g., '1967')
            \s*$""",
        re.VERBOSE | re.IGNORECASE,
    )

    for i, ln in enumerate(lines):
        s = (ln or "").strip()
        if not s or likely_noise_line(s):
            continue

        match = pat_full_row_precise.match(s) # Use the new precise regex
        if match:
            name = (match.group("name") or "").strip(" -–—\t")
            flags_raw = match.group("flags")
            score_str = match.group("score")
            rank_str = match.group("rank")

            nplayers, is_t, is_v = extract_players_and_flags(flags_raw or "")
            score = int(score_str) if score_str else None
            rank = int(rank_str) if rank_str else None

            # Keep filtering out obvious non-teams (like "Whammy") unless they have players.
            # "Whammy (2)" means it's a team named Whammy. "Whammy" alone is noise.
            if "WHAMMY" in name.upper() and (nplayers is None or nplayers == 0) and not name.upper().startswith("TEAM"):
                continue

            items.append({
                "name": name,
                "score": score,
                "playerCount": nplayers or 0,
                "isTournament": bool(is_t), 
                "isVisiting": bool(is_v),
                "position": rank if rank is not None else (len(items) + 1),
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
    pat_team_and_flags = re.compile(
        r"""^\s*
            (?P<rank>\d+)?                  # Optional leading rank (e.g., 1)
            \s*
            (?P<name>[^(\n]+?)             # Capture team name (non-greedy)
            \s*\(\s*(?P<flags>[\d\sTVtv]*)\s*\) # Capture (digits/flags) - flags can be empty
            \s*$""",
        re.VERBOSE | re.IGNORECASE,
    )

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
                "isTournament": bool(is_t), # Correctly boolified
                "isVisiting": bool(is_v),
                "score": None, 
                "position": int(rank_str) if rank_str else None,
                "_raw_line_idx": i
            })
            continue

        match_loose = pat_loose_team_name.match(s)
        if match_loose:
            name = (match_loose.group("name") or "").strip(" -–—\t")
            rank_str = match_loose.group("rank")

            if "WHAMMY" in name.upper() and not name.upper().startswith("TEAM "):
                continue

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

    deduped_teams = []
    seen_names = set()
    for t in sorted(potential_teams, key=lambda x: (x.get('position') if x.get('position') is not None else float('inf'), x.get('_raw_line_idx', float('inf')))):
        if t["name"].lower() not in seen_names:
            seen_names.add(t["name"].lower())
            if t["position"] is None:
                t["position"] = len(deduped_teams) + 1
            deduped_teams.append(t)
    items = deduped_teams

    # --- Score Column Alignment (CRITICAL: this section needed to be preserved) ---
    try:
        teams_n = len(items)
        if teams_n == 0:
            raise ValueError("No teams found for score alignment.")

        text_full = "\n".join(lines)
        segments = re.split(r"\n\s*\n", text_full)

        def classify_score_block(seg_text: str):
            ls = [ln.strip() for ln in seg_text.split("\n") if ln.strip()]
            if not ls: return None
            
            has_score_header = any(header_kw in s.upper() for header_kw in ["SCORE", "POINTS"] for s in ls[:2])
            
            if not has_score_header and not all(re.fullmatch(r"[-+]?\d+", s) for s in ls):
                return None 

            ints = []
            int_like_count = 0
            for s in ls:
                m = re.fullmatch(r"[-+]?\d+", s)
                if m:
                    ints.append(int(s))
                    int_like_count += 1
            
            if len(ls) > 0 and (int_like_count / len(ls) >= 0.7 or has_score_header):
                return { "qualifies": True, "scores": ints, "raw_lines": ls }
            return None

        score_blocks = []
        for seg in segments:
            info = classify_score_block(seg)
            if info and info["qualifies"]:
                score_blocks.append(info)
        
        best_score_block = None
        if score_blocks:
            best_score_block = max(score_blocks, key=lambda x: (len(x['scores']), 'SCORE' in x['raw_lines'][0].upper() or 'POINTS' in x['raw_lines'][0].upper()))

        if best_score_block and best_score_block["scores"]:
            nums = best_score_block["scores"]
            
            if len(nums) == teams_n:
                for j in range(teams_n):
                    items[j]["score"] = nums[j]
            elif len(nums) > teams_n:
                for j in range(teams_n):
                    items[j]["score"] = nums[j]
            else:
                for j in range(len(nums)):
                    items[j]["score"] = nums[j]
    except Exception as e:
        logger.warning(f"Error during split format score alignment: {e}")
        pass

    return {"teams": items, "teamCount": len(items), "playerCount": total_players}

def parse_raw_text(raw: str):
    """
    Extract teams with name, playerCount, isTournament, isVisiting, score, position (rank).
    We will assign position from explicit ranks when available, else by line order.
    Also aligns a trailing numeric Score column to team positions when present.
    """
    items = []
    total_players = 0
    if not raw:
        return {"teams": [], "teamCount": 0, "playerCount": 0}

    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    pat_bracket = re.compile(
        r"""^\s*\[\s*(?P<name>.+?)\s*\(\s*(?P<flags>[\d\sTVtv]+)\s*\)\s*\]
            (?:\s+[-–—]?\s*(?P<score>-?\d+))?\s*$""",
        re.VERBOSE,
    )
    pat_ranked = re.compile(
        r"""^\s*(?:(?P<rank>\d+)[\.\)]\s+)?  
            (?P<name>[^\(\[]+?)
            \s*\(\s*(?P<flags>[\d\sTVtv]+)\s*\)
            (?:\s+[-–—]?\s*(?P<score>-?\d+))?\s*$""",
        re.VERBOSE,
    )
    pat_loose = re.compile(
        r"""^\s*(?P<name>.+?)\s*\(\s*(?P<flags>[\d\sTVtv]+)\s*\)
            (?:\s+[-–—]?\s*(?P<score>-?\d+))?\s*$""",
        re.VERBOSE,
    )

    seq = 0
    for ln in lines:
        s = (ln or "").strip()
        if not s or likely_noise_line(s):
            continue

        name = None
        score = None
        flags_raw = None
        rank = None

        m = pat_bracket.match(s)
        if m:
            name = (m.group("name") or "").strip()
            flags_raw = m.group("flags")
            score = m.group("score")
        else:
            m2 = pat_ranked.match(s)
            if m2:
                name = (m2.group("name") or "").strip(" -–—\t")
                flags_raw = m2.group("flags")
                score = m2.group("score")
                if m2.group("rank"):
                    try:
                        rank = int(m2.group("rank"))
                    except Exception:
                        rank = None
            else:
                m3 = pat_loose.match(s)
                if m3:
                    name = (m3.group("name") or "").strip(" -–—\t")
                    flags_raw = m3.group("flags")
                    score = m3.group("score")

        if not name or not flags_raw:
            continue

        nplayers, is_t, is_v = extract_players_and_flags(flags_raw)
        if score is not None:
            try:
                score = int(score)
            except Exception:
                score = None

        seq += 1
        position = rank if rank is not None else seq

        items.append({
            "name": name,
            "score": score,
            "playerCount": nplayers or 0,
            "isTournament": bool(is_t),
            "isVisiting": bool(is_v),
            "position": position,
        })
        total_players += (nplayers or 0)

    if len(items) > 60:
        items = [t for t in items if t.get("playerCount", 0) > 0 and t.get("name")]

    seen = set()
    deduped = []
    next_pos = 0
    for t in items:
        p = t.get("position")
        if p is None or p in seen:
            next_pos += 1
            t["position"] = next_pos
        else:
            seen.add(p)
        deduped.append(t)
    items = deduped

    # Align trailing "Score" numeric column to positions (best-effort, stricter).
    try:
        teams_n = len(items)
        if teams_n:
            segments = re.split(r"\n\s*\n", text)

            def classify_block(seg_text: str):
                ls = [ln.strip() for ln in seg_text.split("\n") if ln.strip()]
                if not ls:
                    return None
                ints = []
                int_like = 0
                long_ints = 0
                decimals = 0
                for s in ls:
                    if re.fullmatch(r"-?\d+\.\d+", s):
                        decimals += 1
                        continue
                    m = re.fullmatch(r"-?\d+", s)
                    if m:
                        int_like += 1
                        val = int(s)
                        dlen = len(s.lstrip("-"))
                        if 3 <= dlen <= 4:
                            ints.append(val)
                            long_ints += 1
                        elif dlen == 2:
                            ints.append(val)
                total = len(ls)
                if total == 0:
                    return None
                qualifies = (int_like / total) >= 0.6 and (decimals / total) <= 0.2
                return {
                    "qualifies": qualifies,
                    "score_len": len(ints),
                    "score_sized": long_ints,
                    "ints": ints,
                    "total": total,
                }

            candidates = []
            for i, seg in enumerate(segments):
                info = classify_block(seg)
                if not info or not info["qualifies"]:
                    continue
                if info["score_len"] >= max(3, int(info["total"] * 0.5)):
                    candidates.append((i, info))

            if candidates:
                best = None
                best_key = None
                for idx, info in candidates:
                    diff = abs(info["score_len"] - teams_n)
                    key = (idx, -int(info["score_sized"]), diff)
                    if best is None or key > best_key:
                        best = info
                        best_key = key

                if best and best["ints"]:
                    nums = best["ints"]
                    pos_to_score = {}
                    limit = min(len(nums), teams_n)
                    for p in range(1, limit + 1):
                        pos_to_score[p] = nums[p - 1]

                    for t in items:
                        p = t.get("position")
                        if isinstance(p, int) and p in pos_to_score:
                            t["score"] = pos_to_score[p]

                    seq_fill = 1
                    for t in items:
                        if t.get("score") is None:
                            while seq_fill in pos_to_score:
                                seq_fill += 1
                            if seq_fill <= len(nums):
                                t["score"] = nums[seq_fill - 1]
                                seq_fill += 1
    except Exception:
        pass

    return {"teams": items, "teamCount": len(items), "playerCount": total_players}

# ------------------------------------------------------------------------------
# Diagnostics
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

    routes = [
        # health/diag
        "GET /doctor",
        "GET /version",
        "GET /diag/sa",
        "GET /diag/versions",
        "GET /diag/bucket",
        "POST /diag/parse-pdf-test",
        "POST /diag/parse-preview",

        # references
        "GET /hosts",
        "GET /venues",

        # uploads
        "POST /generate-upload-url",
        "POST /events/<id>/add-photo",
        "POST /events/<id>/add-photo-url",

        # events core
        "GET /events",
        "GET /events/<id>",
        "PUT /events/<id>/status",
        "PUT /events/<id>/ai",
        "POST /events/<id>/parse-pdf",
        "POST /events/<id>/import-from-last-parse",

        # parse logs
        "GET /events/<id>/parse-log (latest)",
        "GET /events/<id>/parse-logs (list recent)",
        "GET /events/parse-log/<log_id> (one log)",

        # Event Photos (list/download)
        "GET /events/<int:eid>/photos", # Added back
        "GET /events/<int:eid>/download-photos", # Added back

        # admin events
        "GET /admin/events",
        "GET /admin/events/<id>",
        "PUT /admin/events/<id>",
        "PUT /admin/events/<id>/participation",
        "POST /admin/events/<id>/photos",
        "DELETE /admin/events/<id>/photos",
        "PUT /admin/events/<id>/validate",
        "POST /admin/events/batch-validate-by-criteria",
        "POST /admin/migrate-pdf",
        "POST /admin/parse-all",
        "POST /admin/parse-sweep",

        # admin data CRUD
        "GET /admin/hosts",
        "POST /admin/hosts",
        "GET /admin/hosts/<host_id>",
        "PUT /admin/hosts/<host_id>",
        "DELETE /admin/hosts/<host_id>",

        "GET /admin/venues",
        "POST /admin/venues",
        "GET /admin/venues/<venue_id>",
        "PUT /admin/venues/<venue_id>",
        "DELETE /admin/venues/<venue_id>",
        "PUT /admin/venues/<venue_id>/generate-access-key",

        "GET /admin/tournament-teams",
        "POST /admin/tournament-teams",
        "GET /admin/tournament-teams/<id>",
        "PUT /admin/tournament-teams/<id>",
        "DELETE /admin/tournament-teams/<id>",

        # admin search (search-first UI)
        "GET /admin/search/hosts?q=&limit=",
        "GET /admin/search/venues?q=&limit=",
        "GET /admin/search/teams?q=&limit=",

        # bulk uploads
        "POST /admin/bulk-upload-tournament-teams",
        "POST /admin/bulk-upload-summary-events",

        # tournament admin/public
        "GET /admin/tournament/weeks",
        "POST /admin/tournament/weeks",
        "PUT /admin/tournament/scores",
        "GET /admin/tournament/scores",
        "PUT /admin/tournament/scores/<venue_id>/<week_ending>/validate",
        "GET /pub/tournament/scores",
        "GET /pub/tournament/venues",
        "GET /pub/tournament/venue/<slug>/<date>",

        # owner portal
        "GET /pub/venues/<slug>/stats",
    ]

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
        "routes": routes
    })

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
        "routes": routes
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
    """
    Body:
      { "event_id": 123 } OR { "pdf_url": "https://..." }
      optional: { "max_chars": 4000 }
    Returns: source url, raw_text preview, line sample (keep/noise), parse summary, parsed teams.
    """
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
        logger.exception("diag_parse_preview failed")
        return jsonify({"error": str(e)}), 500

@app.get("/diag/ai-preview/<int:eid>")
def diag_ai_preview(eid):
    conn = getconn()
    try:
        cur = conn.cursor()
        # REVISED SELECT: Explicitly select fields needed by format_ai_recap and alias them
        cur.execute("""
            SELECT e.id, e.event_date, e.highlights, e.pdf_url, e.ai_recap, e.status, e.fb_event_url,
                   e.show_type, -- NEW: Select show_type
                   h.name AS host_name, v.name AS venue_name, v.default_day, v.default_time
            FROM events e
            LEFT JOIN hosts h ON e.host_id=h.id
            LEFT JOIN venues v ON e.venue_id=v.id
            WHERE e.id=%s;
        """, (eid,))
        row = cur.fetchone() # Rename 'e' to 'row' to avoid confusion with event_data dict
        if not row:
            return jsonify({"error":"event not found"}), 404

        # Map row to dictionary for format_ai_recap
        event_data = {
            "id": row[0],
            "event_date": row[1],
            "highlights": row[2],
            "pdf_url": row[3],
            "ai_recap": row[4],
            "status": row[5],
            "fb_event_url": row[6],
            "show_type": row[7], # This is the crucial line for passing show_type
            "host_name": row[8],
            "venue_name": row[9],
        }
        venue_defaults = {"default_day": row[10], "default_time": row[11]}

        cur.execute("""
            SELECT team_name, score, num_players
            FROM event_participation
            WHERE event_id=%s
            ORDER BY position ASC
            LIMIT 3;
        """, (eid,))
        winners = [{"name": r[0], "score": r[1], "playerCount": r[2]} for r in cur.fetchall()]

        preview = format_ai_recap(event_data, winners, venue_defaults)
        return jsonify({"status":"ok", "ai_preview": preview, "winners": winners})
    finally:
        conn.close()
        
# Function to clean up old parse logs
# Function to clean up old parse logs
def cleanup_parse_logs(event_id: int, conn_or_cur=None, max_logs_to_keep: int = 2):
    """
    Deletes older parse logs for a given event, keeping only the N most recent.
    Can be passed a connection or cursor to run within an existing transaction.
    """
    if max_logs_to_keep <= 0:
        return # Don't delete all logs if max_logs_to_keep is invalid

    local_conn = None
    cur = None
    try:
        if conn_or_cur is None:
            local_conn = getconn()
            cur = local_conn.cursor()
        elif hasattr(conn_or_cur, 'cursor'): # It's a connection
            cur = conn_or_cur.cursor()
        else: # It's already a cursor
            cur = conn_or_cur

        # Find IDs of logs to keep (most recent)
        cur.execute("""
            SELECT id
            FROM event_parse_log
            WHERE event_id = %s
            ORDER BY created_at DESC
            LIMIT %s;
        """, (event_id, max_logs_to_keep))
        logs_to_keep_ids = [r[0] for r in cur.fetchall()]

        # Delete logs that are NOT in the list to keep
        if logs_to_keep_ids:
            # Dynamically construct the IN clause with placeholders
            # Example: id NOT IN (%s, %s) if logs_to_keep_ids has 2 items
            placeholders = ', '.join(['%s'] * len(logs_to_keep_ids))
            
            cur.execute(f"""
                DELETE FROM event_parse_log
                WHERE event_id = %s AND id NOT IN ({placeholders});
            """, (event_id, *logs_to_keep_ids)) # Use `*` to unpack the list into separate arguments
            logger.info(f"Cleaned up {cur.rowcount} old parse logs for event {event_id}.")
        else:
            # If logs_to_keep_ids is empty, it means all existing logs (if any) should be deleted
            # because we want to keep 0 logs, or there are less than max_logs_to_keep but still need pruning
            cur.execute("""
                DELETE FROM event_parse_log
                WHERE event_id = %s;
            """, (event_id,))
            if cur.rowcount > 0:
                logger.info(f"Deleted all parse logs ({cur.rowcount}) for event {event_id} (requested to keep 0).")


    except Exception:
        logger.exception(f"Failed to cleanup parse logs for event {event_id}")
    finally:
        if local_conn:
            local_conn.commit()
            local_conn.close()
# ------------------------------------------------------------------------------
# Upload endpoints (proxied)
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
# Migrate
# ------------------------------------------------------------------------------
@app.route("/migrate", methods=["POST"])
def migrate():
    """
    Builds the entire database schema from scratch to match the current state.
    This route is idempotent and safe to run on an existing or empty database.
    It creates all tables, columns, constraints, and indexes in the correct order.
    """
    conn = getconn()
    try:
        cur = conn.cursor()

        # --- Base Tables (No External Dependencies) ---
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
              default_time TEXT,
              access_key TEXT UNIQUE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tournament_weeks (
              id SERIAL PRIMARY KEY,
              week_ending DATE UNIQUE NOT NULL,
              created_at TIMESTAMP DEFAULT now()
            );
        """)

        # --- Tables with Dependencies on Base Tables ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tournament_teams (
              id SERIAL PRIMARY KEY,
              name TEXT UNIQUE NOT NULL,
              home_venue_id INTEGER,
              captain_name TEXT,
              captain_email TEXT,
              captain_phone TEXT,
              player_count INTEGER,
              created_at TIMESTAMP DEFAULT now(),
              access_key TEXT UNIQUE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
              id SERIAL PRIMARY KEY,
              host_id INTEGER REFERENCES hosts(id),
              venue_id INTEGER UNIQUE,
              event_date DATE UNIQUE NOT NULL,
              highlights TEXT,
              pdf_url TEXT,
              ai_recap TEXT,
              status TEXT DEFAULT 'unposted',
              fb_event_url TEXT,
              created_at TIMESTAMP DEFAULT now(),
              show_type TEXT DEFAULT 'gsp',
              updated_at TIMESTAMP,
              is_validated BOOLEAN DEFAULT false,
              total_players INTEGER,
              total_teams INTEGER,
              CONSTRAINT uniq_venue_date UNIQUE (venue_id, event_date)
            );
        """)

        # --- Tables with a Foreign Key to Events ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS event_photos (
              id SERIAL PRIMARY KEY,
              event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
              photo_url TEXT
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS event_participation (
              id SERIAL PRIMARY KEY,
              event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
              team_name TEXT,
              tournament_team_id INTEGER,
              score INTEGER,
              position INTEGER,
              num_players INTEGER,
              is_visiting BOOLEAN DEFAULT false,
              is_tournament BOOLEAN DEFAULT false,
              updated_at TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS event_parse_log (
              id SERIAL PRIMARY KEY,
              event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
              raw_text_gz BYTEA,
              parsed_json JSONB,
              status TEXT,
              error TEXT,
              created_at TIMESTAMP DEFAULT now()
            );
        """)

        # --- Final Tournament Scores Table (Connects multiple tables) ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tournament_team_scores (
              id SERIAL PRIMARY KEY,
              tournament_team_id INTEGER UNIQUE NOT NULL REFERENCES tournament_teams(id) ON DELETE CASCADE,
              venue_id INTEGER UNIQUE NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
              week_id INTEGER UNIQUE NOT NULL REFERENCES tournament_weeks(id) ON DELETE CASCADE,
              event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
              points INTEGER DEFAULT 0,
              num_players INTEGER,
              is_validated BOOLEAN DEFAULT false,
              updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
              CONSTRAINT tournament_team_scores_tournament_team_id_venue_id_week_id_key
                UNIQUE (tournament_team_id, venue_id, week_id)
            );
        """)

        # --- Indexes for Performance (PostgreSQL creates unique indexes for PRIMARY KEY and UNIQUE constraints automatically) ---
        cur.execute("CREATE INDEX IF NOT EXISTS idx_event_photos_event ON event_photos(event_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_event_participation_event_pos ON event_participation(event_id, position);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tts_team_week ON tournament_team_scores(tournament_team_id, week_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tts_venue_week ON tournament_team_scores(venue_id, week_id);")

        conn.commit()
        return jsonify({"status": "ok", "message": "Database schema created/verified successfully."})
    except Exception as e:
        conn.rollback()
        logger.exception("migrate failed")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()
# ------------------------------------------------------------------------------
# Health
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
# Reference data
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

@app.get("/venues/<int:vid>/recent-photos")
def get_venue_recent_photos(vid):
    """
    Finds the most recent event for a given venue that has photos
    and returns the event_id and the list of photo URLs.
    """
    conn = getconn()
    try:
        cur = conn.cursor()
        # Find the most recent event_id for this venue that has at least one photo.
        cur.execute("""
            SELECT e.id
            FROM events e
            WHERE e.venue_id = %s
              AND EXISTS (SELECT 1 FROM event_photos ep WHERE ep.event_id = e.id)
            ORDER BY e.event_date DESC
            LIMIT 1;
        """, (vid,))
        
        result = cur.fetchone()
        if not result:
            conn.close()
            return jsonify({"message": "No recent events with photos found for this venue."}), 404

        most_recent_event_id = result[0]

        # Now get all photos for that event
        cur.execute("SELECT photo_url FROM event_photos WHERE event_id=%s ORDER BY id;", (most_recent_event_id,))
        photos = [r[0] for r in cur.fetchall()]

        conn.close()
        return jsonify({
            "eventId": most_recent_event_id,
            "photoUrls": photos
        })
    except Exception as e:
        logger.exception("get_venue_recent_photos failed")
        try: 
            if 'conn' in locals() and conn: 
                conn.close()
        except Exception: 
            pass
        return jsonify({"error": str(e)}), 500

# ------------------------------------------------------------------------------
# Create Event
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
    show_type = (d.get("showType") or "gsp").strip() # NEW: Extract showType

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

        # REVISED INSERT/UPDATE: Include show_type
        cur.execute(
            """
            INSERT INTO events (host_id, venue_id, event_date, highlights, pdf_url, status, show_type)
            VALUES (%s,%s,%s,%s,%s,'unposted',%s)
            ON CONFLICT (venue_id, event_date)
            DO UPDATE SET
              host_id = EXCLUDED.host_id,
              highlights = COALESCE(NULLIF(EXCLUDED.highlights, ''), events.highlights),
              pdf_url = COALESCE(NULLIF(EXCLUDED.pdf_url, ''), events.pdf_url),
              show_type = EXCLUDED.show_type -- NEW: Update show_type on conflict
            RETURNING id;
            """,
            (host_id, venue_id, event_date, highlights, pdf_url, show_type),
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
        logger.info("Event created id=%s pdf=%s photos=%s show_type=%s", event_id, bool(pdf_url), len(photo_urls), show_type)

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
# Events list/detail/status
# ------------------------------------------------------------------------------
@app.get("/events")
def list_events():
    st = request.args.get("status")
    # NEW: is_validated_filter is only applied if explicitly requested, not automatically with `status`
    # This allows hosts to see all their events, regardless of validation status.
    is_validated_param = request.args.get("is_validated") # Can be "true", "false", or absent
    
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

        # Apply is_validated filter ONLY if it's explicitly requested in the query params
        if is_validated_param is not None:
            if is_validated_param.lower() == "true":
                where_clauses.append("e.is_validated=TRUE")
            elif is_validated_param.lower() == "false":
                where_clauses.append("e.is_validated=FALSE")
            # If param exists but is not "true"/"false", it won't add a clause.

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

@app.post("/events/<int:eid>/parse-pdf")
def parse_pdf_for_event(eid):
    conn = getconn()
    try:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT e.id, e.event_date, e.highlights, e.pdf_url, e.ai_recap, e.status, e.fb_event_url,
                   e.show_type,
                   h.name AS host_name, v.name AS venue_name, v.default_day, v.default_time
            FROM events e
            LEFT JOIN hosts h ON e.host_id=h.id
            LEFT JOIN venues v ON e.venue_id=v.id
            WHERE e.id=%s;
        """, (eid,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "event not found"}), 404

        pdf_url = row[3]
        if not pdf_url:
            return jsonify({"error": "event has no pdf_url"}), 400

        pdf_bytes = fetch_pdf_bytes(pdf_url)
        raw_text = safe_extract_text(pdf_bytes)
        parsed = parse_raw_text(raw_text)

        st = "success" if parsed["teams"] else "failed"
        error = None if parsed["teams"] else "no teams parsed"

        # --- Store Parse Log ---
        try:
            raw_text_gz = gzip.compress(raw_text.encode("utf-8")) if raw_text is not None else None
            cur.execute(
                "INSERT INTO event_parse_log (event_id, raw_text_gz, parsed_json, status, error) VALUES (%s,%s,%s,%s,%s) RETURNING id;",
                (eid, raw_text_gz, json.dumps(parsed), st, error)
            )
            log_id = cur.fetchone()[0]
            cleanup_parse_logs(eid, cur, max_logs_to_keep=2)
        except Exception as e:
            conn.rollback() # CRITICAL: Rollback immediately on failure
            logger.exception(f"Failed to store parse log for event {eid}")
            return jsonify({"error": f"Failed to store parse log: {str(e)}"}), 500

        # --- Delete existing participation ---
        try:
            cur.execute("DELETE FROM event_participation WHERE event_id=%s;", (eid,))
        except Exception as e:
            conn.rollback() # CRITICAL: Rollback immediately on failure
            logger.exception(f"Failed to delete existing participation for event {eid}")
            return jsonify({"error": f"Failed to clear old participation: {str(e)}"}), 500

        # --- Insert new participation records ---
        winners = []
        try:
            for t in parsed["teams"]:
                team_name = str(t.get("name") or "").strip()
                score = t.get("score")
                num_players = t.get("playerCount")
                position = t.get("position")
                is_visiting = bool(t.get("isVisiting", False))
                is_tournament = bool(t.get("isTournament", False))

                if not team_name:
                    logger.warning(f"Skipping team with no name in parse results for event {eid}: {t}")
                    continue # Skip inserting teams with no name

                if t.get("position") in (1, 2, 3) and len(winners) < 3:
                    winners.append({
                        "name": team_name,
                        "score": score,
                        "playerCount": num_players,
                    })
                
                cur.execute("""
                    INSERT INTO event_participation
                      (event_id, team_name, score, position, num_players, is_visiting, is_tournament)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, (
                    eid, team_name, score, position, num_players, is_visiting, is_tournament,
                ))
        except Exception as e:
            conn.rollback() # CRITICAL: Rollback immediately on failure
            logger.exception(f"Failed to insert participation record for event {eid}")
            return jsonify({"error": f"Failed to insert participation records: {str(e)}"}), 500

        # --- Generate and update AI Recap ---
        ai_text = ""
        try:
            if parsed["teams"]:
                event_data = {
                    "id": row[0], "event_date": row[1], "highlights": row[2], "pdf_url": row[3],
                    "ai_recap": row[4], "status": row[5], "fb_event_url": row[6], "show_type": row[7],
                    "host_name": row[8], "venue_name": row[9],
                }
                venue_defaults = {"default_day": row[10], "default_time": row[11]}
                
                ai_text = format_ai_recap(event_data, winners, venue_defaults)
                cur.execute("UPDATE events SET ai_recap=%s WHERE id=%s;", (ai_text, eid))
            else:
                cur.execute("UPDATE events SET ai_recap=NULL WHERE id=%s;", (eid,)) # Clear AI recap if no teams
        except Exception as e:
            logger.exception(f"Failed to generate/update AI recap for event {eid}")
            error = (error or "") + f" (AI recap gen failed: {str(e)})"
            st = "partial_success"
            ai_text = "AI recap generation failed. See logs for details." # Provide this as status message

        conn.commit()
        return jsonify({"status": st, "logId": log_id, "parsed": parsed, "ai_recap_generated": ai_text, "error": error})
    except Exception as e: # This outer block catches errors not caught by inner blocks
        conn.rollback()
        logger.exception(f"parse-pdf failed for event {eid} in outer block")
        return jsonify({"error": f"Parse operation failed: {str(e)}"}), 500
    finally:
        conn.close()

@app.post("/events/<int:eid>/import-from-last-parse")
def import_from_last_parse(eid):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT parsed_json
            FROM event_parse_log
            WHERE event_id=%s AND status='success'
            ORDER BY created_at DESC LIMIT 1;
        """, (eid,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error":"no successful parse to import"}), 404

        parsed_json = row[0]
        parsed = json.loads(parsed_json) if isinstance(parsed_json, str) else parsed_json
        if not parsed.get("teams"):
            return jsonify({"error":"parse has no teams"}), 400

        # Fetch current event data to generate AI recap
        cur.execute("""
            SELECT e.id, e.event_date, e.highlights, e.pdf_url, e.ai_recap, e.status, e.fb_event_url,
                   e.show_type,
                   h.name AS host_name, v.name AS venue_name, v.default_day, v.default_time
            FROM events e
            LEFT JOIN hosts h ON e.host_id=h.id
            LEFT JOIN venues v ON e.venue_id=v.id
            WHERE e.id=%s;
        """, (eid,))
        event_row_for_recap = cur.fetchone()
        if not event_row_for_recap:
            return jsonify({"error": "event not found for recap generation"}), 404

        # --- Delete existing participation ---
        try:
            cur.execute("DELETE FROM event_participation WHERE event_id=%s;", (eid,))
        except Exception as e:
            conn.rollback()
            logger.exception(f"Failed to delete existing participation for event {eid} during import")
            return jsonify({"error": f"Failed to clear old participation: {str(e)}"}), 500

        # --- Insert new participation records ---
        winners = []
        try:
            pos = 1
            for t in parsed["teams"][:3]: # Only top 3 for winners list
                winners.append({"name": t["name"], "score": t.get("score"), "playerCount": t.get("playerCount")})
                cur.execute(
                    "INSERT INTO event_participation (event_id, team_name, score, position, num_players, is_visiting) VALUES (%s,%s,%s,%s,%s,%s)",
                    (eid, t["name"], t.get("score"), pos, t.get("playerCount"), t.get("isVisiting", False))
                )
                pos += 1
            # Insert all other teams from parsed data if you want more than just winners
            for t in parsed["teams"][3:]:
                 cur.execute(
                    "INSERT INTO event_participation (event_id, team_name, score, position, num_players, is_visiting) VALUES (%s,%s,%s,%s,%s,%s)",
                    (eid, t["name"], t.get("score"), t.get("position"), t.get("playerCount"), t.get("isVisiting", False))
                )
        except Exception as e:
            conn.rollback()
            logger.exception(f"Failed to insert participation record for event {eid} during import")
            return jsonify({"error": f"Failed to insert participation records: {str(e)}"}), 500

        # --- Generate and update AI Recap ---
        ai_text = ""
        try:
            event_data_for_recap = {
                "id": event_row_for_recap[0], "event_date": event_row_for_recap[1], "highlights": event_row_for_recap[2],
                "pdf_url": event_row_for_recap[3], "ai_recap": event_row_for_recap[4], "status": event_row_for_recap[5],
                "fb_event_url": event_row_for_recap[6], "show_type": event_row_for_recap[7],
                "host_name": event_row_for_recap[8], "venue_name": event_row_for_recap[9],
            }
            venue_defaults = {"default_day": event_row_for_recap[10], "default_time": event_row_for_recap[11]}
            
            ai_text = format_ai_recap(event_data_for_recap, winners, venue_defaults)
            cur.execute("UPDATE events SET ai_recap=%s WHERE id=%s;", (ai_text, eid))
        except Exception as e:
            logger.exception(f"Failed to generate/update AI recap for event {eid} during import")
            ai_text = "AI recap generation failed during import. See logs for details."


        conn.commit()
        return jsonify({"status":"ok","winners": winners, "ai_recap_generated": ai_text})
    except Exception as e: # Outer block catches errors not caught by inner blocks
        conn.rollback()
        logger.exception(f"import_from_last_parse failed for event {eid} in outer block")
        return jsonify({"error":"failed to import parsed data: " + str(e)}), 500
    finally:
        conn.close()

@app.get("/events/parse-log/<int:log_id>")
def get_parse_log_by_id(log_id):
    """
    Return a single parse log by log_id, including full raw_text (decompressed)
    and parsed_json (if present).
    """
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, event_id, created_at, status, error, raw_text_gz, parsed_json
            FROM event_parse_log
            WHERE id=%s;
        """, (log_id,))
        r = cur.fetchone()
        if not r:
            return jsonify({"error": "log not found"}), 404
        _id, event_id, created_at, status_s, err, raw_gz, parsed_json = r
        raw_text = None
        if raw_gz:
            try:
                raw_text = gzip.decompress(raw_gz).decode("utf-8", errors="replace")
            except Exception as e:
                raw_text = f"[decompress failed: {e}]"
        return jsonify({
            "id": _id,
            "event_id": event_id,
            "created_at": created_at.isoformat() if created_at else None,
            "status": status_s,
            "error": err,
            "raw_text": raw_text,
            "parsed_json": parsed_json,
        })
    finally:
        conn.close()

@app.get("/events/<int:eid>/parse-logs")
def get_parse_logs(eid):
    """
    Return recent parse logs for an event (default 10).
    Includes: id, created_at, status, error, parsed_json presence, and raw preview length.
    NOTE: For safety, this only sends a small preview of raw_text, not the full blob.
    """
    limit = max(1, min(int(request.args.get("limit", "10")), 100))
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, created_at, status, error, raw_text_gz, parsed_json
            FROM event_parse_log
            WHERE event_id=%s
            ORDER BY created_at DESC
            LIMIT %s;
        """, (eid, limit))
        rows = cur.fetchall()

        out = []
        for r in rows:
            log_id, created_at, status_s, err, raw_gz, parsed_json = r
            raw_preview = None
            if raw_gz:
                try:
                    raw_preview = gzip.decompress(raw_gz).decode("utf-8", errors="replace")
                    if len(raw_preview) > 2000:
                        raw_preview = raw_preview[:2000] + "\n...[truncated preview]..."
                except Exception as e:
                    raw_preview = f"[decompress failed: {e}]"
            out.append({
                "id": log_id,
                "created_at": created_at.isoformat() if created_at else None,
                "status": status_s,
                "error": err,
                "parsed_present": bool(parsed_json),
                "raw_preview_len": len(raw_preview) if isinstance(raw_preview, str) else 0,
                "raw_preview": raw_preview,
            })
        return jsonify({"event_id": eid, "count": len(out), "logs": out})
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

@app.get("/events/<int:eid>/photos")
def get_event_photos_list(eid):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT photo_url FROM event_photos WHERE event_id=%s ORDER BY id;", (eid,))
        photos = [r[0] for r in cur.fetchall()]
        return jsonify(photos)
    finally:
        conn.close()

@app.get("/events/<int:eid>/download-photos")
def download_event_photos_zip(eid):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.event_date, v.name
            FROM events e
            JOIN venues v ON e.venue_id = v.id
            WHERE e.id = %s;
        """, (eid,))
        event_info = cur.fetchone()
        
        if not event_info:
            conn.close()
            return jsonify({"error": "Event not found"}), 404

        event_date_str = event_info[0].isoformat() if event_info[0] else "UnknownDate"
        venue_name_str = (event_info[1] or "UnknownVenue").replace(" ", "-")
        safe_venue_name = re.sub(r'[^\w\-]', '', venue_name_str)
        zip_filename = f"{safe_venue_name}-{event_date_str}.zip"

        cur.execute("SELECT photo_url FROM event_photos WHERE event_id=%s ORDER BY id;", (eid,))
        photo_urls = [r[0] for r in cur.fetchall()]
        if not photo_urls:
            cur.close()
            conn.close()
            return jsonify({"message": "No photos found for this event."}), 200

        import zipfile
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for i, url in enumerate(photo_urls):
                try:
                    filename = url.split('/')[-1] or f"photo_{i+1}.bin"
                    filename = re.sub(r'[^\w\.-]', '_', filename)
                    resp = httpx.get(url, timeout=30)
                    resp.raise_for_status()
                    zf.writestr(filename, resp.content)
                except Exception as ex:
                    logger.warning("Skip %s: %s", url, ex)

        zip_buffer.seek(0)
        cur.close()
        conn.close()
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=zip_filename, # Use the new dynamic filename
        )
    except Exception as e:
        logger.exception("download_event_photos_zip failed")
        try:
            if 'conn' in locals() and conn:
                conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

# ------------------------------------------------------------------------------
# Admin migrate PDF and sweeps
# ------------------------------------------------------------------------------
@app.post("/admin/migrate-pdf")
def migrate_pdf():
    d = request.json or {}
    event_id = d.get("event_id")
    pdf_url_in = (d.get("pdf_url") or "").strip()
    update_event = bool(d.get("update_event", True if event_id else False))

    if not event_id and not pdf_url_in:
        return jsonify({"error": "Provide event_id or pdf_url"}), 400

    conn = getconn()
    try:
        cur = conn.cursor()
        pdf_url = pdf_url_in

        if event_id and not pdf_url:
            cur.execute("SELECT pdf_url FROM events WHERE id=%s;", (event_id,))
            row = cur.fetchone()
            if not row or not row[0]:
                return jsonify({"error": "event has no pdf_url"}), 400
            pdf_url = row[0]

        try:
            pdf_bytes = fetch_pdf_bytes(pdf_url)
        except Exception as e:
            logger.exception("fetch_pdf_bytes failed")
            return jsonify({"error": f"failed to download source pdf: {e}"}), 500

        filename = "recap.pdf"
        m = re.search(r"/([^/]+)\.(pdf|PDF)(?:\?|$)", pdf_url)
        if m:
            filename = m.group(0).split("/")[-1]
        else:
            tail = pdf_url.strip("/").split("/")[-1]
            if tail:
                tail = re.sub(r"[^\w\.-]", "_", tail)
                if not tail.lower().endswith(".pdf"):
                    tail = tail + ".pdf"
                filename = tail

        key = safe_key(filename)
        if not GCS_BUCKET:
            return jsonify({"error": "GCS_BUCKET not configured"}), 500

        blob = storage_client.bucket(GCS_BUCKET).blob(key)
        blob.upload_from_string(pdf_bytes, content_type="application/pdf")
        public_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{key}"

        if event_id and update_event:
            cur.execute("UPDATE events SET pdf_url=%s WHERE id=%s;", (public_url, event_id))
            conn.commit()

        return jsonify({"status": "ok", "gcs_url": public_url})
    except Exception as e:
        conn.rollback()
        logger.exception("migrate_pdf failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.post("/admin/migrate-all-drive-pdfs")
def migrate_all_drive_pdfs():
    limit = int(request.args.get("limit", "500"))
    conn = getconn()
    results = {"attempted":0, "migrated":0, "failed":0, "errors":[]}
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, pdf_url FROM events WHERE pdf_url ILIKE '%%drive.google.com%%' ORDER BY id DESC LIMIT %s;",
            (limit,)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        for eid, url in rows:
            results["attempted"] += 1
            try:
                r = rq.post("https://api.gspevents.com/admin/migrate-pdf", json={"event_id": eid}, timeout=60)
                if r.ok and r.json().get("status") == "ok":
                    results["migrated"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append({"event": eid, "msg": r.text})
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"event": eid, "msg": str(e)})
        return jsonify(results)
    except Exception as e:
        logger.exception("migrate_all_drive_pdfs failed")
        return jsonify({"error": str(e), "partial": results}), 500

@app.post("/admin/parse-sweep")
def parse_sweep():
    return parse_all_events()

# ------------------------------------------------------------------------------
# Admin Data
# ------------------------------------------------------------------------------


# --- Hosts ---
@app.get("/admin/hosts")
def admin_list_hosts():
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, phone, email FROM hosts ORDER BY name;")
        rows = cur.fetchall()
        return jsonify([{"id": r[0], "name": r[1], "phone": r[2], "email": r[3]} for r in rows])
    finally:
        conn.close()

@app.post("/admin/hosts")
def admin_create_host():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    if not name:
        return jsonify({"error": "Host name is required"}), 400
    
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM hosts WHERE lower(name) = lower(%s);", (name,))
        existing = cur.fetchone()
        if existing:
            return jsonify({"status": "exists", "id": existing[0]}), 200 # Return 200 OK if exists
        
        cur.execute(
            "INSERT INTO hosts (name, phone, email) VALUES (%s, %s, %s) RETURNING id;",
            (name, phone, email)
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({"status": "created", "id": new_id}), 201 # Return 201 Created
    except Exception as e:
        conn.rollback()
        logger.exception("admin_create_host failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.get("/admin/hosts/<int:host_id>")
def admin_get_host_detail(host_id):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, phone, email FROM hosts WHERE id=%s;", (host_id,))
        r = cur.fetchone()
        if not r:
            return jsonify({"error": "Host not found"}), 404
        return jsonify({"id": r[0], "name": r[1], "phone": r[2], "email": r[3]})
    finally:
        conn.close()

@app.put("/admin/hosts/<int:host_id>")
def admin_update_host(host_id):
    data = request.json or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    if not name:
        return jsonify({"error": "Host name is required"}), 400

    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE hosts SET name=%s, phone=%s, email=%s WHERE id=%s;", (name, phone, email, host_id))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Host not found"}), 404
        return jsonify({"status": "ok", "id": host_id})
    except Exception as e:
        conn.rollback()
        logger.exception(f"admin_update_host {host_id} failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.delete("/admin/hosts/<int:host_id>")
def admin_delete_host(host_id):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM hosts WHERE id=%s;", (host_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Host not found or could not be deleted"}), 404
        return jsonify({"status": "ok"})
    except pg8000.exceptions.IntegrityError:
        conn.rollback()
        return jsonify({"error": "Host cannot be deleted because it is linked to existing events. Reassign events first."}), 409
    except Exception as e:
        conn.rollback()
        logger.exception(f"admin_delete_host {host_id} failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.post("/admin/venues")
def admin_add_venue():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    default_day = (data.get("default_day") or "").strip()
    default_time = (data.get("default_time") or "").strip()
    if not name:
        return jsonify({"error": "Venue name is required"}), 400
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM venues WHERE lower(name) = lower(%s);", (name,))
        existing_id = cur.fetchone()
        if existing_id:
            return jsonify({"status": "exists", "id": existing_id[0]}), 200
        cur.execute(
            "INSERT INTO venues (name, default_day, default_time) VALUES (%s, %s, %s) RETURNING id;",
            (name, default_day, default_time)
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({"status": "created", "id": new_id}), 201
    except Exception as e:
        logger.exception("admin/venues failed")
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# --- Venues ---
@app.get("/admin/venues")
def admin_list_venues():
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, default_day, default_time, access_key FROM venues ORDER BY name;")
        rows = cur.fetchall()
        return jsonify([
            {"id": r[0], "name": r[1], "default_day": r[2], "default_time": r[3], "access_key": r[4]}
            for r in rows
        ])
    finally:
        conn.close()

@app.post("/admin/venues")
def admin_create_venue():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    default_day = (data.get("default_day") or "").strip()
    default_time = (data.get("default_time") or "").strip()
    
    if not name:
        return jsonify({"error": "Venue name is required"}), 400
    
    new_access_key = str(uuid4().hex) # Generate a unique access key for the new venue

    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM venues WHERE lower(name) = lower(%s);", (name,))
        existing_id = cur.fetchone()
        if existing_id:
            return jsonify({"status": "exists", "id": existing_id[0]}), 200
        cur.execute(
            "INSERT INTO venues (name, default_day, default_time, access_key) VALUES (%s, %s, %s, %s) RETURNING id;",
            (name, default_day, default_time, new_access_key)
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({"status": "created", "id": new_id, "access_key": new_access_key}), 201
    except Exception as e:
        logger.exception("admin_create_venue failed")
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.get("/admin/venues/<int:venue_id>")
def admin_get_venue_detail(venue_id):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, default_day, default_time, access_key FROM venues WHERE id=%s;", (venue_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Venue not found"}), 404
        return jsonify({"id": row[0], "name": row[1], "default_day": row[2], "default_time": row[3], "access_key": row[4]})
    finally:
        conn.close()

@app.put("/admin/venues/<int:venue_id>")
def admin_update_venue(venue_id):
    data = request.json or {}
    name = (data.get("name") or "").strip()
    default_day = (data.get("default_day") or "").strip()
    default_time = (data.get("default_time") or "").strip()
    # Allowing access_key to be updated via this route, if provided by the frontend
    access_key = data.get("access_key") # Can be null if not changed

    if not name:
        return jsonify({"error": "Venue name is required"}), 400

    conn = getconn()
    try:
        cur = conn.cursor()
        
        update_fields = ["name=%s", "default_day=%s", "default_time=%s"]
        update_params = [name, default_day, default_time]

        # Conditionally add access_key to the update if it's explicitly provided in the request body
        # This allows regenerating a key and then saving the form, or explicitly setting one.
        if access_key is not None: # Check for None to allow setting it to null explicitly if needed, though usually it's set to a new uuid.
            update_fields.append("access_key=%s")
            update_params.append(access_key)

        update_params.append(venue_id) # WHERE clause parameter

        cur.execute(
            f"UPDATE venues SET {', '.join(update_fields)} WHERE id=%s;",
            tuple(update_params)
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Venue not found"}), 404
        return jsonify({"status": "ok", "id": venue_id})
    except Exception as e:
        logger.exception(f"admin_update_venue {venue_id} failed")
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.delete("/admin/venues/<int:venue_id>")
def admin_delete_venue(venue_id):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM venues WHERE id=%s;", (venue_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Venue not found or could not be deleted"}), 404
        return jsonify({"status": "ok", "message": "Venue deleted"})
    except pg8000.exceptions.IntegrityError as e: # Catch foreign key constraint issues
        conn.rollback()
        return jsonify({"error": "Venue cannot be deleted as it is linked to existing events or tournament teams. Please reassign items first."}), 409
    except Exception as e:
        logger.exception(f"admin_delete_venue {venue_id} failed")
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# NEW ADMIN ENDPOINT: Generate a new access key for an existing venue
@app.put("/admin/venues/<int:venue_id>/generate-access-key")
def admin_generate_venue_access_key(venue_id):
    conn = getconn()
    try:
        new_key = str(uuid4().hex)
        cur = conn.cursor()
        cur.execute("UPDATE venues SET access_key=%s WHERE id=%s RETURNING access_key;", (new_key, venue_id))
        result = cur.fetchone()
        conn.commit()
        if not result:
            return jsonify({"error": "Venue not found"}), 404
        return jsonify({"status": "ok", "id": venue_id, "access_key": result[0]})
    except Exception as e:
        conn.rollback()
        logger.exception(f"admin_generate_venue_access_key for {venue_id} failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# --- Tournament Teams ---
@app.get("/admin/tournament-teams")
def admin_list_tournament_teams():
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT tt.id, tt.name, tt.home_venue_id, v.name AS home_venue_name,
                   tt.captain_name, tt.captain_email, tt.captain_phone, tt.player_count
            FROM tournament_teams tt
            LEFT JOIN venues v ON tt.home_venue_id = v.id
            ORDER BY tt.name;
        """)
        rows = cur.fetchall()
        return jsonify([{
            "id": r[0], "name": r[1], "home_venue_id": r[2], "home_venue": r[3],
            "captain_name": r[4], "captain_email": r[5], "captain_phone": r[6], "player_count": r[7]
        } for r in rows])
    finally:
        conn.close()

@app.post("/admin/tournament-teams")
def admin_create_tournament_team():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    home_venue_id = data.get("home_venue_id")
    captain_name = (data.get("captain_name") or "").strip()
    captain_email = (data.get("captain_email") or "").strip().lower()
    captain_phone = (data.get("captain_phone") or "").strip()
    player_count = data.get("player_count")
    if not name:
        return jsonify({"error": "Team name is required"}), 400
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM tournament_teams WHERE lower(name) = lower(%s);", (name,))
        existing_id = cur.fetchone()
        if existing_id:
            return jsonify({"status": "exists", "id": existing_id[0]}), 200
        cur.execute("""
            INSERT INTO tournament_teams (name, home_venue_id, captain_name, captain_email, captain_phone, player_count)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;
        """, (name, home_venue_id, captain_name, captain_email, captain_phone, player_count))
        new_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({"status": "created", "id": new_id}), 201
    except Exception as e:
        logger.exception("admin_create_tournament_team failed")
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.get("/admin/tournament-teams/<int:team_id>")
def admin_get_tournament_team_detail(team_id):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT tt.id, tt.name, tt.home_venue_id, v.name AS home_venue_name,
                   tt.captain_name, tt.captain_email, tt.captain_phone, tt.player_count
            FROM tournament_teams tt
            LEFT JOIN venues v ON tt.home_venue_id = v.id
            WHERE tt.id=%s;
        """, (team_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Tournament team not found"}), 404
        return jsonify({
            "id": row[0], "name": row[1], "home_venue_id": row[2], "home_venue": row[3],
            "captain_name": row[4], "captain_email": row[5], "captain_phone": row[6], "player_count": row[7]
        })
    finally:
        conn.close()

@app.put("/admin/tournament-teams/<int:team_id>")
def admin_update_tournament_team(team_id):
    data = request.json or {}
    name = (data.get("name") or "").strip()
    home_venue_id = data.get("home_venue_id")
    captain_name = (data.get("captain_name") or "").strip()
    captain_email = (data.get("captain_email") or "").strip().lower()
    captain_phone = (data.get("captain_phone") or "").strip()
    player_count = data.get("player_count")

    if not name:
        return jsonify({"error": "Team name is required"}), 400

    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE tournament_teams
            SET name=%s, home_venue_id=%s, captain_name=%s, captain_email=%s, captain_phone=%s, player_count=%s
            WHERE id=%s;
            """,
            (name, home_venue_id, captain_name, captain_email, captain_phone, player_count, team_id)
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Tournament team not found"}), 404
        return jsonify({"status": "ok", "id": team_id})
    except Exception as e:
        logger.exception(f"admin_update_tournament_team {team_id} failed")
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.delete("/admin/tournament-teams/<int:team_id>")
def admin_delete_tournament_team(team_id):
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM tournament_teams WHERE id=%s;", (team_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Tournament team not found or could not be deleted"}), 404
        return jsonify({"status": "ok", "message": "Tournament team deleted"})
    except pg8000.exceptions.IntegrityError as e:
        conn.rollback()
        return jsonify({"error": "Tournament team cannot be deleted as it is linked to existing scores. Please delete scores first."}), 409
    except Exception as e:
        logger.exception(f"admin_delete_tournament_team {team_id} failed")
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# --- Tournament Score Management API ---

def get_last_12_weeks():
    """
    Returns a list of the 12 most relevant tournament week-ending dates (Sundays).
    - Before the season: Shows the first 12 weeks of the season.
    - During the season: Shows a rolling 12-week window ending on the current week.
    - After the season: Shows the final 12 weeks of the season.
    """
    today = date.today()
    
    # --- Define Tournament Season ---
    season_start = date(2025, 8, 17)
    season_end = date(2025, 11, 9)
    
    # Normalize start/end to be Sundays
    season_start_sunday = season_start - timedelta(days=(season_start.weekday() + 1) % 7)
    season_end_sunday = season_end - timedelta(days=(season_end.weekday() + 1) % 7)
    
    weeks = []
    
    if today < season_start_sunday:
        # --- Pre-Season: Show the first 12 weeks ---
        for i in range(12):
            weeks.append(season_start_sunday + timedelta(weeks=i))
            
    elif today > season_end_sunday:
        # --- Post-Season: Show the last 12 weeks ---
        for i in range(12):
            weeks.append(season_end_sunday - timedelta(weeks=11 - i))
            
    else:
        # --- In-Season: Show a rolling 12-week window ---
        # Find the Sunday of the current week
        current_week_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
        for i in range(12):
            weeks.append(current_week_sunday - timedelta(weeks=11 - i))

    return weeks

@app.get("/admin/teams/<int:team_id>/weekly-scores")
def get_team_weekly_scores(team_id):
    """
    Fetches the last 12 weeks of scores for a team AT a specific venue,
    now correctly joining with the tournament_weeks table.
    """
    venue_id = request.args.get("venue_id")
    if not venue_id:
        return jsonify({"error": "venue_id is required"}), 400
        
    weeks = get_last_12_weeks()
    conn = getconn()
    try:
        cur = conn.cursor()
        
        # CORRECTED QUERY:
        # 1. JOIN tournament_team_scores (tts) with tournament_weeks (tw).
        # 2. SELECT tw.week_ending, not a non-existent column.
        # 3. FILTER on tw.week_ending using the list of the last 12 weeks.
        cur.execute("""
            SELECT
                tw.week_ending,
                tts.points,
                tts.num_players
            FROM tournament_team_scores tts
            JOIN tournament_weeks tw ON tts.week_id = tw.id
            WHERE tts.tournament_team_id = %s AND tts.venue_id = %s AND tw.week_ending = ANY(%s);
        """, (team_id, venue_id, weeks))
        
        scores_by_week = {r[0].isoformat(): {"points": r[1], "num_players": r[2]} for r in cur.fetchall()}
        
        # Prepare response for all 12 weeks, filling in blanks
        response_weeks = []
        for week_date in weeks:
            iso_date = week_date.isoformat()
            response_weeks.append({
                "week_ending": iso_date,
                "points": scores_by_week.get(iso_date, {}).get("points", ""),
                "num_players": scores_by_week.get(iso_date, {}).get("num_players", "")
            })
            
        return jsonify(response_weeks)
    finally:
        conn.close()

@app.put("/admin/teams/<int:team_id>/weekly-scores")
def save_team_weekly_scores(team_id):
    """
    UPSERTS manual scores for a team at a venue for multiple weeks.
    Body: { venue_id: 1, scores: [{ week_ending: "YYYY-MM-DD", points: 100, num_players: 5 }, ...] }
    """
    data = request.json or {}
    venue_id = data.get("venue_id")
    scores = data.get("scores", [])
    if not venue_id or not scores:
        return jsonify({"error": "venue_id and a scores array are required"}), 400

    conn = getconn()
    try:
        cur = conn.cursor()
        for score_entry in scores:
            week_ending = score_entry.get("week_ending")
            points = score_entry.get("points")
            num_players = score_entry.get("num_players")

            # Use an UPSERT to handle both new and existing weekly scores
            cur.execute("""
                INSERT INTO tournament_team_scores (tournament_team_id, venue_id, week_ending, points, num_players, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tournament_team_id, venue_id, week_ending)
                DO UPDATE SET points = EXCLUDED.points, num_players = EXCLUDED.num_players, updated_at = NOW();
            """, (team_id, venue_id, week_ending, points, num_players))
        
        conn.commit()
        return jsonify({"status": "ok", "message": f"{len(scores)} weekly scores saved for team {team_id}."})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# Public route for team breakdown (used in the "See More" modal)
@app.get("/pub/teams/<int:team_id>/breakdown")
def get_public_team_breakdown(team_id):
    """
    Fetches the full score history for a team to show in a public breakdown.
    """
    conn = getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT v.name as venue_name, tts.week_ending, tts.points
            FROM tournament_team_scores tts
            JOIN venues v ON tts.venue_id = v.id
            WHERE tts.tournament_team_id = %s AND tts.points > 0
            ORDER BY tts.week_ending DESC;
        """, (team_id,))
        
        breakdown = [{"venue": r[0], "week_ending": r[1].isoformat(), "points": r[2]} for r in cur.fetchall()]
        
        cur.execute("SELECT name FROM tournament_teams WHERE id = %s;", (team_id,))
        team_name = cur.fetchone()[0]

        return jsonify({"team_name": team_name, "breakdown": breakdown})
    finally:
        conn.close()


# --- Admin: Search endpoints (fast, limited) ---

@app.get("/admin/search/hosts")
def admin_search_hosts():
    q = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", "25")), 200)
    conn = getconn()
    try:
        cur = conn.cursor()
        if q:
            like = f"%{q}%"
            cur.execute(
                "SELECT id, name, phone, email FROM hosts "
                "WHERE LOWER(name) LIKE LOWER(%s) OR LOWER(email) LIKE LOWER(%s) "
                "ORDER BY name LIMIT %s;",
                (like, like, limit)
            )
        else:
            cur.execute(
                "SELECT id, name, phone, email FROM hosts ORDER BY name LIMIT %s;",
                (limit,)
            )
        rows = cur.fetchall()
        return jsonify([{"id": r[0], "name": r[1], "phone": r[2], "email": r[3]} for r in rows])
    finally:
        conn.close()

@app.get("/admin/search/venues")
def admin_search_venues():
    q = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", "25")), 200)
    conn = getconn()
    try:
        cur = conn.cursor()
        if q:
            like = f"%{q}%"
            cur.execute(
                "SELECT id, name, default_day, default_time, access_key "
                "FROM venues WHERE LOWER(name) LIKE LOWER(%s) "
                "ORDER BY name LIMIT %s;",
                (like, limit)
            )
        else:
            cur.execute(
                "SELECT id, name, default_day, default_time, access_key "
                "FROM venues ORDER BY name LIMIT %s;",
                (limit,)
            )
        rows = cur.fetchall()
        return jsonify([
            {"id": r[0], "name": r[1], "default_day": r[2], "default_time": r[3], "access_key": r[4]}
        for r in rows])
    finally:
        conn.close()

@app.get("/admin/search/teams")
def admin_search_teams():
    q = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", "25")), 200)
    conn = getconn()
    try:
        cur = conn.cursor()
        if q:
            like = f"%{q}%"
            cur.execute(
                "SELECT tt.id, tt.name, tt.home_venue_id, v.name AS home_venue_name, "
                "tt.captain_name, tt.captain_email, tt.captain_phone, tt.player_count "
                "FROM tournament_teams tt "
                "LEFT JOIN venues v ON tt.home_venue_id=v.id "
                "WHERE LOWER(tt.name) LIKE LOWER(%s) OR LOWER(tt.captain_email) LIKE LOWER(%s) "
                "ORDER BY tt.name LIMIT %s;",
                (like, like, limit)
            )
        else:
            cur.execute(
                "SELECT tt.id, tt.name, tt.home_venue_id, v.name AS home_venue_name, "
                "tt.captain_name, tt.captain_email, tt.captain_phone, tt.player_count "
                "FROM tournament_teams tt "
                "LEFT JOIN venues v ON tt.home_venue_id=v.id "
                "ORDER BY tt.name LIMIT %s;",
                (limit,)
            )
        rows = cur.fetchall()
        return jsonify([{
            "id": r[0], "name": r[1], "home_venue_id": r[2], "home_venue": r[3],
            "captain_name": r[4], "captain_email": r[5], "captain_phone": r[6],
            "player_count": r[7]
        } for r in rows])
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
                   e.is_validated,         -- NEW FIELD (from previous turn)
                   e.created_at, e.updated_at
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
            "is_validated": e[14],
            "created_at": e[15].isoformat() if e[15] else None,
            "updated_at": e[16].isoformat() if e[16] else None,
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

@app.put("/admin/events/<int:eid>/participation")
def admin_replace_participation(eid):
    d = request.json or {}
    teams = d.get("teams") or []
    if not isinstance(teams, list):
        return jsonify({"error": "teams must be an array"}), 400

    conn = getconn()
    try:
        cur = conn.cursor()
        
        # --- Start of Fix ---
        # 1. Fetch the full event data needed for the AI recap first.
        cur.execute("""
            SELECT 
                e.id, e.event_date, e.highlights, e.pdf_url, e.ai_recap, 
                e.status, e.fb_event_url, e.show_type,
                h.name AS host_name, v.name AS venue_name, 
                v.default_day, v.default_time
            FROM events e
            LEFT JOIN hosts h ON e.host_id = h.id
            LEFT JOIN venues v ON e.venue_id = v.id
            WHERE e.id = %s;
        """, (eid,))
        event_row = cur.fetchone()
        if not event_row:
            return jsonify({"error": "Event not found"}), 404
            
        # 2. Map the row to the dictionary that format_ai_recap expects.
        event_data = {
            "id": event_row[0], "event_date": event_row[1], "highlights": event_row[2],
            "pdf_url": event_row[3], "ai_recap": event_row[4], "status": event_row[5],
            "fb_event_url": event_row[6], "show_type": event_row[7], "host_name": event_row[8],
            "venue_name": event_row[9]
        }
        venue_defaults = {"default_day": event_row[10], "default_time": event_row[11]}
        # --- End of Fix ---

        cur.execute("DELETE FROM event_participation WHERE event_id=%s", (eid,))
        
        # Sort teams by position from the frontend payload to find the winners
        teams.sort(key=lambda t: t.get('position') or float('inf'))
        winners = []

        for t in teams:
            # Re-populate winners list based on the new, sorted data
            if t.get("position") in (1, 2, 3) and len(winners) < 3:
                winners.append({
                    "name": t.get("team_name"),
                    "score": t.get("score"),
                    "playerCount": t.get("num_players"),
                })

            cur.execute("""
                INSERT INTO event_participation
                (event_id, team_name, score, position, num_players, is_visiting, is_tournament, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
            """, (
                eid, t.get("team_name"), t.get("score"), t.get("position"),
                t.get("num_players"), bool(t.get("is_visiting")), bool(t.get("is_tournament"))
            ))

        # Now, call format_ai_recap with the correct dictionary and the new winners list
        if winners:
            ai_text = format_ai_recap(event_data, winners, venue_defaults)
            cur.execute("UPDATE events SET ai_recap=%s, updated_at=NOW() WHERE id=%s;", (ai_text, eid))

        conn.commit()
        return jsonify({"status": "ok", "count": len(teams)})
    except Exception as e:
        conn.rollback()
        logger.exception("admin_replace_participation failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# Save Tournament Scores
def get_week_ending(event_date: date) -> date:
    # weekday() returns Monday is 0 and Sunday is 6
    days_until_sunday = 6 - event_date.weekday()
    return event_date + timedelta(days=days_until_sunday)

@app.put("/admin/events/<int:event_id>/tournament-scores")
def save_tournament_scores_for_event(event_id):
    """
    Saves or updates tournament scores for an event.
    This version STRICTLY checks that the event's date falls within a pre-defined
    tournament week from the 'tournament_weeks' table. It will NOT create new weeks.
    """
    conn = None
    try:
        # --- Robust JSON Parsing (from previous fix) ---
        data = request.get_json(silent=True)
        if data is None:
            logging.warning(f"Could not parse JSON from headers for event {event_id}. Attempting raw body.")
            try:
                data = json.loads(request.data)
            except json.JSONDecodeError:
                return jsonify({"error": "Malformed JSON in request body."}), 400
        
        teams = data.get("teams")
        if not isinstance(teams, list):
            return jsonify({"error": "Request body must contain a 'teams' list."}), 400

        conn = getconn()
        cur = conn.cursor()

        # 1. Get event details (venue_id, event_date)
        cur.execute("SELECT venue_id, event_date FROM events WHERE id = %s;", (event_id,))
        event_details = cur.fetchone()
        if not event_details:
            return jsonify({"error": f"Event with id {event_id} not found."}), 404
        
        venue_id, event_date = event_details
        if not venue_id or not event_date:
            return jsonify({"error": "Event is missing required venue_id or event_date."}), 400

        # --- NEW LOGIC: STRICTLY FIND THE TOURNAMENT WEEK ---
        # 2. Calculate the theoretical week-ending date (the Sunday of the event's week)
        day_of_week = event_date.weekday()  # Monday=0, Sunday=6
        days_to_sunday = 6 - day_of_week
        week_ending_date = event_date + timedelta(days=days_to_sunday)

        # 3. Look up this date in the pre-populated tournament_weeks table.
        cur.execute("SELECT id FROM tournament_weeks WHERE week_ending = %s;", (week_ending_date,))
        week_row = cur.fetchone()
        
        if not week_row:
            # If no week is found, stop and return a clear error.
            error_msg = f"No valid tournament week found for the week ending {week_ending_date}. Please ensure this week exists in the system before saving scores."
            logging.warning(f"Failed to save scores for event {event_id}: {error_msg}")
            return jsonify({"error": error_msg}), 404 # 404 is appropriate as a required resource (the week) is missing.

        week_id = week_row[0]
        # --- END OF NEW LOGIC ---

        # 4. Loop through teams and perform an UPSERT (this logic remains the same)
        upserted_count = 0
        for team_data in teams:
            if not isinstance(team_data, dict):
                logging.error(f"FATAL: Item in 'teams' list was not a dictionary. Type: {type(team_data)}")
                return jsonify({"error": "Invalid data structure in 'teams' array."}), 400

            team_id = team_data.get("team_id")
            points = team_data.get("points")
            num_players = team_data.get("num_players")

            if team_id is None or points is None:
                continue

            cur.execute(
                """
                INSERT INTO tournament_team_scores
                    (tournament_team_id, venue_id, week_id, event_id, points, num_players, is_validated)
                VALUES (%s, %s, %s, %s, %s, %s, true)
                ON CONFLICT (tournament_team_id, venue_id, week_id)
                DO UPDATE SET
                    points = EXCLUDED.points,
                    num_players = EXCLUDED.num_players,
                    event_id = EXCLUDED.event_id,
                    is_validated = true,
                    updated_at = NOW();
                """,
                (team_id, venue_id, week_id, event_id, points, num_players)
            )
            upserted_count += 1
        
        conn.commit()
        return jsonify({
            "status": "ok",
            "message": f"Successfully saved/updated {upserted_count} scores for the week ending {week_ending_date.strftime('%Y-%m-%d')}.",
            "event_id": event_id,
            "week_id": week_id
        })

    except Exception as e:
        if conn:
            conn.rollback()
        logging.exception(f"Critical failure in save_tournament_scores for event {event_id}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
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

#admin initial seed validation
@app.post("/admin/events/batch-validate-by-criteria")
def admin_batch_validate_by_criteria():
    """
    Flags events as validated if they have a PDF and more than 3 photos.
    This is an admin utility for initial data bootstrapping.
    """
    conn = getconn()
    try:
        cur = conn.cursor()

        # SQL to find events that meet the criteria:
        # 1. pdf_url is not NULL
        # 2. Have more than 3 associated photos
        # 3. Are not already validated (optional, to prevent redundant updates)
        cur.execute("""
            WITH EventsToValidate AS (
                SELECT e.id
                FROM events e
                LEFT JOIN event_photos ep ON e.id = ep.event_id
                WHERE e.pdf_url IS NOT NULL
                GROUP BY e.id
                HAVING COUNT(ep.id) > 3
            )
            UPDATE events
            SET is_validated = TRUE,
                updated_at = NOW()
            WHERE id IN (SELECT id FROM EventsToValidate)
              AND is_validated = FALSE; -- Only update if not already validated
        """)
        updated_count = cur.rowcount
        conn.commit()

        if updated_count > 0:
            logger.info(f"Batch validation: {updated_count} events validated based on criteria.")
            return jsonify({"status": "ok", "message": f"{updated_count} events have been validated based on criteria (PDF exists and >3 photos)."})
        else:
            return jsonify({"status": "info", "message": "No new events matched the criteria for validation or they were already validated."})

    except Exception as e:
        conn.rollback()
        logger.exception("admin_batch_validate_by_criteria failed")
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
def validate_tournament_scores(venue_id, week_ending):
    """
    Updates tournament_team_scores for the matching event at venue_id in week_ending.
    - Finds/creates week_id from tournament_weeks using week_ending.
    - Finds matching event_id.
    - Inserts rows from body into tournament_team_scores, mapping team_name to tournament_team_id.
    - Sets is_validated = true.
    Body: { teams: [ { position, team_name, score, num_players, is_visiting, is_tournament, team_id? (optional) } ] }
    Note: Maps score to points; assumes position not directly used (add if needed).
    """
    data = request.json or {}
    teams = data.get("teams") or []
    if not isinstance(teams, list) or not teams:
        return jsonify({"error": "Body must include 'teams' array with participation data"}), 400

    conn = getconn()
    try:
        cur = conn.cursor()

        # 1. Parse week_ending and calculate range (Mon-Sun)
        try:
            end_date = datetime.strptime(week_ending, "%Y-%m-%d").date()
            if end_date.weekday() != 6:
                return jsonify({"error": "week_ending must be a Sunday (YYYY-MM-DD)"}), 400
            start_date = end_date - timedelta(days=6)
        except ValueError:
            return jsonify({"error": "Invalid week_ending format (YYYY-MM-DD)"}), 400

        # 2. Find/create week_id in tournament_weeks
        cur.execute("SELECT id FROM tournament_weeks WHERE week_ending = %s;", (end_date,))
        week_row = cur.fetchone()
        if week_row:
            week_id = week_row[0]
        else:
            # Create if missing (adjust columns if more needed, e.g., start_date)
            cur.execute(
                """
                INSERT INTO tournament_weeks (week_ending) VALUES (%s) RETURNING id;
                """,
                (end_date,)
            )
            week_id = cur.fetchone()[0]
            logger.info(f"Created tournament_weeks id {week_id} for {week_ending}")

        # 3. Find matching event_id
        cur.execute(
            """
            SELECT id FROM events
            WHERE venue_id = %s
              AND event_date >= %s
              AND event_date <= %s
            LIMIT 1
            """,
            (venue_id, start_date, end_date)
        )
        event_row = cur.fetchone()
        if not event_row:
            return jsonify({"error": f"No event found for venue {venue_id} in week ending {week_ending}"}), 404

        event_id = event_row[0]

        # 4. Insert into tournament_team_scores, mapping team_name to tournament_team_id
        inserted = 0
        for team in teams:
            team_name = team.get("team_name")
            team_id = team.get("team_id")  # Use if provided

            # Map if team_id not provided
            if not team_id and team_name:
                cur.execute("SELECT id FROM tournament_teams WHERE lower(name) = lower(%s);", (team_name,))
                id_row = cur.fetchone()
                if not id_row:
                    return jsonify({"error": f"Team '{team_name}' not found in tournament_teams"}), 404
                team_id = id_row[0]

            # Insert (adjust if you want upsert instead of insert)
            cur.execute(
                """
                INSERT INTO tournament_team_scores 
                    (tournament_team_id, venue_id, week_id, event_id, points, num_players, is_validated, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, true, NOW());
                """,
                (
                    team_id,
                    venue_id,
                    week_id,
                    event_id,
                    team.get("score"),  # Maps to points
                    team.get("num_players"),
                )
            )
            inserted += 1

        conn.commit()
        return jsonify({
            "status": "ok",
            "message": "tournament_team_scores updated with manual data and is_validated set to true",
            "event_id": event_id,
            "week_id": week_id,
            "inserted_count": inserted
        })

    except Exception as e:
        conn.rollback()
        logger.exception(f"Score update failed for venue {venue_id} week {week_ending}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()        
@app.post("/admin/bulk-upload-tournament-teams")
def admin_bulk_upload_tournament_teams():
    """
    Bulk upload:
      - Tournament teams (upsert with venue matching, no venue creation)
      - Events: skip duplicates; new ones are auto-validated and marked 'posted'
    Duplicate event rule: same venue_id and event_date already exists.
    Body:
      {
        "teams": [ { Name, HomeVenue, DefaultNight, CaptainName, CaptainEmail, CaptainCell, PlayerCount } ],
        "events": [ { hostName, venueName, eventDate, highlights?, pdfUrl?, photoUrls?[] } ]
      }
    """
    payload = request.json or {}
    teams_data: List[Dict[str, Any]] = payload.get("teams") or []
    events_data: List[Dict[str, Any]] = payload.get("events") or []

    if not isinstance(teams_data, list) or not isinstance(events_data, list):
        return jsonify({"error": "teams and events must be arrays"}), 400

    results = {
        "teams": {
            "total_attempted": 0,
            "teams_created": 0,
            "teams_updated": 0,
            "venues_not_found": 0,
            "skipped_errors": 0,
            "errors": []
        },
        "events": {
            "total_attempted": 0,
            "inserted": 0,
            "duplicates_skipped": 0,
            "errors": [],
            "inserted_ids": [],
            "duplicate_samples": []
        }
    }

    conn = getconn()
    try:
        cur = conn.cursor()

        # ------- Venue cache for team fuzzy matching -------
        cur.execute("SELECT id, name, default_day FROM venues;")
        all_venues_db_rows = cur.fetchall()

        venue_exact_normalized_lookup = {}
        venue_fuzzy_list = []
        for v_id, v_name, v_default_day in all_venues_db_rows:
            normalized_name = re.sub(r"[^a-z0-9\s]", "", (v_name or "").lower())
            venue_exact_normalized_lookup[normalized_name] = v_id
            venue_fuzzy_list.append({
                "id": v_id,
                "name_raw": v_name or "",
                "name_lower": (v_name or "").lower(),
                "name_normalized": normalized_name,
                "default_day_lower": (v_default_day or "").lower()
            })

        # ------- Helper: resolve host/venue ids by name (create if missing for hosts, not venues) -------
        def resolve_host_id(name: str) -> int:
            cur.execute("SELECT id FROM hosts WHERE lower(name)=lower(%s);", (name,))
            r = cur.fetchone()
            if r:
                return r[0]
            cur.execute("INSERT INTO hosts (name) VALUES (%s) RETURNING id;", (name,))
            return cur.fetchone()[0]

        def resolve_venue_id_strict(name: str) -> int:
            cur.execute("SELECT id FROM venues WHERE lower(name)=lower(%s);", (name,))
            r = cur.fetchone()
            if r:
                return r[0]
            # Do NOT create new venues here
            raise ValueError(f"Venue '{name}' not found")

        # ------- TEAMS: upsert with fuzzy venue matching (no venue creation) -------
        for team_entry in teams_data:
            results["teams"]["total_attempted"] += 1
            try:
                team_name = str(team_entry.get("Name") or "").strip()
                home_venue_name_raw = str(team_entry.get("HomeVenue") or "").strip()
                captain_name = str(team_entry.get("CaptainName") or "").strip()
                captain_email = str(team_entry.get("CaptainEmail") or "").strip().lower()
                captain_phone = str(team_entry.get("CaptainCell") or "").strip()
                player_count = team_entry.get("PlayerCount")
                default_night_raw = str(team_entry.get("DefaultNight") or "").strip()

                if not team_name:
                    raise ValueError("Team 'Name' is required")

                home_venue_id = None
                if home_venue_name_raw:
                    input_norm = re.sub(r"[^a-z0-9\s]", "", home_venue_name_raw.lower())
                    target_day = (default_night_raw or "").lower()

                    # exact normalized
                    home_venue_id = venue_exact_normalized_lookup.get(input_norm)
                    # fuzzy with default night filter
                    if home_venue_id is None:
                        candidates = []
                        for v in venue_fuzzy_list:
                            if v["default_day_lower"] == target_day:
                                ratio = difflib.SequenceMatcher(None, input_norm, v["name_normalized"]).ratio()
                                if ratio > 0.6:
                                    candidates.append((v, ratio))
                        candidates.sort(key=lambda x: x[1], reverse=True)
                        if candidates and candidates[0][1] > 0.7:
                            best, best_ratio = candidates[0]
                            ambiguous = len(candidates) > 1 and (best_ratio - candidates[1][1] < 0.1)
                            if not ambiguous:
                                home_venue_id = best["id"]
                                logger.info(f"Fuzzy matched '{home_venue_name_raw}' -> '{best['name_raw']}' ({best_ratio:.2f})")
                            else:
                                results["teams"]["venues_not_found"] += 1
                                names = [d["name_raw"] for d, r in candidates if r > 0.6]
                                raise ValueError(f"HomeVenue '{home_venue_name_raw}' ambiguous: {', '.join(names)}")
                        else:
                            results["teams"]["venues_not_found"] += 1
                            raise ValueError(f"HomeVenue '{home_venue_name_raw}' not found (fuzzy)")

                # Upsert team by name
                cur.execute("SELECT id FROM tournament_teams WHERE lower(name)=lower(%s);", (team_name,))
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """
                        UPDATE tournament_teams
                           SET home_venue_id=%s, captain_name=%s, captain_email=%s,
                               captain_phone=%s, player_count=%s
                         WHERE id=%s
                        """,
                        (home_venue_id, captain_name, captain_email, captain_phone, player_count, row[0])
                    )
                    results["teams"]["teams_updated"] += 1
                else:
                    cur.execute(
                        """git
                        INSERT INTO tournament_teams
                            (name, home_venue_id, captain_name, captain_email, captain_phone, player_count)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (team_name, home_venue_id, captain_name, captain_email, captain_phone, player_count)
                    )
                    results["teams"]["teams_created"] += 1

            except Exception as e:
                results["teams"]["skipped_errors"] += 1
                tn = (team_entry.get("Name") or "UNKNOWN")
                results["teams"]["errors"].append(f"Team '{tn}': {e}")
                logger.error(f"Bulk team error: {e}", exc_info=True)

        # ------- EVENTS: skip duplicates, auto-validate/post new -------
        for ev in events_data:
            results["events"]["total_attempted"] += 1
            try:
                host_name = (ev.get("hostName") or "").strip()
                venue_name = (ev.get("venueName") or "").strip()
                event_date = (ev.get("eventDate") or "").strip()  # YYYY-MM-DD
                highlights = ev.get("highlights") or ""
                pdf_url = ev.get("pdfUrl") or ""
                photo_urls = ev.get("photoUrls") or []

                if not host_name or not venue_name or not event_date:
                    raise ValueError("hostName, venueName, and eventDate are required")

                host_id = resolve_host_id(host_name)
                venue_id = resolve_venue_id_strict(venue_name)

                # Duplicate check: venue_id + event_date
                cur.execute(
                    "SELECT id FROM events WHERE venue_id=%s AND event_date=%s LIMIT 1;",
                    (venue_id, event_date),
                )
                existing = cur.fetchone()
                if existing:
                    results["events"]["duplicates_skipped"] += 1
                    if len(results["events"]["duplicate_samples"]) < 20:
                        results["events"]["duplicate_samples"].append(existing[0])
                    continue

                # Insert event
                cur.execute(
                    """
                    INSERT INTO events (host_id, venue_id, event_date, highlights, pdf_url, status)
                    VALUES (%s,%s,%s,%s,%s,'ready') RETURNING id;
                    """,
                    (host_id, venue_id, event_date, highlights, pdf_url),
                )
                event_id = cur.fetchone()[0]

                # Insert photos
                for url in photo_urls:
                    cur.execute(
                        "INSERT INTO event_photos (event_id, photo_url) VALUES (%s,%s);",
                        (event_id, url),
                    )

                # Auto-validate/post: set status to 'posted' and stamp fb_event_url
                cur.execute(
                    "UPDATE events SET status='posted', fb_event_url=COALESCE(fb_event_url, 'historical-import') WHERE id=%s;",
                    (event_id,),
                )

                results["events"]["inserted"] += 1
                results["events"]["inserted_ids"].append(event_id)

            except Exception as e:
                results["events"]["errors"].append(str(e))
                logger.error(f"Bulk event error: {e}", exc_info=True)

        conn.commit()
        return jsonify({"status": "ok", "summary": results})

    except Exception as e:
        conn.rollback()
        logger.exception("bulk upload failed")
        return jsonify({"error": str(e), "partial": results}), 500
    finally:
        conn.close()

@app.post("/admin/bulk-upload-summary-events")
def admin_bulk_upload_summary_events():
    """
    Bulk uploads summary event data for a specific venue from a JSON array.
    Creates new events if they don't already exist for the given venue and date.
    Hosts will be created if they don't exist.

    Request body:
    {
      "venue_id": 123,
      "events": [
        { "Date": "1/13/25", "Host": "Taylor", "# of people": 19, "# of teams": 5, "Comments": "" },
        ...
      ],
      "options": { "validated": true, "posted": true }
    }
    """
    payload = request.json
    if not isinstance(payload, dict) or "venue_id" not in payload or "events" not in payload:
        return jsonify({"error": "Request body must be a JSON object with 'venue_id' and 'events' array"}), 400
    
    target_venue_id = payload.get("venue_id")
    events_data = payload.get("events")
    options = payload.get("options") or {}
    mark_validated = bool(options.get("validated", True))
    mark_posted = bool(options.get("posted", True))
    status_val = "posted" if mark_posted else "unposted"

    if not isinstance(target_venue_id, int):
        return jsonify({"error": "'venue_id' must be an integer"}), 400
    if not isinstance(events_data, list):
        return jsonify({"error": "'events' must be a JSON array"}), 400

    results = {
        "total_attempted": 0,
        "events_created": 0,
        "hosts_created": 0,
        "events_skipped_existing": 0,
        "skipped_errors": 0,
        "errors": []
    }

    conn = getconn()
    try:
        cur = conn.cursor()

        # Verify venue exists
        cur.execute("SELECT id FROM venues WHERE id=%s;", (target_venue_id,))
        if not cur.fetchone():
            return jsonify({"error": f"Target venue with ID {target_venue_id} not found."}), 404

        # Fetch all hosts once for quick lookup
        cur.execute("SELECT id, name FROM hosts;")
        all_hosts = cur.fetchall()
        host_lookup = { (name or "").lower(): host_id for host_id, name in all_hosts }

        def parse_date_flex(s: str):
            s = (s or "").strip()
            if not s:
                raise ValueError("Date is required.")
            # Try 4-digit year first, then 2-digit, allow single-digit M/D
            for fmt in ("%m/%d/%Y", "%-m/%-d/%Y", "%m/%d/%y", "%-m/%-d/%y"):
                try:
                    return datetime.strptime(s, fmt).date()
                except Exception:
                    continue
            # Windows strptime doesn't like %-m, %-d; attempt manual normalization:
            try:
                parts = s.split("/")
                if len(parts) == 3:
                    m = str(int(parts[0]))
                    d = str(int(parts[1]))
                    y = parts[2]
                    if len(y) == 2:
                        y = "20" + y
                    return datetime.strptime(f"{m}/{d}/{y}", "%m/%d/%Y").date()
            except Exception:
                pass
            raise ValueError(f"Unrecognized date format: {s}")

        for row in events_data:
            results["total_attempted"] += 1
            try:
                date_raw = str(row.get("Date") or "").strip()
                host_name_raw = str(row.get("Host") or "").strip()
                num_people = row.get("# of people")
                num_teams = row.get("# of teams")
                comments = str(row.get("Comments") or "").strip()

                if not date_raw or not host_name_raw:
                    raise ValueError("Date and Host are required for each row.")

                event_date = parse_date_flex(date_raw)

                # Find or create host
                host_key = host_name_raw.lower()
                host_id = host_lookup.get(host_key)
                if host_id is None:
                    cur.execute("INSERT INTO hosts (name) VALUES (%s) RETURNING id;", (host_name_raw,))
                    host_id = cur.fetchone()[0]
                    host_lookup[host_key] = host_id
                    results["hosts_created"] += 1

                # Check for existing event (venue_id + date)
                cur.execute(
                    "SELECT id FROM events WHERE venue_id=%s AND event_date=%s;",
                    (target_venue_id, event_date)
                )
                if cur.fetchone():
                    results["events_skipped_existing"] += 1
                    continue

                # Insert new event
                cur.execute(
                    """
                    INSERT INTO events (
                        host_id, venue_id, event_date, highlights,
                        total_players, total_teams,
                        status, is_validated, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id;
                    """,
                    (host_id, target_venue_id, event_date, comments,
                     num_people, num_teams, status_val, mark_validated)
                )
                new_event_id = cur.fetchone()[0]
                results["events_created"] += 1

            except Exception as e:
                results["skipped_errors"] += 1
                label = f"{row.get('Date','?')} - {row.get('Host','?')}"
                results["errors"].append(f"Row '{label}': {str(e)}")

        conn.commit()
        return jsonify({"status": "ok", "summary": results})
    except Exception as e:
        conn.rollback()
        logger.exception("admin_bulk_upload_summary_events failed")
        return jsonify({"error": f"Bulk upload failed: {str(e)}", "partial_results": results}), 500
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
        return jsonify({"error": "venue_id and week_ending required"}), 400
    
    conn = getconn()
    try:
        cur = conn.cursor()
        
        # Get week_id from week_ending date
        cur.execute("SELECT id FROM tournament_weeks WHERE week_ending = %s;", (week_ending,))
        week_row = cur.fetchone()
        if not week_row:
            return jsonify({"venue_id": int(venue_id), "week_ending": week_ending, "rows": []})
        week_id = week_row[0]
        
        # CORRECTED QUERY: Join with tournament_teams to get the team_id and name
        cur.execute("""
            SELECT
                tts.tournament_team_id,
                tt.name AS team_name,
                tts.points,
                tts.num_players
            FROM tournament_team_scores tts
            JOIN tournament_teams tt ON tts.tournament_team_id = tt.id
            WHERE tts.venue_id = %s AND tts.week_ending = %s AND tts.is_validated = TRUE
            ORDER BY tts.points DESC NULLS LAST, tt.name ASC;
        """, (venue_id, week_ending))
        
        rows = [{"team_id": r[0], "team_name": r[1], "points": r[2], "num_players": r[3]} for r in cur.fetchall()]
        
        return jsonify({"venue_id": int(venue_id), "week_ending": week_ending, "rows": rows})
    except Exception as e:
        logger.exception("pub_scores failed")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.get("/pub/tournament-standings")
def get_public_standings():
    venue_id = request.args.get("venue_id")
    if not venue_id:
        return jsonify({"error": "venue_id is required"}), 400
    
    conn = getconn()
    try:
        cur = conn.cursor()
        # Sums all points for teams whose HOME venue is the one requested
        cur.execute("""
            SELECT
                tt.name,
                SUM(tts.points_gained) as total_points
            FROM tournament_team_scores tts
            JOIN tournament_teams tt ON tts.tournament_team_id = tt.id
            WHERE tt.home_venue_id = %s
            GROUP BY tt.name
            ORDER BY total_points DESC;
        """, (venue_id,))
        rows = cur.fetchall()
        standings = [{"team_name": r[0], "total_points": r[1]} for r in rows]
        return jsonify(standings)
    finally:
        conn.close()

@app.get("/pub/teams/<int:team_id>/stats")
def get_team_stats(team_id):
    key = request.args.get("key")
    if not key:
        return jsonify({"error": "Access key required"}), 401
    
    conn = getconn()
    try:
        cur = conn.cursor()
        
        # Authenticate and get team info
        cur.execute("SELECT name, access_key FROM tournament_teams WHERE id=%s;", (team_id,))
        team_row = cur.fetchone()
        if not team_row or team_row[1] != key:
            return jsonify({"error": "Invalid team or access key"}), 403

        # Fetch weekly score breakdown
        cur.execute("""
            SELECT
                tts.week_ending,
                SUM(tts.points_gained) as weekly_points,
                json_agg(json_build_object('venue', v.name, 'points', tts.points_gained)) as events
            FROM tournament_team_scores tts
            JOIN venues v ON tts.venue_id = v.id
            WHERE tts.tournament_team_id = %s
            GROUP BY tts.week_ending
            ORDER BY tts.week_ending DESC;
        """, (team_id,))
        rows = cur.fetchall()
        
        weekly_summary = [{
            "week_ending": r[0].isoformat(),
            "weekly_points": r[1],
            "events": r[2]
        } for r in rows]

        return jsonify({"team_name": team_row[0], "weekly_summary": weekly_summary})
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
# PUBLIC ENDPOINT: Venue Stats for Owners
# ------------------------------------------------------------------------------
@app.get("/pub/venues/<slug>/stats")
def pub_venue_stats_secure(slug):
    conn = getconn()
    try:
        # Authentication via access_key query parameter
        access_key = request.args.get("key")
        if not access_key:
            return jsonify({"error": "Access key is required."}), 401

        cur = conn.cursor()

        # Fetch all venues to find the one matching the slug and verify its key.
        cur.execute("SELECT id, name, default_day, default_time, access_key FROM venues;")
        venues_raw = cur.fetchall()

        venue_info = None
        for v_id, v_name, v_default_day, v_default_time, v_access_key in venues_raw:
            # Re-create slug from venue name to match frontend's generation logic
            venue_slug_from_db = re.sub(r'[^a-z0-9]+','-', (v_name or '').lower()).strip('-')
            if venue_slug_from_db == slug:
                venue_info = {
                    "id": v_id,
                    "name": v_name,
                    "default_day": v_default_day,
                    "default_time": v_default_time,
                    "access_key": v_access_key
                }
                break

        if not venue_info:
            return jsonify({"error":"Venue not found or invalid URL."}), 404
        
        if access_key != venue_info["access_key"]:
            return jsonify({"error": "Invalid access key for this venue."}), 403

        # If authenticated, proceed to fetch the detailed stats
        # NEW SQL: Use COALESCE to prioritize total_teams/total_players from 'events' table
        # then fallback to aggregating from 'event_participation' if not directly available.
        cur.execute("""
            SELECT
                e.id, -- Added e.id for grouping
                e.event_date,
                h.name AS host_name,
                COALESCE(e.total_teams, COUNT(ep.id)) AS num_teams,
                COALESCE(e.total_players, SUM(ep.num_players)) AS num_players_total
            FROM events e
            LEFT JOIN hosts h ON e.host_id = h.id
            LEFT JOIN event_participation ep ON e.id = ep.event_id
            WHERE e.venue_id = %s AND e.is_validated = TRUE -- Filter for validated events
            GROUP BY e.id, e.event_date, h.name, e.total_teams, e.total_players -- Group by all non-aggregated columns
            ORDER BY e.event_date DESC;
        """, (venue_info["id"],))
        
        event_stats = []
        for r in cur.fetchall():
            event_stats.append({
                "event_id": r[0], # Added event_id to output
                "event_date": r[1].isoformat() if r[1] else None,
                "host_name": r[2],
                "num_teams": int(r[3]) if r[3] else 0,
                "num_players": int(r[4]) if r[4] else 0,
            })
        
        return jsonify({
            "venue_name": venue_info["name"],
            "default_day": venue_info["default_day"],
            "default_time": venue_info["default_time"],
            "events": event_stats,
            "event_count": len(event_stats),
            "access_key_info": "Key validated successfully."
        })
    except Exception as e:
        logger.exception(f"pub_venue_stats_secure for slug {slug} failed")
        return jsonify({"error": "An internal server error occurred."}), 500
    finally:
        conn.close()
# ------------------------------------------------------------------------------
# Entrypoint 
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))