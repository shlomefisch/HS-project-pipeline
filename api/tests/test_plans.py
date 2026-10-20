"""Order assembly, first part: plans, footage, takeoff."""

import io
import zipfile

from conftest import new_job, step
from app.services import files as F


# ---------------------------------------------------------- link rules (no server)
def test_share_links_become_download_links():
    url, what = F.direct_url("https://www.dropbox.com/scl/fi/abc/plan.pdf?rlkey=x&dl=0")
    assert what == "dropbox_file" and "dl=1" in url and "rlkey=x" in url
    assert F.direct_url("https://www.dropbox.com/scl/fo/abc/xyz?rlkey=y&dl=0")[1] == "dropbox_folder"
    url, what = F.direct_url("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing")
    assert what == "drive_file" and "id=1AbCdEfGhIjKlMnOp" in url
    assert "export?format=pdf" in F.direct_url("https://docs.google.com/document/d/1AbCdEfGhIjKlMnOp/edit")[0]


def test_drive_folders_and_junk_need_a_download():
    for bad in ("https://drive.google.com/drive/folders/1AbCdEfGhIjKl", "ftp://x/y", "not a link"):
        try:
            F.direct_url(bad)
            raise AssertionError(bad)
        except F.NeedsDownload:
            pass


class Resp:
    def __init__(self, status=200, ctype="application/pdf", body=b"%PDF-1.4 x", cd=None):
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        if cd:
            self.headers["Content-Disposition"] = cd
        self.body = body

    def iter_content(self, chunk_size):
        yield self.body


class Http:
    def __init__(self, resp):
        self.resp = resp
        self.urls = []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.resp


def test_fetch_a_file_and_a_folder():
    got = F.fetch("https://www.dropbox.com/scl/fi/a/k.pdf?dl=0", Http(Resp(cd='attachment; filename="Kitchen plan.pdf"')))
    assert got == [("Kitchen plan.pdf", "application/pdf", b"%PDF-1.4 x")]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("plans/first.pdf", b"one")
        z.writestr("plans/second.jpg", b"two")
        z.writestr("__MACOSX/._first.pdf", b"junk")
    got = F.fetch("https://www.dropbox.com/scl/fo/a/b?dl=0", Http(Resp(ctype="application/zip", body=buf.getvalue(), cd='attachment; filename="plans.zip"')))
    assert [g[0] for g in got] == ["first.pdf", "second.jpg"]


def test_a_private_link_says_so():
    for resp in (Resp(ctype="text/html"), Resp(status=403)):
        try:
            F.fetch("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view", Http(resp))
            raise AssertionError("should need a download")
        except F.NeedsDownload as exc:
            assert "upload" in str(exc)


# ------------------------------------------------------------- through the API
def _upload(actor, job_id, name="plan.pdf", data=b"%PDF-1.4 plan", kind="plan"):
    return actor.client.post(
        f"/api/jobs/{job_id}/files",
        files={"files": (name, data, "application/pdf")},
        data={"kind": kind},
        headers=actor._h(),
    )


def test_upload_then_open_with_a_short_lived_link(client, jay):
    job = new_job(jay)
    r = _upload(jay, job["id"])
    assert r.status_code == 201, r.text
    f = r.json()[0]
    assert f["name"] == "plan.pdf" and f["size_bytes"] == 13 and f["opens_inline"]
    got = client.get(f["url"])  # no sign-in header: the token in the link is enough
    assert got.status_code == 200 and got.content == b"%PDF-1.4 plan"
    assert got.headers["content-security-policy"] == "sandbox"
    assert client.get(f"/api/files/{f['id']}/content?t=bad").status_code == 403
    story = [e["summary"] for e in jay.get(f"/api/jobs/{job['id']}/timeline").json()]
    assert "Plan added: plan.pdf" in story


def test_web_pages_download_instead_of_opening(client, jay):
    job = new_job(jay)
    f = _upload(jay, job["id"], name="evil.html", data=b"<script>x</script>").json()[0]
    got = client.get(f["url"])
    assert got.headers["content-disposition"].startswith("attachment")


def test_a_private_link_is_marked_needs_download(client, jay):
    job = new_job(jay)
    r = jay.post(f"/api/jobs/{job['id']}/links", json={"url": "https://drive.google.com/drive/folders/1AbCdEfGhIjKl"})
    f = r.json()[0]
    assert f["status"] == "needs_download" and "folder" in f["problem"]


def test_pulling_a_link_fills_it(client, jay, monkeypatch):
    job = new_job(jay)
    monkeypatch.setattr(F, "pull_link_in_background", lambda file_id: None)
    f = jay.post(f"/api/jobs/{job['id']}/links", json={"url": "https://www.dropbox.com/scl/fi/a/k.pdf?dl=0"}).json()[0]
    assert f["status"] == "fetching"
    F.pull_link(f["id"], Http(Resp(cd='attachment; filename="Kitchen.pdf"')))
    f = jay.get(f"/api/jobs/{job['id']}/files").json()[0]
    assert f["status"] == "ready" and f["name"] == "Kitchen.pdf" and f["url"]


def test_footage_needs_its_source_and_lands_in_the_story(client, jay):
    job = new_job(jay)
    area = jay.post(f"/api/jobs/{job['id']}/areas", json={"name": "Kitchen"}).json()
    assert jay.put(f"/api/areas/{area['id']}/footage", json={"footage": 420}).status_code == 422
    assert jay.put(f"/api/areas/{area['id']}/footage", json={"footage": 420, "source": "designer", "confidence": "approximate"}).status_code == 422
    r = jay.put(f"/api/areas/{area['id']}/footage", json={"footage": 420, "source": "designer", "by": "Rifky", "confidence": "approximate"})
    assert r.status_code == 200 and r.json()["footage"] == 420.0
    story = [e["summary"] for e in jay.get(f"/api/jobs/{job['id']}/timeline").json()]
    assert "Kitchen footage: 420 sf, approximate — from designer (Rifky)" in story
    assert jay.put(f"/api/areas/{area['id']}/footage", json={"footage": None}).json()["footage"] is None


def test_takeoff_needs_plans_a_person_and_is_one_per_job(client, boss, jay, office):
    job = new_job(jay)
    assert jay.post(f"/api/jobs/{job['id']}/takeoff", json={}).status_code == 422  # no plans
    _upload(jay, job["id"])
    assert jay.post(f"/api/jobs/{job['id']}/takeoff", json={}).status_code == 422  # nobody set
    assert boss.put("/api/settings", json={"takeoff_user_id": office.id}).json()["takeoff_user_id"] == office.id
    r = jay.post(f"/api/jobs/{job['id']}/takeoff", json={})
    assert r.status_code == 201 and r.json()["assignee_id"] == office.id and r.json()["kind"] == "takeoff"
    assert jay.post(f"/api/jobs/{job['id']}/takeoff", json={}).status_code == 409
    assert jay.get(f"/api/jobs/{job['id']}").json()["open_takeoff_id"] == r.json()["id"]


def test_takeoff_is_not_done_until_every_area_has_footage(client, boss, jay, office):
    job = new_job(jay)
    _upload(jay, job["id"])
    kitchen = jay.post(f"/api/jobs/{job['id']}/areas", json={"name": "Kitchen"}).json()
    jay.post(f"/api/jobs/{job['id']}/areas", json={"name": "Mudroom"})
    t = jay.post(f"/api/jobs/{job['id']}/takeoff", json={"assignee_id": office.id}).json()
    office.put(f"/api/areas/{kitchen['id']}/footage", json={"footage": 300, "source": "takeoff", "confidence": "confirmed"})
    r = office.post(f"/api/tasks/{t['id']}/complete", json={"outcome": "done", "next_step": step(jay.id, "Price it")})
    assert r.status_code == 422 and "Mudroom" in r.json()["detail"]
    mud = [a for a in jay.get(f"/api/jobs/{job['id']}").json()["areas"] if a["name"] == "Mudroom"][0]
    office.put(f"/api/areas/{mud['id']}/footage", json={"footage": 80, "source": "takeoff", "confidence": "confirmed"})
    r = office.post(f"/api/tasks/{t['id']}/complete", json={"outcome": "done", "next_step": step(jay.id, "Price it")})
    assert r.status_code == 200
    assert mud["name"] == "Mudroom"


def test_only_admins_change_settings(client, jay):
    assert jay.put("/api/settings", json={"takeoff_user_id": None}).status_code == 403
