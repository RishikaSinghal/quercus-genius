import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query

CANVAS_BASE_URL = os.getenv("CANVAS_BASE_URL", "https://q.utoronto.ca/api/v1").rstrip("/")
CANVAS_TOKEN = os.getenv("CANVAS_TOKEN")

app = FastAPI(title="Canvas (Quercus) Tool Server")

def _headers() -> Dict[str, str]:
    if not CANVAS_TOKEN:
        raise HTTPException(status_code=500, detail="CANVAS_TOKEN env var not set")
    return {"Authorization": f"Bearer {CANVAS_TOKEN}"}

async def _get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{CANVAS_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(url, headers=_headers(), params=params)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

@app.get("/health")
def health():
    return {"ok": True, "canvas_base_url": CANVAS_BASE_URL}

@app.get("/canvas/me")
async def canvas_me():
    # GET /users/self
    return await _get_json("/users/self")

@app.get("/canvas/courses")
async def list_courses(
    enrollment_state: str = Query("active", description="active|invited|completed|inactive"),
    per_page: int = Query(50, ge=1, le=100),
):
    # GET /courses
    # Note: Canvas paginates; this returns one page (enough for MVP).
    return await _get_json("/courses", params={"enrollment_state": enrollment_state, "per_page": per_page})

@app.get("/canvas/courses/{course_id}/assignments")
async def list_assignments(
    course_id: int,
    per_page: int = Query(50, ge=1, le=100),
):
    return await _get_json(f"/courses/{course_id}/assignments", params={"per_page": per_page})

@app.get("/canvas/courses/{course_id}/announcements")
async def list_announcements(
    course_id: int,
    per_page: int = Query(50, ge=1, le=100),
):
    # Canvas discussions endpoint used for announcements
    return await _get_json(
        f"/courses/{course_id}/discussion_topics",
        params={"only_announcements": True, "per_page": per_page},
    )
