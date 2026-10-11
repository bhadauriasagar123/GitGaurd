"""Static UI guards: the page must stay consistent with its script and compatible with the production CSP
(script-src 'self', style-src 'self': no inline <script>, no style="" attributes, no inline event handlers)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import VIEWER

STATIC = Path(__file__).resolve().parent.parent / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf8")
JS = (STATIC / "app.js").read_text(encoding="utf8")
CSS = (STATIC / "style.css").read_text(encoding="utf8")


def test_every_selector_used_by_script_exists_in_html():
    ids_html = set(re.findall(r'id="([\w-]+)"', HTML))
    # ids created dynamically by the script itself
    dynamic = {"upTrace"}
    for m in set(re.findall(r'\$\("#([\w-]+)"\)', JS)):
        assert m in ids_html or m in dynamic, f"app.js references #{m} which is not in index.html"
    for m in set(re.findall(r'onClick\("#([\w-]+)"', JS)):
        assert m in ids_html, m


def test_every_tab_has_a_panel_and_a_loader():
    tabs = re.findall(r'data-tab="(\w+)"', HTML)
    panels = set(re.findall(r'id="tab-(\w+)"', HTML))
    assert set(tabs) == panels and len(tabs) == len(set(tabs))
    loaders = set(re.findall(r"const LOAD = \{([^}]*)\}", JS)[0].replace(" ", "").split(","))
    for t in tabs:
        assert t == "whatif" or t == "assistant" or any(x.startswith(t) for x in loaders), f"tab {t} has no loader"


def test_html_is_csp_compatible():
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", HTML), "inline <script> would be blocked by CSP"
    assert not re.search(r'\sstyle="', HTML), "inline style attribute would be blocked by CSP"
    assert not re.search(r'\son\w+="', HTML), "inline event handler would be blocked by CSP"
    assert not re.search(r"\.(?:innerHTML|outerHTML)\b|insertAdjacentHTML|document\.write", JS), "UI must render untrusted data with textContent only"
    assert "eval(" not in JS and "new Function" not in JS
    assert "@import" not in CSS and "url(http" not in CSS


def test_script_never_sets_inline_style_attribute():
    assert 'setAttribute("style"' not in JS and "setAttribute('style'" not in JS


def test_upload_picker_uses_native_label_activation():
    assert re.search(r'<label[^>]*id="upDrop"[^>]*for="upPick"', HTML)
    assert 'drop.addEventListener("click"' not in JS


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_app_js_parses():
    r = subprocess.run(["node", "--check", str(STATIC / "app.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


async def test_static_assets_served_with_security_headers(client):
    for path, ctype in (("/", "text/html"), ("/static/app.js", "javascript"), ("/static/style.css", "text/css")):
        r = await client.get(path)
        assert r.status_code == 200 and ctype in r.headers["content-type"], path
        assert "default-src 'self'" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"
    cfg = (await client.get("/config.json")).json()
    assert "demoKey" in cfg


async def test_ui_upload_flow_contract(client):
    """The exact request the Upload tab sends (text body + regulation meta + Idempotency-Key) is accepted; a binary DOCX works too."""
    import base64
    from tests.conftest import ANALYST
    from tests.helpers import make_docx
    body = {"kind": "regulation", "title": "UI upload test", "sourceType": "text", "content": "1.1 Banks shall report fraud within 4 hours.",
            "regulation": {"code": "UI-1", "version": "1.0", "jurisdiction": "IN"}}
    r = await client.post("/api/v1/documents", headers={**ANALYST, "Idempotency-Key": "ui-up-contract-0001"}, json=body)
    assert r.status_code == 201 and r.json()["firewall"]["verdict"] == "allow"
    docx = {"kind": "policy", "title": "UI docx upload", "sourceType": "docx", "contentBase64": base64.b64encode(make_docx("2.1 Staff must complete training annually.")).decode(),
            "regulation": {"code": "UI-POL", "version": "1.0"}}
    assert (await client.post("/api/v1/documents", headers=ANALYST, json=docx)).status_code == 201
