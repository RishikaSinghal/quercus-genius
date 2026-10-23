import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from pydantic import BaseModel, Field
from north_mcp_python_sdk import NorthMCPServer

from datetime import datetime
from pypdf import PdfReader
from io import BytesIO

DEFAULT_PORT = int(os.getenv("QUERCUS_MCP_PORT", "3002"))

# For UofT Quercus, base is typically https://q.utoronto.ca
# Canvas API is under /api/v1
DEFAULT_BASE_URL = os.getenv("QUERCUS_BASE_URL", "https://q.utoronto.ca").rstrip("/")
API_BASE = f"{DEFAULT_BASE_URL}/api/v1"

# Put your Canvas token here via env var (recommended)
# export QUERCUS_TOKEN="..."
QUERCUS_TOKEN = os.getenv("QUERCUS_TOKEN", "").strip()

# Tool-name prefix (must be unique in North)
TOOL_PREFIX = os.getenv("TOOL_PREFIX", "rishika").strip() or "rishika"


# -----------------------
# MCP Server
# -----------------------
mcp = NorthMCPServer(
    "UofT Quercus Helper (Phase 1)", host="0.0.0.0", port=DEFAULT_PORT
)


# -----------------------
# Helpers
# -----------------------
class QuercusError(Exception):
    pass

from datetime import datetime, timezone

SEASON_RANK = {"winter": 0, "spring": 1, "summer": 2, "fall": 3}
TERM_NAME_RE = re.compile(r"\b(winter|spring|summer|fall)\b.*?\b(\d{4})\b", re.IGNORECASE)

def _parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def _term_key_from_name(term_name: Optional[str]) -> Optional[Tuple[int, int]]:
    if not term_name:
        return None
    m = TERM_NAME_RE.search(term_name)
    if not m:
        return None
    season = m.group(1).lower()
    year = int(m.group(2))
    return (year, SEASON_RANK.get(season, -1))

def _term_key(term_obj: Optional[Dict[str, Any]]) -> Tuple[int, int, float]:
    if not term_obj:
        return (-1, -1, float("-inf"))

    start_dt = _parse_iso_dt(term_obj.get("start_at"))
    if start_dt:
        # date-based primary signal
        return (9999, 9999, start_dt.timestamp())

    nk = _term_key_from_name(term_obj.get("name"))
    if nk:
        year, season = nk
        return (year, season, float("-inf"))

    return (-1, -1, float("-inf"))

def _term_is_currentish(term_obj: Optional[Dict[str, Any]], now: datetime) -> bool:
    if not term_obj:
        return False
    start_dt = _parse_iso_dt(term_obj.get("start_at"))
    end_dt = _parse_iso_dt(term_obj.get("end_at"))
    if start_dt and now < start_dt:
        return False
    if end_dt and now > end_dt:
        return False
    return True

def _require_token() -> str:
    if not QUERCUS_TOKEN:
        raise QuercusError(
            "Missing QUERCUS_TOKEN. Set it in your shell:\n"
            'export QUERCUS_TOKEN="YOUR_CANVAS_ACCESS_TOKEN"\n'
            'export QUERCUS_BASE_URL="https://q.utoronto.ca"'
        )
    return QUERCUS_TOKEN


def _auth_headers() -> Dict[str, str]:
    token = _require_token()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _parse_link_header(link_header: str) -> Dict[str, str]:
    """
    Canvas pagination uses RFC5988 Link headers like:
      <.../api/v1/courses?page=2>; rel="next", <...>; rel="last"
    """
    links: Dict[str, str] = {}
    if not link_header:
        return links

    parts = [p.strip() for p in link_header.split(",")]
    for p in parts:
        m = re.match(r'<([^>]+)>\s*;\s*rel="([^"]+)"', p)
        if m:
            url, rel = m.group(1), m.group(2)
            links[rel] = url
    return links


@dataclass
class QuercusClient:
    base: str = API_BASE

    def _request(self, method: str, path_or_url: str, params: Optional[dict] = None) -> httpx.Response:
        headers = _auth_headers()
        url = path_or_url if path_or_url.startswith("http") else f"{self.base}{path_or_url}"
        with httpx.Client(timeout=30.0) as client:
            resp = client.request(method, url, headers=headers, params=params)
        return resp

    def get_json(self, path: str, params: Optional[dict] = None) -> Any:
        resp = self._request("GET", path, params=params)
        if resp.status_code >= 400:
            raise QuercusError(f"Canvas API error {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def get_paginated(self, path: str, params: Optional[dict] = None) -> List[Any]:
        """
        Fetch all pages for Canvas endpoints that paginate.
        """
        out: List[Any] = []
        next_url: Optional[str] = None

        # First request
        resp = self._request("GET", path, params=params)
        if resp.status_code >= 400:
            raise QuercusError(f"Canvas API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        if isinstance(data, list):
            out.extend(data)
        else:
            # some endpoints return dicts; still return in a list for consistency
            out.append(data)

        link = resp.headers.get("Link", "")
        links = _parse_link_header(link)
        next_url = links.get("next")

        # Follow next links
        while next_url:
            resp2 = self._request("GET", next_url)
            if resp2.status_code >= 400:
                raise QuercusError(f"Canvas API error {resp2.status_code}: {resp2.text[:500]}")
            data2 = resp2.json()
            if isinstance(data2, list):
                out.extend(data2)
            else:
                out.append(data2)

            link2 = resp2.headers.get("Link", "")
            links2 = _parse_link_header(link2)
            next_url = links2.get("next")
        return out
        

    def list_my_enrollments(
        self,
        states: Optional[List[str]] = None,
        types: Optional[List[str]] = None,
        include: Optional[List[str]] = None,
        enrollment_term_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        GET /api/v1/users/self/enrollments
        """
        params: Dict[str, Any] = {"per_page": 100}

        if states:
            params["state[]"] = states
        if types:
            params["type[]"] = types
        if include:
            params["include[]"] = include
        if enrollment_term_id is not None:
            params["enrollment_term_id"] = enrollment_term_id

        return self.get_paginated("/users/self/enrollments", params=params)


        return out

    # ---- Core Canvas pulls ----
    # def list_active_courses(self, include_term: bool = True) -> List[Dict[str, Any]]:
    #     params: Dict[str, Any] = {
    #         "per_page": 100,
    #         "enrollment_state": "active",  # <-- add this
    #     }
    #     if include_term:
    #         params["include[]"] = "term"
    #     return self.get_paginated("/courses", params=params)
    
    def list_active_courses(
    self,
    enrollment_type: Optional[str] = None,
    enrollment_state: Optional[str] = "active",
    course_states: Optional[List[str]] = None,
    include: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        GET /api/v1/courses
        Supports enrollment_type, enrollment_state, state[], include[] per Canvas docs.
        """
        params: Dict[str, Any] = {"per_page": 100}

        if enrollment_type:
            params["enrollment_type"] = enrollment_type  # teacher/student/ta/observer/designer :contentReference[oaicite:6]{index=6}
        if enrollment_state:
            params["enrollment_state"] = enrollment_state  # active/invited_or_pending/completed :contentReference[oaicite:7]{index=7}
        if course_states:
            params["state[]"] = course_states  # unpublished/available/completed/deleted :contentReference[oaicite:8]{index=8}

        if include:
            # Canvas supports repeated include[] values :contentReference[oaicite:9]{index=9}
            params["include[]"] = include

        return self.get_paginated("/courses", params=params)

    
    def list_courses_most_recent_term(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        courses = self.list_active_courses(
            enrollment_type="student",
            enrollment_state="active",
            course_states=["available"],
            include=["term"],
        )


        # Prefer terms that look current by dates if available; else fall back to all
        dated_ok = [c for c in courses if _term_is_currentish((c.get("term") or None), now)]
        candidates = dated_ok if dated_ok else courses

        best_term = None
        best_key = (-1, -1, float("-inf"))
        for c in candidates:
            k = _term_key(c.get("term"))
            if k > best_key:
                best_key = k
                best_term = c.get("term")

        if not best_term:
            return {"most_recent_term": None, "courses": []}

        best_id = best_term.get("id")
        best_name = best_term.get("name")

        def same_term(t: Optional[Dict[str, Any]]) -> bool:
            if not t:
                return False
            if best_id is not None and t.get("id") == best_id:
                return True
            if best_name and t.get("name") == best_name:
                return True
            return False

        filtered = [c for c in candidates if same_term(c.get("term"))]
        return {"most_recent_term": best_term, "courses": filtered}

    
    def get_course(self, course_id: int, include_syllabus: bool = True, include_term: bool = True) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        includes: List[str] = []
        if include_syllabus:
            includes.append("syllabus_body")
        if include_term:
            includes.append("term")
        if includes:
            # Canvas allows include[]=syllabus_body etc.
            params["include[]"] = includes
        return self.get_json(f"/courses/{course_id}", params=params)

    def list_assignment_groups(self, course_id: int, include_assignments: bool = True) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"per_page": 100}
        if include_assignments:
            params["include[]"] = "assignments"
        return self.get_paginated(f"/courses/{course_id}/assignment_groups", params=params)

    def list_assignments(
        self,
        course_id: int,
        include: Optional[List[str]] = None,
        search_term: Optional[str] = None,
        bucket: Optional[str] = None,
        order_by: Optional[str] = None,
        override_assignment_dates: Optional[bool] = True,
        needs_grading_count_by_section: Optional[bool] = False,
        per_page: int = 100,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"per_page": min(max(per_page, 1), 100)}

        if include:
            params["include[]"] = include
        if search_term:
            params["search_term"] = search_term
        if bucket:
            params["bucket"] = bucket
        if order_by:
            params["order_by"] = order_by

        # Canvas expects booleans; httpx will serialize True->"true"
        if override_assignment_dates is not None:
            params["override_assignment_dates"] = override_assignment_dates
        if needs_grading_count_by_section is not None:
            params["needs_grading_count_by_section"] = needs_grading_count_by_section

        return self.get_paginated(f"/courses/{course_id}/assignments", params=params)


    def search_files(self, course_id: int, query: str) -> List[Dict[str, Any]]:
        params = {
            "per_page": 100,
            "search_term": query,
        }
        return self.get_paginated(f"/courses/{course_id}/files", params=params)

    def list_tabs(self, course_id: int) -> List[Dict[str, Any]]:
        # Useful if you want to know if "syllabus", "assignments", "files" tabs exist/visible
        return self.get_paginated(f"/courses/{course_id}/tabs", params={"per_page": 100})
    
    def get_front_page(self, course_id: int) -> Dict[str, Any]:
        # Canvas: GET /api/v1/courses/:course_id/front_page
        return self.get_json(f"/courses/{course_id}/front_page")

    def list_pages(self, course_id: int) -> List[Dict[str, Any]]:
        # Canvas: GET /api/v1/courses/:course_id/pages
        return self.get_paginated(f"/courses/{course_id}/pages", params={"per_page": 100})

    def get_page(self, course_id: int, page_url: str) -> Dict[str, Any]:
        # Canvas: GET /api/v1/courses/:course_id/pages/:url
        safe = page_url.strip()
        return self.get_json(f"/courses/{course_id}/pages/{safe}")



# shared client instance
qc = QuercusClient()

def _normalize_term_name(name: str) -> str:
    return (name or "").strip()

def _term_sort_key(term_name: str) -> Tuple[int, int]:
    """
    Turns term names like 'Winter 2026' into a sortable key.
    Higher key => later term.
    Season order: Winter(1), Spring(2), Summer(3), Fall(4)
    """
    season_rank = {"winter": 1, "spring": 2, "summer": 3, "fall": 4}
    s = (term_name or "").strip().lower()
    m = re.search(r"(winter|spring|summer|fall)\s+(\d{4})", s)
    if not m:
        return (0, 0)
    season = m.group(1)
    year = int(m.group(2))
    return (year, season_rank.get(season, 0))


def _html_to_text_basic(html: str) -> str:
    if not html:
        return ""
    # very lightweight strip; enough for searching grading keywords
    text = re.sub(r"<script.*?>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_grading_lines(text: str) -> List[str]:
    """
    Pull candidate 'grade distribution' lines from text.
    We look for patterns like:
      - Midterm 25%
      - Assignments: 40%
      - Labs (15%)
      - Final exam - 35%
    """
    if not text:
        return []

    # Keep it line-ish by splitting on sentence-ish separators too
    chunks = re.split(r"[\n\r•\u2022]+", text)
    chunks = [c.strip() for c in chunks if c.strip()]

    patterns = [
        r"\b\d{1,3}\s*%\b",
        r"\(\s*\d{1,3}\s*%\s*\)",
    ]

    out = []
    for c in chunks:
        if any(re.search(p, c) for p in patterns):
            # also prefer chunks with grading keywords
            if re.search(r"\b(grade|grading|weight|weighted|evaluation|mark|marks|assessment)\b", c, re.IGNORECASE) or len(c) < 140:
                out.append(c)

    # de-dup, preserve order
    seen = set()
    deduped = []
    for x in out:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            deduped.append(x)

    return deduped[:40]



# -----------------------
# Tool input models
# -----------------------
class AssignmentsListRequest(BaseModel):
    course_id: int = Field(..., description="Canvas course id")
    search_term: Optional[str] = Field(default=None, description="Partial assignment title to match.")
    bucket: Optional[str] = Field(
        default=None,
        description="Filter by bucket: past, overdue, undated, ungraded, unsubmitted, upcoming, future.",
    )
    order_by: Optional[str] = Field(
        default="position",
        description="Order: position, name, due_at",
    )
    include_submission: bool = Field(default=False, description="If true, include[]=submission.")
    include_all_dates: bool = Field(default=False, description="If true, include[]=all_dates.")
    include_overrides: bool = Field(default=False, description="If true, include[]=overrides.")
    override_assignment_dates: bool = Field(default=True, description="Apply overrides for the calling user.")
    needs_grading_count_by_section: bool = Field(default=False, description="Split needs_grading_count by section.")
    per_page: int = Field(default=100, description="Canvas page size (max 100).")
    compact: bool = Field(default=True, description="If true, return a simplified list; else return raw objects.")


class CourseIdByNameRequest(BaseModel):
    query: str = Field(
        ...,
        description="Course identifier query like 'ECE343', 'ece343h1', 'databases', etc."
    )
    role: Optional[str] = Field(
        default="student",
        description="Canvas enrollment_type filter: 'student', 'teacher', 'ta', 'observer', 'designer'."
    )
    enrollment_state: str = Field(
        default="active",
        description="Canvas enrollment_state filter: 'active', 'invited_or_pending', 'completed'."
    )
    course_states: Optional[List[str]] = Field(
        default=["available"],
        description="Canvas state[] filter. For students usually ['available']."
    )
    include_teachers: bool = Field(default=False, description="If true, include[]=teachers (if permitted).")
    include_tabs: bool = Field(default=False, description="If true, include[]=tabs.")
    include_term: bool = Field(default=True, description="If true, include[]=term.")
    max_results: int = Field(
        default=5,
        description="Maximum number of matching courses to return."
    )


class CourseFilterRequest(BaseModel):
    session: Optional[str] = Field(
        default=None,
        description="Optional term name filter like 'Winter 2026'. If provided, only courses matching this term are returned (best-effort). If 'current', returns most recent/current term.",
    )
    role: Optional[str] = Field(
        default=None,
        description="Canvas enrollment_type filter: 'student', 'teacher', 'ta', 'observer', 'designer'.",
    )
    enrollment_state: Optional[str] = Field(
        default="active",
        description="Canvas enrollment_state filter: 'active', 'invited_or_pending', 'completed'.",
    )
    course_states: Optional[List[str]] = Field(
        default=None,
        description="Canvas state[] filter: e.g. ['available'] for students. Allowed: unpublished, available, completed, deleted.",
    )
    include_teachers: bool = Field(default=True, description="If true, include[]=teachers (if permitted).")
    include_tabs: bool = Field(default=True, description="If true, include[]=tabs.")
    include_syllabus: bool = Field(default=False, description="If true, include[]=syllabus_body (can be large).")
    include_term: bool = Field(default=True, description="If true, include[]=term.")


class DeliverableItem(BaseModel):
    assignment_name: str
    weight: Optional[float] = None
    due_at: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    mark_gotten: Optional[float] = None
    percent_lost: Optional[float] = None


class EnrollmentCoursesRequest(BaseModel):
    session_term_id: Optional[int] = Field(
        default=None,
        description="Optional enrollment_term_id to filter (works on /users/self/enrollments).",
    )
    state: Optional[str] = Field(
        default="current_and_invited",
        description="Enrollment state filter. For user enrollments, synthetic states like 'current_and_invited' are allowed.",
    )

class EnrollmentListRequest(BaseModel):
    states: Optional[List[str]] = Field(
        default=None,
        description="Enrollment state[] filter. Examples: ['active'] or ['current_and_invited'] (synthetic states work on user enrollments).",
    )
    types: Optional[List[str]] = Field(
        default=None,
        description="Enrollment type[] filter. Examples: ['StudentEnrollment'], ['TeacherEnrollment']",
    )
    include: Optional[List[str]] = Field(
        default=None,
        description="include[] extras, e.g. ['uuid', 'avatar_url', 'group_ids', 'current_points']",
    )
    enrollment_term_id: Optional[int] = Field(
        default=None,
        description="Filter by enrollment_term_id (applies to /users/self/enrollments).",
    )
    compact: bool = Field(
        default=True,
        description="If true, return compact output; if false, return raw enrollments.",
    )


class DeliverablesDict(BaseModel):
    course_id: int
    course_name: str
    term_name: Optional[str] = None
    deliverables: List[DeliverableItem]


class SyllabusSearchResult(BaseModel):
    course_id: int
    course_name: str
    term_name: Optional[str] = None
    sources_checked: List[str]
    found_sources: List[dict]
    grading_lines: List[str]


def _download_pdf_text(url: str) -> str:
    """
    Download a PDF and extract text using pypdf.
    Best-effort; returns "" on failure.
    """
    if not url:
        return ""

    try:
        headers = _auth_headers()
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, headers=headers)
        if r.status_code >= 400:
            return ""
        data = r.content
        reader = PdfReader(BytesIO(data))
        texts = []
        for page in reader.pages[:12]:  # cap to avoid huge PDFs
            t = page.extract_text() or ""
            if t.strip():
                texts.append(t)
        return "\n".join(texts)
    except Exception:
        return ""


def _syllabus_crawl(course_id: int) -> Tuple[List[dict], str, List[str]]:
    """
    Search order:
      1) PDF with 'syllabus' in name (files search)
      2) Syllabus page: course.syllabus_body
      3) Home page: front_page body
      4) Files page: broader search terms
    Returns:
      found_sources (metadata list),
      combined_text (for grading extraction),
      sources_checked list
    """
    sources_checked = []
    found_sources: List[dict] = []
    combined_text_parts: List[str] = []

    # 1) PDF with syllabus in name
    sources_checked.append("files: search_term=syllabus (prefer pdf)")
    files = qc.search_files(course_id, query="syllabus")
    pdfs = []
    for f in files:
        name = (f.get("display_name") or f.get("filename") or "").lower()
        ctype = (f.get("content-type") or "").lower()
        if "syllabus" in name and ("pdf" in name or "pdf" in ctype):
            pdfs.append(f)

    for f in pdfs[:3]:
        # Canvas file objects often include 'url' or 'download_url'
        dl = f.get("url") or f.get("download_url") or ""
        found_sources.append({"type": "file_pdf", "display_name": f.get("display_name"), "id": f.get("id"), "download": dl})
        pdf_text = _download_pdf_text(dl)
        if pdf_text:
            combined_text_parts.append(pdf_text)

    # 2) syllabus_body (syllabus page)
    sources_checked.append("course: include[]=syllabus_body")
    try:
        course = qc.get_course(course_id, include_syllabus=True, include_term=True)
        syllabus_html = course.get("syllabus_body") or ""
        syllabus_text = _html_to_text_basic(syllabus_html)
        if syllabus_text:
            found_sources.append({"type": "syllabus_body", "len": len(syllabus_text)})
            combined_text_parts.append(syllabus_text)
    except Exception:
        pass

    # 3) home page (front page)
    sources_checked.append("front_page: /courses/:course_id/front_page")
    try:
        fp = qc.get_front_page(course_id)
        body = fp.get("body") or ""
        fp_text = _html_to_text_basic(body)
        if fp_text:
            found_sources.append({"type": "front_page", "title": fp.get("title"), "len": len(fp_text)})
            combined_text_parts.append(fp_text)
    except Exception:
        pass

    # 4) files page broader
    sources_checked.append("files: broader search (course outline / grading / evaluation)")
    broader_terms = ["course outline", "grading", "evaluation", "assessment", "outline"]
    for term in broader_terms:
        try:
            hits = qc.search_files(course_id, query=term)
        except Exception:
            hits = []
        for f in hits[:2]:
            name = (f.get("display_name") or f.get("filename") or "").lower()
            ctype = (f.get("content-type") or "").lower()
            if "pdf" in name or "pdf" in ctype:
                dl = f.get("url") or f.get("download_url") or ""
                found_sources.append({"type": "file_pdf", "display_name": f.get("display_name"), "id": f.get("id"), "download": dl})
                pdf_text = _download_pdf_text(dl)
                if pdf_text:
                    combined_text_parts.append(pdf_text)

    combined_text = "\n\n".join([p for p in combined_text_parts if p.strip()])
    return found_sources, combined_text, sources_checked


@mcp.tool()
def rishika_quercus_find_syllabus_and_grading(course_id: int) -> dict:
    """
    Crawls for syllabus content in the requested search order and extracts
    best-effort grading/weight lines from found text.
    """
    course = qc.get_course(course_id, include_syllabus=False, include_term=True)
    found_sources, combined_text, sources_checked = _syllabus_crawl(course_id)
    grading_lines = _extract_grading_lines(combined_text)

    out = SyllabusSearchResult(
        course_id=course_id,
        course_name=course.get("name", f"course_{course_id}"),
        term_name=(course.get("term") or {}).get("name"),
        sources_checked=sources_checked,
        found_sources=found_sources,
        grading_lines=grading_lines,
    )
    return out.model_dump()


# -----------------------
# MCP Tools
# -----------------------

@mcp.tool()
def rishika_quercus_get_assignments(request: AssignmentsListRequest) -> Any:
    """
    List assignments for a course via:
      GET /api/v1/courses/:course_id/assignments
    """
    include: List[str] = []
    if request.include_submission:
        include.append("submission")
    if request.include_all_dates:
        include.append("all_dates")
    if request.include_overrides:
        include.append("overrides")

    assignments = qc.list_assignments(
        course_id=request.course_id,
        include=include if include else None,
        search_term=request.search_term,
        bucket=request.bucket,
        order_by=request.order_by,
        override_assignment_dates=request.override_assignment_dates,
        needs_grading_count_by_section=request.needs_grading_count_by_section,
        per_page=request.per_page,
    )

    if not request.compact:
        return assignments

    out = []
    for a in assignments:
        out.append({
            "assignment_id": a.get("id"),
            "name": a.get("name"),
            "due_at": a.get("due_at"),
            "unlock_at": a.get("unlock_at"),
            "lock_at": a.get("lock_at"),
            "points_possible": a.get("points_possible"),
            "published": a.get("published"),
            "html_url": a.get("html_url"),
        })
    return out


@mcp.tool()
def rishika_quercus_list_my_enrollments(request: EnrollmentListRequest) -> Any:
    """
    Lists your own enrollments via GET /api/v1/users/self/enrollments.
    Use this to verify whether your token has access as a student.
    """
    enrollments = qc.list_my_enrollments(
        states=request.states,
        types=request.types,
        include=request.include,
        enrollment_term_id=request.enrollment_term_id,
    )

    if not request.compact:
        return enrollments

    out = []
    for e in enrollments:
        out.append({
            "enrollment_id": e.get("id"),
            "course_id": e.get("course_id"),
            "course_section_id": e.get("course_section_id"),
            "enrollment_term_id": e.get("enrollment_term_id"),
            "type": e.get("type"),
            "role": e.get("role"),
            "state": e.get("enrollment_state") or e.get("state"),
            "user_id": e.get("user_id") or (e.get("user") or {}).get("id"),
            "uuid": e.get("uuid"),
        })
    return out


@mcp.tool()
def rishika_quercus_healthcheck() -> dict:
    """
    Quick sanity check that the server is running and Quercus env vars exist.
    """
    return {
        "ok": True,
        "api_base": API_BASE,
        "has_token": bool(QUERCUS_TOKEN),
        "port": DEFAULT_PORT,
        "tool_prefix": TOOL_PREFIX,
    }


@mcp.tool()
def rishika_quercus_list_courses(request: CourseFilterRequest) -> List[dict]:
    """
    List active courses for the current Quercus user.

    If request.session is provided, filter by exact term name match.
    If request.session is NOT provided, automatically return only courses
    in the most recent term.
    """
    # If user explicitly asks for a term, keep your existing behavior:
    if request.session:
        courses = qc.list_active_courses(include_term=True)
        wanted = request.session.strip().lower()
        return [
            c for c in courses
            if ((c.get("term") or {}).get("name", "").strip().lower() == wanted)
        ]

    # Otherwise: auto-most-recent-term behavior
    out = qc.list_courses_most_recent_term()
    return out["courses"]


@mcp.tool()
def rishika_quercus_get_course(course_id: int) -> dict:
    """
    Get course details. Includes syllabus_body (if available) and term info.
    """
    return qc.get_course(course_id, include_syllabus=True, include_term=True)


@mcp.tool()
def rishika_quercus_build_deliverables_dict(course_id: int) -> dict:
    """
    Build deliverables dictionary:
      - Uses assignment groups + assignments (structured)
      - Then crawls syllabus sources to extract grading breakdown (best-effort)
      - Attempts to map extracted weight lines to assignments by name (best-effort)
    """
    course = qc.get_course(course_id, include_syllabus=False, include_term=True)
    course_name = course.get("name", f"course_{course_id}")
    term_name = (course.get("term") or {}).get("name")

    # 1) Structured assignments
    groups = qc.list_assignment_groups(course_id, include_assignments=True)

    # Build base deliverables from Canvas assignments
    deliverables: List[DeliverableItem] = []
    for g in groups:
        group_name = g.get("name", "")
        group_weight = g.get("group_weight")  # may be null
        assignments = g.get("assignments") or []
        for a in assignments:
            due_at = a.get("due_at")
            due_date, due_time = None, None
            if isinstance(due_at, str) and "T" in due_at:
                due_date = due_at.split("T", 1)[0]
                due_time = due_at.split("T", 1)[1].replace("Z", "")

            deliverables.append(
                DeliverableItem(
                    assignment_name=a.get("name", "Unnamed Assignment"),
                    # store group weight if individual weight unknown
                    weight=float(group_weight) if group_weight is not None else None,
                    due_at=due_at,
                    due_date=due_date,
                    due_time=due_time,
                    mark_gotten=None,
                    percent_lost=None,
                )
            )

    # 2) Crawl syllabus + extract grading lines
    found_sources, combined_text, sources_checked = _syllabus_crawl(course_id)
    grading_lines = _extract_grading_lines(combined_text)

    # 3) Best-effort mapping: if grading line mentions an assignment name + percent, attach it
    # Example line: "Midterm 25%" => match deliverable containing "midterm"
    for line in grading_lines:
        m = re.search(r"(\d{1,3})\s*%", line)
        if not m:
            continue
        pct = float(m.group(1))
        line_l = line.lower()

        # match to existing deliverables if names overlap
        for d in deliverables:
            name_l = (d.assignment_name or "").lower()
            if name_l and (name_l in line_l or line_l in name_l or _fuzzy_contains(name_l, line_l)):
                # overwrite with more specific weight if we found one
                d.weight = pct
                break

    model = DeliverablesDict(
        course_id=course_id,
        course_name=course_name,
        term_name=term_name,
        deliverables=deliverables,
    )

    # Attach meta so North can explain what it found
    return {
        **model.model_dump(),
        "syllabus_search": {
            "sources_checked": sources_checked,
            "found_sources": found_sources,
            "grading_lines": grading_lines,
        },
    }

@mcp.tool()
def rishika_quercus_get_course_id_by_name(request: CourseIdByNameRequest) -> List[dict]:
    """
    Returns the Canvas numeric course_id(s) that best match a query like 'ECE343'.
    """
    q = (request.query or "").strip()
    if not q:
        return []

    qn = _norm_course_text(q)

    include: List[str] = []
    if request.include_term:
        include.append("term")
    if request.include_teachers:
        include.append("teachers")
    if request.include_tabs:
        include.append("tabs")

    courses = qc.list_active_courses(
        enrollment_type=request.role,
        enrollment_state=request.enrollment_state,
        course_states=request.course_states,
        include=include if include else None,
    )

    scored = []
    for c in courses:
        s = _course_match_score(qn, c)
        if s > 0:
            scored.append((s, c))

    scored.sort(key=lambda x: x[0], reverse=True)

    out: List[dict] = []
    for s, c in scored[: max(1, request.max_results)]:
        out.append({
            "course_id": c.get("id"),
            "course_code": c.get("course_code"),
            "name": c.get("name"),
            "term": (c.get("term") or {}).get("name"),
            "workflow_state": c.get("workflow_state"),
            "match_score": s,
        })

    return out

def _fuzzy_contains(a: str, b: str) -> bool:
    """
    Loose match helper: checks whether a shortened keyword from b appears in a.
    Helps map 'final exam 35%' to assignment 'Final Exam' etc.
    """
    # Keep only words 3+ chars
    bw = [w for w in re.split(r"[^a-z0-9]+", b.lower()) if len(w) >= 3]
    if not bw:
        return False
    score = sum(1 for w in bw if w in a.lower())
    return score >= max(1, min(3, len(bw) // 2))

def _norm_course_text(s: Optional[str]) -> str:
    # lowercase, remove non-alphanumerics (spaces, dashes, etc.)
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

def _course_match_score(query_norm: str, course: Dict[str, Any]) -> int:
    """
    Higher score = better match.
    """
    code = course.get("course_code") or ""
    name = course.get("name") or ""

    code_n = _norm_course_text(code)
    name_n = _norm_course_text(name)

    # exact-ish matches get big points
    score = 0
    if query_norm == code_n:
        score += 1000
    if query_norm == name_n:
        score += 800

    # common case: query like ece343 is contained in course_code
    if query_norm and query_norm in code_n:
        score += 600

    # query contained in name
    if query_norm and query_norm in name_n:
        score += 350

    # prefix match helps for things like "ece343" vs "ece343h1s20261"
    if code_n.startswith(query_norm):
        score += 500
    if name_n.startswith(query_norm):
        score += 200

    return score



# -----------------------
# Run
# -----------------------
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
