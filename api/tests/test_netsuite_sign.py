"""Signing checked against the worked example in the OAuth 1.0 spec, with no server."""

from app.netsuite import Keys, oauth_header


def _sig(header: str) -> str:
    from urllib.parse import unquote

    part = [p for p in header.split(",") if p.startswith("oauth_signature=")][0]
    return unquote(part.split("=", 1)[1].strip('"'))


def test_matches_the_spec_example():
    keys = Keys("x", "dpf43f3p2l4k3l03", "kd94hf93k423kf44", "nnch734d00sl2jdk", "pfkkdhi9sl3r4s00")
    h = oauth_header(
        "GET",
        "http://photos.example.net/photos?file=vacation.jpg&size=original",
        keys,
        nonce="kllo9940pd9333jh",
        timestamp="1191242096",
        algorithm="HMAC-SHA1",
    )
    assert _sig(h) == "tR3+Ty81lMeYAr/Fid0kMTYa/WM="


def test_realm_and_host_from_account():
    k = Keys("5032967", "a", "b", "c", "d")
    assert k.realm == "5032967" and k.host == "5032967.suitetalk.api.netsuite.com"
    sb = Keys("5032967_SB1", "a", "b", "c", "d")
    assert sb.realm == "5032967_SB1" and sb.host == "5032967-sb1.suitetalk.api.netsuite.com"


def test_header_shape_for_netsuite():
    h = oauth_header("POST", "https://5032967.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql?limit=1000&offset=0",
                     Keys("5032967", "ck", "cs", "ti", "ts"))
    assert h.startswith('OAuth realm="5032967",') and 'oauth_signature_method="HMAC-SHA256"' in h
