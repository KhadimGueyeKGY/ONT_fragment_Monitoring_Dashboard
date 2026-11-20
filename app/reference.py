# Malaria dashboard monitor (ONT fragment monitoring). Author: Khadim Gueye
from __future__ import annotations

import gzip
import shutil
import threading
import urllib.request
from pathlib import Path

import pysam

REFERENCE_URL = "https://pf8-release.cog.sanger.ac.uk/reference/PlasmoDB-54-Pfalciparum3D7-Genome.fasta"
EXPECTED_CONTIG = "Pf3D7_01_v3"


class ReferenceSetup:
    """Checks the Pf3D7 reference and its index, downloads and indexes them when missing."""

    def __init__(self, fasta: Path, log):
        self.fasta = fasta
        self.log = log
        self.lock = threading.Lock()
        self.state = {
            "step": "checking",
            "ready": False,
            "error": None,
            "progress": None,
            "steps": {"conda": "done", "environment": "done", "reference": "pending", "index": "pending"},
        }

    def snapshot(self) -> dict:
        with self.lock:
            return {**self.state, "steps": dict(self.state["steps"]), "fasta": str(self.fasta)}

    def _set(self, **kw):
        with self.lock:
            steps = kw.pop("steps", None)
            self.state.update(kw)
            if steps:
                self.state["steps"].update(steps)

    def run(self) -> None:
        try:
            self._ensure_fasta()
            self._ensure_index()
            self._set(step="ready", ready=True, progress=None)
            self.log("Reference ready: " + str(self.fasta))
        except Exception as exc:
            self._set(step="error", error=str(exc))
            self.log("Reference setup failed: " + str(exc))

    def _fasta_ok(self) -> bool:
        if not self.fasta.exists() or self.fasta.stat().st_size < 1_000_000:
            return False
        with open(self.fasta, "rb") as fh:
            return fh.read(1) == b">"

    def _ensure_fasta(self) -> None:
        if self._fasta_ok():
            self._set(steps={"reference": "done"})
            return
        self._set(step="downloading", steps={"reference": "running"})
        self.fasta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.fasta.with_suffix(".download")
        self.log("Downloading reference from " + REFERENCE_URL)
        req = urllib.request.Request(REFERENCE_URL, headers={"User-Agent": "ont-fragment-dashboard"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                self._set(progress={"done": done, "total": total})
        with open(tmp, "rb") as fh:
            gz = fh.read(2) == b"\x1f\x8b"
        if gz:
            plain = tmp.with_suffix(".plain")
            with gzip.open(tmp, "rb") as src, open(plain, "wb") as dst:
                shutil.copyfileobj(src, dst)
            tmp.unlink()
            tmp = plain
        tmp.replace(self.fasta)
        for stale in (Path(str(self.fasta) + ".fai"),):
            stale.unlink(missing_ok=True)
        self._set(steps={"reference": "done"}, progress=None)

    def _ensure_index(self) -> None:
        fai = Path(str(self.fasta) + ".fai")
        if not fai.exists() or fai.stat().st_mtime < self.fasta.stat().st_mtime:
            self._set(step="indexing", steps={"index": "running"})
            self.log("Indexing reference (samtools faidx).")
            pysam.faidx(str(self.fasta))
        with pysam.FastaFile(str(self.fasta)) as fa:
            if EXPECTED_CONTIG not in fa.references:
                raise RuntimeError(
                    f"The reference does not contain {EXPECTED_CONTIG}. Fragment coordinates expect Pf3D7 (PlasmoDB 54)."
                )
        self._set(steps={"index": "done"})
