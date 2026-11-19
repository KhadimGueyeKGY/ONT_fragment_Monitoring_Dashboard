from __future__ import annotations

import argparse
import json
import mimetypes
import os
import socket
import sys
import threading
import time
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
sys.path.insert(0, str(APP_DIR))

import platform_utils as pu  # noqa: E402
from catalog import Catalog, parse_bed_or_tsv  # noqa: E402
from monitor import DEFAULT_SETTINGS, Monitor  # noqa: E402
from reference import ReferenceSetup  # noqa: E402
from updater import Updater  # noqa: E402

RESTART_CODE = 75
WEB_DIR = APP_DIR / "web"
STATE_DIR = Path.home() / ".ont_fragment_dashboard"
INSTANCE_FILE = STATE_DIR / "instance.json"
PREFS_FILE = STATE_DIR / "preferences.json"

LOG = deque(maxlen=600)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    LOG.append(line)
    print(line, flush=True)


def load_prefs() -> dict:
    try:
        return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_prefs(update: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    prefs = {**load_prefs(), **update}
    PREFS_FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")


def plotly_js() -> Path | None:
    try:
        import plotly
        p = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
        return p if p.exists() else None
    except Exception:
        return None


class App:
    def __init__(self):
        self.reference = ReferenceSetup(ROOT / "Reference" / "Pf3D7_v2.fasta", log)
        self.catalog = Catalog(ROOT / "panels" / "fragments.tsv", ROOT / "panels" / "custom.tsv")
        self.monitor = Monitor(self.reference.fasta, ROOT / "results", self.catalog, log)
        self.updater = Updater(ROOT, log)
        self.exit_code = 0
        self.server: ThreadingHTTPServer | None = None
        threading.Thread(target=self.reference.run, daemon=True).start()
        threading.Thread(target=self.updater.check, daemon=True).start()
        last = load_prefs().get("last_run_dir")
        if last and Path(last).exists():
            self.monitor.load_previous(Path(last))

    def contigs(self) -> dict:
        fai = Path(str(self.reference.fasta) + ".fai")
        if not fai.exists():
            return {}
        return {l.split("\t")[0]: int(l.split("\t")[1]) for l in fai.read_text().splitlines() if l}

    def shutdown(self, code: int = 0) -> None:
        self.exit_code = code
        self.monitor.stop()

        def later():
            time.sleep(0.4)
            if self.server:
                self.server.shutdown()
        threading.Thread(target=later, daemon=True).start()


APP: App | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "ONTFragmentDashboard"

    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _file(self, path: Path) -> None:
        if not path.is_file():
            return self._send(404, b"Not found", "text/plain")
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            ctype = "text/javascript"
        self._send(200, path.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                return self._file(WEB_DIR / "index.html")
            if url.path == "/static/plotly.min.js":
                p = plotly_js()
                return self._file(p) if p else self._send(404, b"", "text/plain")
            if url.path.startswith("/static/"):
                target = (WEB_DIR / url.path[len("/static/"):]).resolve()
                if WEB_DIR in target.parents:
                    return self._file(target)
                return self._send(404, b"", "text/plain")
            if url.path == "/logo.png":
                return self._file(ROOT / "img" / "logo.png")
            if url.path == "/api/ping":
                return self._json({"ok": True, "app": "ont-fragment-dashboard"})
            if url.path == "/api/state":
                return self._json({
                    "setup": APP.reference.snapshot(),
                    "job": APP.monitor.status(),
                    "running": APP.monitor.running(),
                    "update": APP.updater.snapshot(),
                    "log": list(LOG)[-200:],
                    "platform": {"os": pu.os_label(), "wsl": pu.is_wsl()},
                })
            if url.path == "/api/init":
                return self._json({
                    "catalog": APP.catalog.all(),
                    "defaults": DEFAULT_SETTINGS,
                    "prefs": load_prefs(),
                    "version": APP.updater.current,
                    "platform": {"os": pu.os_label(), "wsl": pu.is_wsl()},
                    "roots": pu.browse_roots(),
                })
            if url.path == "/api/results":
                return self._json(APP.monitor.get_results() or {})
            if url.path == "/api/ls":
                return self._json(pu.list_dirs(q.get("path") or str(Path.home())))
            if url.path == "/api/download":
                r = APP.monitor.get_results()
                name = {"stats": "fragment_stats.tsv", "deletion": "hrp_deletion_screen.tsv"}.get(q.get("what", ""))
                if not r or not name:
                    return self._send(404, b"Nothing to download yet", "text/plain")
                p = Path(r["run"]["out_dir"]) / name
                if not p.exists():
                    return self._send(404, b"Nothing to download yet", "text/plain")
                body = p.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/tab-separated-values")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send(404, b"Not found", "text/plain")
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def do_POST(self):
        url = urlparse(self.path)
        # Only the dashboard page sends JSON. A form posted by another web site cannot set this
        # content type without a CORS preflight, which this server never answers.
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json({"error": "Unsupported request."}, 415)
        try:
            body = self._body()
            if url.path == "/api/resolve":
                return self._json(pu.resolve_fastq_pass(body.get("path", "")))
            if url.path == "/api/pick-folder":
                picked = pu.pick_folder()
                if not picked:
                    return self._json({"cancelled": True})
                return self._json(pu.resolve_fastq_pass(picked))
            if url.path == "/api/start":
                if not APP.reference.snapshot()["ready"]:
                    raise ValueError("The reference is not ready yet.")
                info = pu.resolve_fastq_pass(body.get("path", ""))
                APP.monitor.start(Path(info["path"]), body.get("fragments", []), body.get("settings", {}))
                save_prefs({"fastq_pass": info["display"], "fragments": body.get("fragments", []),
                            "settings": body.get("settings", {})})

                def remember():
                    for _ in range(100):
                        if APP.monitor.run_dir:
                            save_prefs({"last_run_dir": str(APP.monitor.run_dir)})
                            return
                        time.sleep(0.2)
                threading.Thread(target=remember, daemon=True).start()
                return self._json({"ok": True, "resolved": info})
            if url.path == "/api/stop":
                APP.monitor.stop()
                return self._json({"ok": True})
            if url.path == "/api/refresh":
                APP.monitor.refresh_now()
                return self._json({"ok": True})
            if url.path == "/api/prefs":
                save_prefs(body)
                return self._json({"ok": True})
            if url.path == "/api/custom/add":
                items = body.get("items")
                if items is None and body.get("text"):
                    items = parse_bed_or_tsv(body["text"])
                    for it in items:
                        it.setdefault("panel", body.get("panel") or "Custom")
                added = APP.catalog.add_custom(items or [], APP.contigs())
                return self._json({"ok": True, "added": len(added), "catalog": APP.catalog.all()})
            if url.path == "/api/custom/delete":
                APP.catalog.delete_custom(body.get("ids", []))
                return self._json({"ok": True, "catalog": APP.catalog.all()})
            if url.path == "/api/open-folder":
                r = APP.monitor.get_results()
                target = Path(body.get("path") or (r["run"]["out_dir"] if r else ROOT / "results"))
                target.mkdir(parents=True, exist_ok=True)
                pu.open_in_file_manager(target)
                return self._json({"ok": True})
            if url.path == "/api/check-update":
                APP.updater.check()
                return self._json(APP.updater.snapshot())
            if url.path == "/api/update":
                if APP.monitor.running():
                    raise ValueError("Stop the monitoring before updating.")
                APP.updater.apply()
                APP.shutdown(RESTART_CODE)
                return self._json({"ok": True, "restarting": True})
            if url.path == "/api/quit":
                APP.shutdown(0)
                return self._json({"ok": True})
            self._send(404, b"Not found", "text/plain")
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)


def existing_instance() -> str | None:
    try:
        info = json.loads(INSTANCE_FILE.read_text())
        url = info["url"]
        with urllib.request.urlopen(url + "/api/ping", timeout=1.5) as resp:
            if json.loads(resp.read()).get("app") == "ont-fragment-dashboard":
                return url
    except Exception:
        return None
    return None


def free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 50)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def main() -> int:
    global APP
    parser = argparse.ArgumentParser(description="ONT Fragment Monitoring Dashboard")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ONT_DASHBOARD_PORT", 8866)))
    parser.add_argument("--host", default=os.environ.get("ONT_DASHBOARD_HOST", "127.0.0.1"))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    running = existing_instance()
    if running:
        print(f"The dashboard is already running at {running}. Opening it.")
        if not args.no_browser:
            pu.open_browser(running)
        return 0

    APP = App()
    port = free_port(args.port)
    server = ThreadingHTTPServer((args.host, port), Handler)
    server.daemon_threads = True
    APP.server = server
    url = f"http://127.0.0.1:{server.server_address[1]}"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    INSTANCE_FILE.write_text(json.dumps({"url": url, "pid": os.getpid()}))
    log(f"Dashboard running at {url} on {pu.os_label()}. Keep this window open while you use it.")
    if not args.no_browser:
        threading.Timer(0.8, pu.open_browser, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        APP.monitor.stop()
        INSTANCE_FILE.unlink(missing_ok=True)
    return APP.exit_code


if __name__ == "__main__":
    sys.exit(main())
