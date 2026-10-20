"""Plans and photos on a job: storing uploads, pulling in Dropbox / Google Drive
links, and short-lived links for opening a file on a phone."""

import io
import logging
import mimetypes
import re
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit

import jwt
from fastapi import HTTPException
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import FileBlob, JobFile

log = logging.getLogger("pipeline.files")

MAX_FILE = 50 * 1024 * 1024  # one file
MAX_LINK = 250 * 1024 * 1024  # everything from one link
MAX_FILES_PER_LINK = 200
TOKEN_HOURS = 2
TIMEOUT = 60


class NeedsDownload(Exception):
    """The link can't be pulled in from here. The message says why, for a person."""


# --------------------------------------------------------------- storing
def save_blob(db: Session, file: JobFile, data: bytes) -> None:
    db.execute(insert(FileBlob.__table__).values(file_id=file.id, data=data))


def read_blob(db: Session, file_id: int) -> bytes | None:
    return db.scalar(select(FileBlob.__table__.c.data).where(FileBlob.__table__.c.file_id == file_id))


def has_blob(db: Session, file_ids: list[int]) -> set[int]:
    if not file_ids:
        return set()
    t = FileBlob.__table__
    return set(db.scalars(select(t.c.file_id).where(t.c.file_id.in_(file_ids))))


def guess_type(name: str, given: str | None = None) -> str:
    if given and given not in ("application/octet-stream", "binary/octet-stream"):
        return given.split(";")[0].strip()
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def clean_name(name: str | None, fallback: str = "file") -> str:
    name = (name or "").replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[\x00-\x1f]", "", name)
    return (name or fallback)[:200]


# ------------------------------------------------------- opening a file
def file_token(file_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"f": file_id, "k": "file", "exp": exp}, settings.secret_key, algorithm="HS256")


def check_file_token(file_id: int, token: str) -> None:
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(403, "This file link has expired. Go back and tap the file again.") from exc
    if claims.get("k") != "file" or claims.get("f") != file_id:
        raise HTTPException(403, "This file link isn't valid.")


# ------------------------------------------------------- reading links
def direct_url(url: str) -> tuple[str, str]:
    """Turns a share link into one that downloads. Returns (url, what) where what is
    'dropbox_file', 'dropbox_folder', 'drive_file', 'web'. Raises NeedsDownload for
    links that can never be pulled in from a server."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise NeedsDownload("That isn't a web link.")
    host = parts.netloc.lower()
    path = parts.path

    if host.endswith("dropbox.com"):
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        query["dl"] = "1"
        what = "dropbox_folder" if path.startswith(("/sh/", "/scl/fo/")) else "dropbox_file"
        return urlunsplit(("https", "www.dropbox.com", path, urlencode(query), "")), what

    if host in ("drive.google.com", "docs.google.com"):
        if "/folders/" in path:
            raise NeedsDownload(
                "Google Drive folders can't be pulled in automatically. Open the folder, "
                "download it, and upload the files here."
            )
        m = re.search(r"/d/([A-Za-z0-9_-]{10,})", path)
        file_id = m.group(1) if m else (parse_qs(parts.query).get("id") or [None])[0]
        if not file_id:
            raise NeedsDownload("That Google link doesn't point at a file.")
        if host == "docs.google.com" and "/document/" in path:
            return f"https://docs.google.com/document/d/{file_id}/export?format=pdf", "drive_file"
        if host == "docs.google.com" and "/spreadsheets/" in path:
            return f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=pdf", "drive_file"
        return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t", "drive_file"

    return url.strip(), "web"


def _filename(resp, url: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=(?:UTF-8|utf-8)''([^;]+)", cd)
    if m:
        return clean_name(unquote(m.group(1).strip('"')))
    m = re.search(r'filename="?([^";]+)"?', cd)
    if m:
        return clean_name(m.group(1))
    return clean_name(unquote(urlsplit(url).path.rsplit("/", 1)[-1]), "download")


def _read_capped(resp, cap: int) -> bytes:
    buf = io.BytesIO()
    for chunk in resp.iter_content(chunk_size=256 * 1024):
        buf.write(chunk)
        if buf.tell() > cap:
            raise NeedsDownload(f"The file is bigger than {cap // (1024 * 1024)} MB. Download it and upload a smaller copy.")
    return buf.getvalue()


def fetch(url: str, http=None) -> list[tuple[str, str, bytes]]:
    """Downloads what a link points at. Returns [(name, content_type, bytes)].
    A Dropbox folder comes back as a zip, which is unpacked into its files."""
    target, what = direct_url(url)
    if http is None:
        import requests

        http = requests.Session()
    try:
        resp = http.get(target, stream=True, timeout=TIMEOUT, allow_redirects=True,
                        headers={"User-Agent": "Mozilla/5.0 (pipeline file fetch)"})
    except Exception as exc:
        raise NeedsDownload(f"Couldn't reach the link ({type(exc).__name__}). Download it and upload the file here.") from exc
    if resp.status_code in (401, 403, 404):
        raise NeedsDownload("The link is private or gone. Ask for a shared link, or download it and upload the file here.")
    if resp.status_code != 200:
        raise NeedsDownload(f"The link answered {resp.status_code}. Download it and upload the file here.")
    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype in ("text/html", "application/xhtml+xml"):
        raise NeedsDownload(
            "The link opened a web page, not a file — it's probably private or needs a sign-in. "
            "Download it and upload the file here."
        )
    name = _filename(resp, target)
    is_zip = ctype in ("application/zip", "application/x-zip-compressed") or name.lower().endswith(".zip")
    data = _read_capped(resp, MAX_LINK if is_zip else MAX_FILE)

    if is_zip and what == "dropbox_folder":
        return _unzip(data)
    return [(name, guess_type(name, ctype), data)]


def _unzip(data: bytes) -> list[tuple[str, str, bytes]]:
    out = []
    total = 0
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise NeedsDownload("The folder download came back damaged. Download it and upload the files here.") from exc
    for info in zf.infolist():
        if info.is_dir() or "__MACOSX" in info.filename or info.filename.split("/")[-1].startswith("."):
            continue
        if len(out) >= MAX_FILES_PER_LINK:
            break
        if info.file_size > MAX_FILE:
            continue
        total += info.file_size
        if total > MAX_LINK:
            break
        name = clean_name(info.filename)
        out.append((name, guess_type(name), zf.read(info)))
    if not out:
        raise NeedsDownload("The folder is empty, or every file in it is too big.")
    return out


# ------------------------------------------------ background link pull
def pull_link(file_id: int, http=None) -> None:
    """Runs off the request. Fills a link row with its file, or with the files of a
    folder, or marks it 'needs a download' with the reason."""
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        link = db.get(JobFile, file_id)
        if link is None or link.source != "link":
            return
        db.info["user_id"] = link.created_by  # the history credits whoever pasted the link
        try:
            got = fetch(link.link_url, http)
        except NeedsDownload as exc:
            link.status, link.problem = "needs_download", str(exc)
            db.commit()
            return
        _, what = direct_url(link.link_url)
        if what == "dropbox_folder":
            for name, ctype, data in got:
                child = JobFile(job_id=link.job_id, area_id=link.area_id, kind=link.kind, name=name,
                                content_type=ctype, size_bytes=len(data), source="from_link", link_id=link.id,
                                status="ready", created_by=link.created_by)
                db.add(child)
                db.flush()
                save_blob(db, child, data)
            link.name = f"{link.name} ({len(got)} file{'s' if len(got) != 1 else ''})"
            link.status, link.problem = "ready", None
        else:
            name, ctype, data = got[0]
            link.name, link.content_type, link.size_bytes = name, ctype, len(data)
            save_blob(db, link, data)
            link.status, link.problem = "ready", None
        db.commit()
    except Exception as exc:  # never leave a link spinning forever
        log.exception("link pull failed")
        db.rollback()
        link = db.get(JobFile, file_id)
        if link is not None:
            link.status, link.problem = "needs_download", f"Something went wrong pulling it in ({type(exc).__name__}). Download it and upload the file here."
            db.commit()
    finally:
        db.close()


def pull_link_in_background(file_id: int) -> None:
    threading.Thread(target=pull_link, args=(file_id,), name=f"pull-link-{file_id}", daemon=True).start()
