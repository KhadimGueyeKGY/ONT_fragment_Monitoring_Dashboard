from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

REPO = "KhadimGueyeKGY/ONT_fragment_Monitoring_Dashboard"
BRANCH = "main"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION"
NOTES_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/CHANGELOG.md"
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
REPO_URL = f"https://github.com/{REPO}"
KEEP = {"Reference", "results", ".git"}
KEEP_FILES = {"panels/custom.tsv"}


def parse_version(text: str) -> tuple:
    parts = []
    for p in text.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _get(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ont-fragment-dashboard", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


class Updater:
    def __init__(self, root: Path, log):
        self.root = root
        self.log = log
        self.current = (root / "VERSION").read_text().strip() if (root / "VERSION").exists() else "0.0.0"
        self.lock = threading.Lock()
        self.info = {"current": self.current, "latest": None, "available": False, "notes": "",
                     "checked": False, "error": None, "updating": False, "done": False, "repo": REPO_URL}

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.info)

    def check(self) -> None:
        try:
            latest = _get(VERSION_URL).decode().strip()
            notes = ""
            try:
                text = _get(NOTES_URL).decode()
                section = text.split("\n## ")[1] if "\n## " in text else ""
                notes = "\n".join(section.splitlines()[1:]).strip()[:1500]
            except Exception:
                pass
            with self.lock:
                self.info.update(latest=latest, notes=notes, checked=True, error=None,
                                 available=parse_version(latest) > parse_version(self.current))
            if self.info["available"]:
                self.log(f"A new version is available: {latest} (installed {self.current}).")
        except Exception as exc:
            with self.lock:
                self.info.update(checked=True, error=f"Could not check for updates: {exc}")

    def apply(self) -> None:
        with self.lock:
            self.info.update(updating=True, error=None)
        try:
            if (self.root / ".git").exists():
                # A git checkout is only updated by git, so local changes are never overwritten.
                if not shutil.which("git"):
                    raise RuntimeError("this folder is a git copy but git is not installed. Run 'git pull' in it.")
                try:
                    self._git_update()
                except Exception as exc:
                    raise RuntimeError(f"git could not update this folder ({exc}). Run 'git pull' in it.")
            else:
                self._zip_update()
            with self.lock:
                self.info.update(updating=False, done=True, available=False)
            self.log("Update installed. The dashboard restarts.")
        except Exception as exc:
            with self.lock:
                self.info.update(updating=False, error=f"Update failed: {exc}")
            self.log(f"Update failed: {exc}")
            raise

    def _git_update(self) -> None:
        # A folder cloned by Git for Windows has CRLF line endings. Git inside WSL must read it the
        # same way, otherwise every text file looks modified and the update is refused.
        extra = ["-c", "core.autocrlf=true"] if str(self.root).startswith("/mnt/") else []

        def git(*args):
            out = subprocess.run(["git", *extra, "-C", str(self.root), *args], capture_output=True, text=True)
            if out.returncode != 0:
                raise RuntimeError(out.stderr.strip()[-300:] or "git error")
            return out.stdout
        git("fetch", "origin", BRANCH)
        git("merge", "--ff-only", f"origin/{BRANCH}")

    def _zip_update(self) -> None:
        data = _get(ZIP_URL, timeout=120)
        with tempfile.TemporaryDirectory() as tmp:
            zipfile.ZipFile(io.BytesIO(data)).extractall(tmp)
            src = next(Path(tmp).iterdir())
            for item in src.rglob("*"):
                rel = item.relative_to(src)
                if rel.parts[0] in KEEP or rel.as_posix() in KEEP_FILES:
                    continue
                dest = self.root / rel
                if item.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)
