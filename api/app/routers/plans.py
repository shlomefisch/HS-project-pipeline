"""Order assembly, first part: plans on the job, footage per area, the takeoff task."""

from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import admin, member, writer
from ..db import get_db
from ..models import AppSetting, Area, CandidateTag, JobFile, Task, User
from ..rules.constants import TASK_OPEN
from ..schemas import FileUpdate, FootageSet, LinkAdd, NextStep, SettingsUpdate, TakeoffRequest
from ..serialize import row, user_out
from ..services import files as F
from ..services.jobs import get_job
from ..services.tasks import active_user, create_task
from ..timeutil import now, today

router = APIRouter(tags=["plans"])

UPLOAD_LIMIT = 25 * 1024 * 1024
KINDS = ("plan", "photo", "note", "other")
# Only these open inside the app; anything else downloads, so an uploaded web page can't run here.
INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "image/heic", "image/heif", "text/plain"}


# ------------------------------------------------------------ settings
def get_setting(db: Session, key: str) -> str | None:
    s = db.get(AppSetting, key)
    return s.value if s else None


def takeoff_user_id(db: Session) -> int | None:
    v = get_setting(db, "takeoff_user_id")
    return int(v) if v and v.isdigit() else None


@router.get("/settings")
def read_settings(db: Session = Depends(get_db), _: User = Depends(member)):
    uid = takeoff_user_id(db)
    return {"takeoff_user_id": uid, "takeoff_user": user_out(db.get(User, uid)) if uid else None}


@router.put("/settings")
def write_settings(body: SettingsUpdate, db: Session = Depends(get_db), me: User = Depends(admin)):
    data = body.model_dump(exclude_unset=True)
    if "takeoff_user_id" in data:
        uid = data["takeoff_user_id"]
        if uid is not None:
            active_user(db, uid, "takeoff person")
        s = db.get(AppSetting, "takeoff_user_id") or AppSetting(key="takeoff_user_id")
        s.value = str(uid) if uid is not None else None
        s.updated_at, s.updated_by = now(), me.id
        db.add(s)
    db.commit()
    return read_settings(db, me)


# --------------------------------------------------------------- files
def _file_out(f: JobFile, with_blob: set[int]) -> dict:
    d = row(f)
    d["url"] = f"/api/files/{f.id}/content?t={F.file_token(f.id)}" if f.id in with_blob else None
    d["opens_inline"] = (f.content_type or "") in INLINE_TYPES
    return d


def list_files(db: Session, job_id: int) -> list[dict]:
    rows = list(db.scalars(select(JobFile).where(JobFile.job_id == job_id, JobFile.removed.is_(False)).order_by(JobFile.created_at, JobFile.id)))
    blobs = F.has_blob(db, [f.id for f in rows])
    return [_file_out(f, blobs) for f in rows]


def _area_ok(db: Session, area_id: int | None, job_id: int) -> None:
    if area_id is None:
        return
    a = db.get(Area, area_id)
    if a is None or a.job_id != job_id:
        raise HTTPException(422, "That area isn't on this job.")


@router.get("/jobs/{job_id}/files")
def job_files(job_id: int, db: Session = Depends(get_db), _: User = Depends(member)):
    get_job(db, job_id)
    return list_files(db, job_id)


@router.post("/jobs/{job_id}/files", status_code=201)
def upload_files(
    job_id: int,
    files: list[UploadFile] = File(...),
    kind: str = Form("plan"),
    area_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    job = get_job(db, job_id)
    if kind not in KINDS:
        raise HTTPException(422, "Unknown file kind.")
    _area_ok(db, area_id, job.id)
    if not files:
        raise HTTPException(422, "Pick at least one file.")
    saved = []
    for up in files:
        data = up.file.read(UPLOAD_LIMIT + 1)
        if len(data) > UPLOAD_LIMIT:
            raise HTTPException(413, f"{up.filename} is over {UPLOAD_LIMIT // (1024 * 1024)} MB.")
        if not data:
            raise HTTPException(422, f"{up.filename or 'A file'} is empty.")
        name = F.clean_name(up.filename, "photo.jpg")
        # The file's own name decides its type; what the browser claims only fills a gap,
        # and only for types that are safe to open here.
        ctype = F.guess_type(name)
        if ctype == "application/octet-stream" and (up.content_type or "").split(";")[0] in INLINE_TYPES:
            ctype = up.content_type.split(";")[0]
        f = JobFile(job_id=job.id, area_id=area_id, kind=kind, name=name, content_type=ctype,
                    size_bytes=len(data), source="upload", status="ready", created_by=user.id)
        db.add(f)
        db.flush()
        F.save_blob(db, f, data)
        saved.append(f.id)
    db.commit()
    return list_files(db, job.id)


@router.post("/jobs/{job_id}/links", status_code=201)
def add_link(job_id: int, body: LinkAdd, db: Session = Depends(get_db), user: User = Depends(writer)):
    """A Dropbox / Google Drive / web link. Pulled in in the background."""
    job = get_job(db, job_id)
    _area_ok(db, body.area_id, job.id)
    if not body.url:
        raise HTTPException(422, "Paste a link.")
    try:
        _, what = F.direct_url(body.url)
        problem = None
    except F.NeedsDownload as exc:
        what, problem = "none", str(exc)
    label = {"dropbox_folder": "Dropbox folder", "dropbox_file": "Dropbox file", "drive_file": "Google Drive file"}.get(what, "Link")
    if what == "none" and "/folders/" in body.url:
        label = "Google Drive folder"
    f = JobFile(job_id=job.id, area_id=body.area_id, kind=body.kind, name=label, source="link", link_url=body.url,
                status="needs_download" if problem else "fetching", problem=problem, created_by=user.id)
    db.add(f)
    db.commit()
    if not problem:
        F.pull_link_in_background(f.id)
    return list_files(db, job.id)


def _file(db: Session, file_id: int) -> JobFile:
    f = db.get(JobFile, file_id)
    if f is None:
        raise HTTPException(404, "File not found.")
    return f


@router.post("/files/{file_id}/retry")
def retry_link(file_id: int, db: Session = Depends(get_db), _: User = Depends(writer)):
    f = _file(db, file_id)
    if f.source != "link" or f.status != "needs_download":
        raise HTTPException(409, "Only a link that needs a download can be tried again.")
    try:
        F.direct_url(f.link_url)
    except F.NeedsDownload as exc:
        raise HTTPException(422, str(exc)) from exc
    f.status, f.problem = "fetching", None
    db.commit()
    F.pull_link_in_background(f.id)
    return list_files(db, f.job_id)


@router.patch("/files/{file_id}")
def update_file(file_id: int, body: FileUpdate, db: Session = Depends(get_db), _: User = Depends(writer)):
    f = _file(db, file_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and not data["name"]:
        raise HTTPException(422, "A file needs a name.")
    if "kind" in data and data["kind"] is None:
        raise HTTPException(422, "Pick what kind of file it is.")
    if "removed" in data and data["removed"] is None:
        data.pop("removed")
    if "area_id" in data:
        _area_ok(db, data["area_id"], f.job_id)
    for k, v in data.items():
        setattr(f, k, v)
    if data.get("removed"):
        # Removing a folder link removes what came from it too. Nothing is deleted; it's hidden.
        for child in db.scalars(select(JobFile).where(JobFile.link_id == f.id)):
            child.removed = True
    db.commit()
    return list_files(db, f.job_id)


@router.get("/files/{file_id}/content", include_in_schema=False)
def file_content(file_id: int, t: str, db: Session = Depends(get_db)):
    """Opened straight from the phone (a link, not an API call), so it is guarded by a
    short-lived signed token instead of the sign-in header."""
    F.check_file_token(file_id, t)
    f = _file(db, file_id)
    data = F.read_blob(db, file_id)
    if data is None or f.removed:
        raise HTTPException(404, "That file isn't here.")
    ctype = f.content_type or "application/octet-stream"
    inline = ctype in INLINE_TYPES
    disposition = f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(f.name)}"
    return Response(
        content=data,
        media_type=ctype,
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "private, max-age=3600",
        },
    )


# ------------------------------------------------------------- footage
@router.put("/areas/{area_id}/footage")
def set_footage(area_id: int, body: FootageSet, db: Session = Depends(get_db), user: User = Depends(writer)):
    """The area's size: only a starting number. It fills in chosen tiles that have no
    number yet, and new tiles as they're chosen. The number on the tile is the boss."""
    from ..services.availability import fill_from_area

    area = db.get(Area, area_id)
    if area is None:
        raise HTTPException(404, "Area not found.")
    if body.footage is None:
        area.footage = area.footage_source = area.footage_by = area.footage_confidence = None
        area.footage_set_at = None
    else:
        area.footage, area.footage_source, area.footage_confidence = body.footage, body.source, body.confidence
        area.footage_by, area.footage_set_at = body.by or user.name, now()
        for tag in db.scalars(select(CandidateTag).where(CandidateTag.area_id == area.id, CandidateTag.status == "chosen")):
            fill_from_area(db, tag)
    db.commit()
    return row(area)


# ------------------------------------------------------------- takeoff
def has_plan(db: Session, job_id: int) -> bool:
    n = db.scalar(
        select(func.count()).select_from(JobFile).where(
            JobFile.job_id == job_id, JobFile.kind == "plan", JobFile.removed.is_(False), JobFile.status == "ready",
            (JobFile.source != "link") | JobFile.size_bytes.is_not(None),
        )
    )
    return bool(n)


@router.post("/jobs/{job_id}/takeoff", status_code=201)
def request_takeoff(job_id: int, body: TakeoffRequest, db: Session = Depends(get_db), user: User = Depends(writer)):
    """One takeoff per job, to the default takeoff person unless someone else is picked."""
    job = get_job(db, job_id)
    if job.status != "active":
        raise HTTPException(409, "The job isn't active.")
    if not has_plan(db, job.id):
        raise HTTPException(422, "Put the plans on the job first — upload them or paste the link.")
    if db.scalar(select(Task.id).where(Task.job_id == job.id, Task.kind == "takeoff", Task.status.in_(TASK_OPEN))):
        raise HTTPException(409, "This job already has an open takeoff.")
    assignee = body.assignee_id or takeoff_user_id(db)
    if assignee is None:
        raise HTTPException(422, "Pick who does the takeoff — or set a default takeoff person on the Team screen.")
    step = NextStep(
        title="Takeoff",
        assignee_id=assignee,
        due_date=body.due_date or (today() + timedelta(days=2)),
        severity="notify",
        notes=body.notes,
    )
    task = create_task(db, job, step, user)
    task.kind = "takeoff"
    db.commit()
    return row(task)
