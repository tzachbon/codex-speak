"""Stable GitHub release updates, using the existing per-user installer."""
import hashlib
import json
from importlib.metadata import version
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = "https://api.github.com/repos/tzachbon/select-to-tts/releases/latest"
ASSET = "SelectToTTS-Setup.exe"
MAX_INSTALLER = 200 * 1024 * 1024
CACHE = Path(os.environ["LOCALAPPDATA"]) / "select-to-tts" / "updates"


def _trusted(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname in {
        "api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
        and not parsed.username and not parsed.password and parsed.port in (None, 443))


class _HTTPSRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _trusted(newurl):
            raise ValueError("Unexpected installer redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


urlopen = build_opener(_HTTPSRedirect()).open


def current_version():
    return version("select-to-tts")


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}", value):
        raise ValueError("Expected a stable major.minor.patch version")
    return tuple(map(int, value.split(".")))


def check():
    request = Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": "SelectToTTS"})
    with urlopen(request, timeout=15) as reply:
        if reply.geturl() != API:
            raise ValueError("Unexpected release metadata location")
        body = reply.read(65537)
    if len(body) > 65536:
        raise ValueError("Release metadata is too large")
    data = json.loads(body)
    if not isinstance(data, dict) or data.get("draft") is not False or data.get("prerelease") is not False:
        raise ValueError("Expected a published stable release")
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise ValueError("Invalid release tag")
    newer = _version(tag[1:]) > _version(current_version())
    if not newer:
        return None
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Release has no installer")
    matches = [a for a in assets if isinstance(a, dict) and a.get("name") == ASSET]
    if len(matches) != 1:
        raise ValueError("Release must contain one installer")
    asset = matches[0]
    expected = f"https://github.com/tzachbon/select-to-tts/releases/download/{tag}/{ASSET}"
    size, digest = asset.get("size"), asset.get("digest")
    if (asset.get("browser_download_url") != expected or asset.get("state") != "uploaded"
            or type(size) is not int or not 0 < size <= MAX_INSTALLER
            or not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
        raise ValueError("Release installer URL, size or SHA-256 digest is invalid")
    return {**asset, "version": tag[1:]}


def download(asset):
    CACHE.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="update-", dir=CACHE))
    path = directory / ASSET
    try:
        digest, size = hashlib.sha256(), 0
        deadline = time.monotonic() + 300
        request = Request(asset["browser_download_url"], headers={"User-Agent": "SelectToTTS"})
        with urlopen(request, timeout=15) as reply, path.open("xb") as output:
            if not _trusted(reply.geturl()):
                raise ValueError("Unexpected installer download location")
            while chunk := reply.read(1024 * 1024):
                size += len(chunk)
                if size > asset["size"] or time.monotonic() > deadline:
                    raise ValueError("Installer download exceeded its size or time limit")
                output.write(chunk)
                digest.update(chunk)
        if size != asset["size"] or "sha256:" + digest.hexdigest() != asset["digest"]:
            raise ValueError("Installer verification failed. Try again later.")
        return path
    except BaseException:
        shutil.rmtree(directory)
        raise


def install(path):
    if not getattr(sys, "frozen", False):
        raise ValueError("Source runs cannot install updates")
    if path.name != ASSET or not path.resolve().is_relative_to(CACHE.resolve()) or not path.is_file():
        raise ValueError("Invalid installer path")
    subprocess.Popen([str(path), "/SP-", "/SILENT", "/NORESTART",
                      f"/DIR={Path(sys.executable).parent}", f"/LOG={path.parent / 'setup.log'}"], shell=False)
