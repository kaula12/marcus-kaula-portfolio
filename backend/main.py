import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DB_PATH = BASE_DIR / "portfolio.db"
UPLOAD_DIR = BASE_DIR / "uploads"
SEED_PATH = BASE_DIR / "seed.json"
FRONTEND_FILE = ROOT_DIR / "frontend" / "index.html"
IS_VERCEL = bool(os.getenv("VERCEL"))

ALLOWED_UPLOAD_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".mp4",
    ".webm",
    ".mov",
    ".pdf",
}

if IS_VERCEL and not UPLOAD_DIR.exists():
    UPLOAD_DIR = Path("/tmp/uploads")
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    UPLOAD_DIR = Path("/tmp/uploads")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "portfolio-media").strip() or "portfolio-media"

supabase_client = None
supabase_init_error: Optional[str] = None
if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    try:
        from supabase import create_client

        supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    except Exception as exc:
        supabase_init_error = str(exc)
        print(f"[WARN] Could not initialize Supabase client: {exc}")
else:
    missing_vars = []
    if not SUPABASE_URL:
        missing_vars.append("SUPABASE_URL")
    if not SUPABASE_SERVICE_ROLE_KEY:
        missing_vars.append("SUPABASE_SERVICE_ROLE_KEY")
    supabase_init_error = f"Missing environment variable(s): {', '.join(missing_vars)}"

app = FastAPI(title="Marcus Kaula Portfolio CMS API", version="1.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class UploadUrlRequest(BaseModel):
    filename: str
    content_type: Optional[str] = "application/octet-stream"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS portfolio_state (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)"
    )
    conn.commit()
    return conn


def _load_local_state() -> Dict[str, Any]:
    if IS_VERCEL:
        if DB_PATH.exists():
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            try:
                row = conn.execute("SELECT data FROM portfolio_state WHERE id = 1").fetchone()
                if row:
                    return json.loads(row[0])
            except Exception as exc:
                print(f"[WARN] Could not read bundled SQLite seed on Vercel: {exc}")
            finally:
                conn.close()
        if SEED_PATH.exists():
            return json.loads(SEED_PATH.read_text(encoding="utf-8"))
        return {}

    conn = get_conn()
    row = conn.execute("SELECT data FROM portfolio_state WHERE id = 1").fetchone()
    if row:
        conn.close()
        return json.loads(row[0])
    if SEED_PATH.exists():
        seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO portfolio_state (id, data) VALUES (1, ?)",
            (json.dumps(seed),),
        )
        conn.commit()
        conn.close()
        return seed
    conn.close()
    return {}


def _save_local_state(payload: Dict[str, Any]) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO portfolio_state (id, data) VALUES (1, ?)",
        (json.dumps(payload),),
    )
    conn.commit()
    conn.close()


def load_state() -> Dict[str, Any]:
    if supabase_client is not None:
        try:
            res = (
                supabase_client.table("portfolio_state")
                .select("data")
                .eq("id", 1)
                .limit(1)
                .execute()
            )
            if res.data and len(res.data) > 0 and isinstance(res.data[0].get("data"), dict):
                return res.data[0]["data"]
            # First-time boot on Supabase: seed from bundled SQLite/seed.json if present
            local_data = _load_local_state()
            if local_data:
                supabase_client.table("portfolio_state").upsert(
                    {"id": 1, "data": local_data}
                ).execute()
                return local_data
            return {}
        except Exception as exc:
            if IS_VERCEL:
                raise HTTPException(status_code=500, detail=f"Supabase read failed: {exc}")
            print(f"[WARN] Supabase read failed, falling back to local SQLite: {exc}")
    return _load_local_state()


def save_state(payload: Dict[str, Any]) -> None:
    if supabase_client is not None:
        try:
            supabase_client.table("portfolio_state").upsert(
                {"id": 1, "data": payload}
            ).execute()
            return
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Supabase save failed: {exc}")
    if IS_VERCEL:
        raise HTTPException(
            status_code=500,
            detail=f"Supabase is not configured on Vercel ({supabase_init_error or 'set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY'})",
        )
    _save_local_state(payload)


def get_expected_passcode(current_state: Optional[Dict[str, Any]] = None) -> str:
    data = current_state if current_state is not None else load_state()
    return str(
        data.get("profile", {}).get("passcode")
        or os.getenv("ADMIN_PASSCODE", "kaula12")
    )


def _extract_public_url(path: str) -> str:
    raw_pub = supabase_client.storage.from_(SUPABASE_BUCKET).get_public_url(path)
    if isinstance(raw_pub, dict):
        url = raw_pub.get("publicUrl") or raw_pub.get("public_url") or ""
    else:
        url = str(raw_pub)
    return url.rstrip("?")


def _normalize_signed_url(url: str) -> str:
    if url.startswith("/storage/v1/"):
        return f"{SUPABASE_URL.rstrip('/')}{url}"
    if url.startswith("/"):
        return f"{SUPABASE_URL.rstrip('/')}/storage/v1{url}"
    return url


@app.get("/api/health")
def health():
    return JSONResponse(
        content={
            "status": "ok",
            "supabase_connected": supabase_client is not None,
            "backend": "supabase" if supabase_client is not None else "local_sqlite",
            "bucket": SUPABASE_BUCKET,
            "storage_bucket": SUPABASE_BUCKET if supabase_client is not None else "local_uploads",
            "is_vercel": IS_VERCEL,
            "supabase_error": supabase_init_error,
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/api/portfolio")
def get_portfolio():
    data = load_state()
    sanitized = json.loads(json.dumps(data))
    if isinstance(sanitized.get("profile"), dict):
        sanitized["profile"].pop("passcode", None)
    return JSONResponse(
        content=sanitized,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.post("/api/auth/verify")
def verify_passcode(x_admin_passcode: str = Header(default="")):
    expected = get_expected_passcode()
    if not x_admin_passcode or x_admin_passcode != expected:
        raise HTTPException(status_code=401, detail="Invalid admin passcode")
    return {"authenticated": True}


@app.put("/api/portfolio")
def save_portfolio(
    payload: Dict[str, Any],
    x_admin_passcode: str = Header(default=""),
):
    current = load_state()
    expected = get_expected_passcode(current)
    if not x_admin_passcode or x_admin_passcode != expected:
        raise HTTPException(status_code=401, detail="Invalid admin passcode")

    if isinstance(payload.get("profile"), dict):
        new_pass = str(payload["profile"].get("passcode", "")).strip()
        payload["profile"]["passcode"] = new_pass if new_pass else expected

    save_state(payload)
    return {"status": "saved", "backend": "supabase" if supabase_client is not None else "local_sqlite"}


@app.post("/api/upload-url")
def create_upload_url(
    req: UploadUrlRequest,
    x_admin_passcode: str = Header(default=""),
):
    expected = get_expected_passcode()
    if not x_admin_passcode or x_admin_passcode != expected:
        raise HTTPException(status_code=401, detail="Invalid admin passcode")

    ext = Path(req.filename or "file.bin").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or 'unknown'}")

    if supabase_client is None:
        if IS_VERCEL:
            raise HTTPException(
                status_code=500,
                detail=f"Supabase Storage is not configured on Vercel ({supabase_init_error or 'set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY'})",
            )
        return {
            "mode": "proxy",
            "upload_endpoint": "/api/upload",
            "storage": "local",
        }

    safe_name = f"{uuid.uuid4().hex[:12]}{ext}"
    try:
        signed = supabase_client.storage.from_(SUPABASE_BUCKET).create_signed_upload_url(safe_name)
        signed_url = ""
        if isinstance(signed, dict):
            signed_url = signed.get("signed_url") or signed.get("signedUrl") or signed.get("url") or ""
        if not signed_url:
            raise RuntimeError(f"Unexpected signed upload URL response: {signed}")
        signed_url = _normalize_signed_url(signed_url)
        public_url = _extract_public_url(safe_name)
        return {
            "mode": "direct",
            "signed_url": signed_url,
            "public_url": public_url,
            "path": safe_name,
            "storage": "supabase",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not create Supabase upload URL: {exc}")


@app.post("/api/upload")
async def upload_media(
    file: UploadFile = File(...),
    x_admin_passcode: str = Header(default=""),
):
    expected = get_expected_passcode()
    if not x_admin_passcode or x_admin_passcode != expected:
        raise HTTPException(status_code=401, detail="Invalid admin passcode")

    ext = Path(file.filename or "file.bin").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or 'unknown'}")

    safe_name = f"{uuid.uuid4().hex[:12]}{ext}"
    content = await file.read()

    if supabase_client is not None:
        try:
            supabase_client.storage.from_(SUPABASE_BUCKET).upload(
                path=safe_name,
                file=content,
                file_options={
                    "content-type": file.content_type or "application/octet-stream",
                    "upsert": "false",
                },
            )
            public_url = _extract_public_url(safe_name)
            return {"url": public_url, "filename": file.filename, "storage": "supabase"}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Supabase upload failed: {exc}")

    if IS_VERCEL:
        raise HTTPException(
            status_code=500,
            detail=f"Supabase Storage is not configured on Vercel ({supabase_init_error or 'set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY'})",
        )

    dest = UPLOAD_DIR / safe_name
    dest.write_bytes(content)
    return {"url": f"/uploads/{safe_name}", "filename": file.filename, "storage": "local"}


app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get("/")
def serve_frontend():
    return FileResponse(FRONTEND_FILE)
