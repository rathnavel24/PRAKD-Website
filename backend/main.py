"""Prakd enquiry backend: POST /api/enquiries from the prakd.in contact form.

FastAPI + the standard library's sqlite3. Sits behind nginx on 127.0.0.1.
Run with:  uvicorn main:app --host 127.0.0.1 --port 8788
"""
import html
import json
import logging
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

log = logging.getLogger("uvicorn.error")

DB_PATH = Path(os.environ.get("DB_PATH") or Path(__file__).parent / "data" / "enquiries.db")
MAX_BODY = 32 * 1024
RATE_MAX, RATE_WINDOW = 5, 10 * 60  # 5 enquiries per IP per 10 minutes

TOPICS = {"Web & app development", "AI & automation", "Cloud, DevOps & hosting", "IT consulting & support"}
VENTURES: set[str] = set()
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Telegram notification for each new enquiry (same bot as the server alerts). Off if no token file.
TG_API = os.environ.get("TELEGRAM_API", "https://api.telegram.org")
TG_CHAT = os.environ.get("TELEGRAM_CHAT", "")
TG_TOKEN = ""
if os.environ.get("TELEGRAM_TOKEN_FILE"):
    try:
        TG_TOKEN = Path(os.environ["TELEGRAM_TOKEN_FILE"]).read_text().strip()
    except OSError as err:
        log.error("telegram disabled: %s", err)


def text(value: Any, limit: int) -> str:
    """Trimmed string cut to `limit`; anything that is not a string becomes empty."""
    return value.strip()[:limit] if isinstance(value, str) else ""


class Enquiry(BaseModel):
    """The form's fields. Input is cleaned rather than rejected: only name, email and message can fail."""

    name: str = ""
    email: str = ""
    company: str | None = None
    phone: str | None = None
    message: str | None = None
    topics: list[str] = []
    venture: str | None = None
    source: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v: Any) -> str:
        return text(v, 200)

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v: Any) -> str:
        return text(v, 254)

    @field_validator("company", mode="before")
    @classmethod
    def _company(cls, v: Any) -> str | None:
        return text(v, 200) or None

    @field_validator("phone", mode="before")
    @classmethod
    def _phone(cls, v: Any) -> str | None:
        return text(v, 50) or None

    @field_validator("message", mode="before")
    @classmethod
    def _message(cls, v: Any) -> str | None:
        return text(v, 5000) or None

    @field_validator("source", mode="before")
    @classmethod
    def _source(cls, v: Any) -> str | None:
        return text(v, 300) or None

    @field_validator("topics", mode="before")
    @classmethod
    def _topics(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            return []
        return list(dict.fromkeys(t for t in v if isinstance(t, str) and t in TOPICS))

    @field_validator("venture", mode="before")
    @classmethod
    def _venture(cls, v: Any) -> str | None:
        return v if isinstance(v, str) and v in VENTURES else None

    @model_validator(mode="after")
    def _required(self) -> "Enquiry":
        problems = []
        if not self.name:
            problems.append((["body", "name"], "Please enter your name."))
        if not self.message:
            problems.append((["body", "message"], "Please enter a message."))
        if not EMAIL_RE.match(self.email):
            problems.append((["body", "email"], "Please enter a valid email address."))
        if problems:
            raise PydanticCustomError("enquiry", "invalid enquiry", {"problems": problems})
        return self


class Received(BaseModel):
    id: str
    status: str = "received"
    createdAt: str | None = None


def notify(e: Enquiry) -> None:
    """Send the enquiry to Telegram. Runs after the response, so a slow Telegram never delays the visitor."""
    if not (TG_TOKEN and TG_CHAT):
        return
    esc = lambda v: html.escape(str(v or ""), quote=False)
    company = f" ({esc(e.company)})" if e.company else ""
    body = (
        f"📩 <b>New enquiry on prakd.in</b>\n\n<b>{esc(e.name)}</b>{company}\n{esc(e.email)}"
        f"\nTopics: {esc(', '.join(e.topics) or '-')}\n\n{esc((e.message or '')[:3000])}"
    )
    payload = {"chat_id": TG_CHAT, "text": body, "parse_mode": "HTML", "disable_web_page_preview": True}
    req = urllib.request.Request(
        f"{TG_API}/bot{TG_TOKEN}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=15).close()
    except urllib.error.HTTPError as err:
        log.error("telegram notify failed: HTTP %s", err.code)
    except Exception as err:  # never log the URL: it holds the bot token
        log.error("telegram notify failed: %s", type(err).__name__)


hits: dict[str, deque[float]] = {}  # ip -> times of recent enquiries
_last_sweep = time.monotonic()


def rate_limited(ip: str) -> bool:
    global _last_sweep
    now = time.monotonic()
    if now - _last_sweep > RATE_WINDOW:  # drop IPs that have gone quiet
        _last_sweep = now
        for key in [k for k, q in hits.items() if now - q[-1] >= RATE_WINDOW]:
            del hits[key]
    recent = hits.setdefault(ip, deque())
    while recent and now - recent[0] >= RATE_WINDOW:
        recent.popleft()
    if len(recent) >= RATE_MAX:
        return True
    recent.append(now)
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """CREATE TABLE IF NOT EXISTS enquiries (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  company TEXT, phone TEXT, message TEXT,
  topics TEXT NOT NULL DEFAULT '[]',
  venture TEXT, source TEXT, ip TEXT, user_agent TEXT
)"""
    )
    db.commit()
    app.state.db = db
    log.info("prakd-backend ready, db %s", DB_PATH)
    yield
    db.close()


# The interactive docs are off: this API only serves the site's own form.
app = FastAPI(title="Prakd enquiry backend", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse({"detail": "Our server had a problem. Please try again in a moment."}, status_code=500)


async def read_json(request: Request) -> Any:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY:
        raise HTTPException(413, "Request too large.")
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "Request too large.")
    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        raise HTTPException(400, "Invalid JSON body.")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/enquiries", status_code=201, response_model=Received, response_model_exclude_none=True)
async def create_enquiry(request: Request, background: BackgroundTasks):
    if "application/json" not in request.headers.get("content-type", ""):
        raise HTTPException(415, "Content-Type must be application/json.")
    body = await read_json(request)
    if not isinstance(body, dict):
        raise HTTPException(422, [{"msg": "Invalid request body."}])

    # Honeypot: real visitors never see the "website" field. Pretend it worked.
    if isinstance(body.get("website"), str) and body["website"].strip():
        return Received(id="enq_ok")

    try:
        e = Enquiry.model_validate(body)
    except ValidationError as err:
        problems = (err.errors()[0].get("ctx") or {}).get("problems") or [([], "Invalid request body.")]
        raise HTTPException(422, [{"loc": loc, "msg": msg} for loc, msg in problems])

    # nginx sets X-Client-IP (Cloudflare's CF-Connecting-IP for tunnel traffic, else the peer address)
    ip = request.headers.get("x-client-ip") or (request.client.host if request.client else "unknown")
    if rate_limited(ip):
        raise HTTPException(429, "Too many enquiries from your connection. Please try again later.")

    enquiry_id = f"enq_{secrets.token_hex(10)}"
    created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    db: sqlite3.Connection = request.app.state.db
    db.execute(
        """INSERT INTO enquiries
  (id, created_at, name, email, company, phone, message, topics, venture, source, ip, user_agent)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (enquiry_id, created_at, e.name, e.email, e.company, e.phone, e.message, json.dumps(e.topics, separators=(",", ":"), ensure_ascii=False),
         e.venture, e.source, ip, text(request.headers.get("user-agent"), 300) or None),
    )
    db.commit()
    log.info("enquiry %s from %s", enquiry_id, e.email)
    background.add_task(notify, e)
    return Received(id=enquiry_id, createdAt=created_at)
