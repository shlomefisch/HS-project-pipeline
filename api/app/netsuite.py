"""NetSuite, read-only: SuiteQL queries signed with token-based auth.

Standard library only for the signing, so it can be checked without a server.
Nothing in this module writes to NetSuite.
"""

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

PAGE_SIZE = 1000  # SuiteQL's maximum page
TIMEOUT = 60


class NetSuiteError(Exception):
    """A NetSuite call failed. The message is written for a person to read."""


@dataclass(frozen=True)
class Keys:
    account: str
    consumer_key: str
    consumer_secret: str
    token_id: str
    token_secret: str

    @property
    def realm(self) -> str:
        # "5032967" stays as is; a sandbox "5032967-sb1" becomes "5032967_SB1".
        return self.account.upper().replace("-", "_")

    @property
    def host(self) -> str:
        return f"{self.account.lower().replace('_', '-')}.suitetalk.api.netsuite.com"


def _enc(value: str) -> str:
    return quote(str(value), safe="~")


def oauth_header(
    method: str,
    url: str,
    keys: Keys,
    *,
    nonce: str | None = None,
    timestamp: str | None = None,
    algorithm: str = "HMAC-SHA256",
    realm: str | None = None,
) -> str:
    """OAuth 1.0a Authorization header (RFC 5849). Query-string parameters are
    part of the signature, so the URL must be the exact one being requested."""
    nonce = nonce or secrets.token_hex(16)
    timestamp = timestamp or str(int(time.time()))
    oauth = {
        "oauth_consumer_key": keys.consumer_key,
        "oauth_token": keys.token_id,
        "oauth_signature_method": algorithm,
        "oauth_timestamp": timestamp,
        "oauth_nonce": nonce,
        "oauth_version": "1.0",
    }
    parts = urlsplit(url)
    base_url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))
    params = parse_qsl(parts.query, keep_blank_values=True) + list(oauth.items())
    normalized = "&".join(f"{k}={v}" for k, v in sorted((_enc(k), _enc(v)) for k, v in params))
    base = "&".join((method.upper(), _enc(base_url), _enc(normalized)))
    key = f"{_enc(keys.consumer_secret)}&{_enc(keys.token_secret)}".encode()
    digest = hashlib.sha256 if algorithm == "HMAC-SHA256" else hashlib.sha1
    signature = base64.b64encode(hmac.new(key, base.encode(), digest).digest()).decode()
    fields = {"realm": keys.realm if realm is None else realm, **oauth, "oauth_signature": signature}
    return "OAuth " + ",".join(f'{k}="{_enc(v)}"' for k, v in fields.items())


def _problem(resp) -> str:
    try:
        details = resp.json().get("o:errorDetails") or []
        text = "; ".join(d.get("detail", "") for d in details if d.get("detail"))
    except ValueError:
        text = ""
    text = text or (resp.text or "")[:300]
    if resp.status_code == 401:
        return (
            "NetSuite refused the keys. Check the five NS_ variables on Railway, and that the "
            f"token's role has the REST Web Services and SuiteAnalytics Workbook permissions. ({text})"
        )
    if resp.status_code == 403:
        return f"NetSuite says the role isn't allowed to do this. ({text})"
    if resp.status_code == 429:
        return "NetSuite is busy (too many calls at once). The next run will try again."
    return f"NetSuite answered {resp.status_code}: {text}"


class SuiteQL:
    def __init__(self, keys: Keys, http=None):
        if http is None:
            import requests

            http = requests.Session()
        self.keys = keys
        self.http = http

    def page(self, sql: str, limit: int = PAGE_SIZE, offset: int = 0) -> tuple[list[dict], bool]:
        url = f"https://{self.keys.host}/services/rest/query/v1/suiteql?limit={limit}&offset={offset}"
        headers = {
            "Authorization": oauth_header("POST", url, self.keys),
            "Content-Type": "application/json",
            "Prefer": "transient",
        }
        try:
            resp = self.http.post(url, json={"q": sql}, headers=headers, timeout=TIMEOUT)
        except Exception as exc:  # network trouble of any kind
            raise NetSuiteError(f"Couldn't reach NetSuite: {exc}") from exc
        if resp.status_code != 200:
            raise NetSuiteError(_problem(resp))
        body = resp.json()
        rows = [{k.lower(): v for k, v in r.items() if k != "links"} for r in body.get("items", [])]
        return rows, bool(body.get("hasMore"))

    def by_id(self, sql_for_after: Callable[[int], str], id_field: str = "id") -> Iterator[list[dict]]:
        """Pages through a query ordered by id, restarting after the last id seen.
        Unlike offsets, this can't skip or repeat rows if NetSuite changes mid-run."""
        last = 0
        while True:
            rows, more = self.page(sql_for_after(last))
            if not rows:
                return
            yield rows
            if not more:
                return
            last = int(rows[-1][id_field])
