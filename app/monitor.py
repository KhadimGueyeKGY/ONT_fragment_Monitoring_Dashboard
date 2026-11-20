# Malaria dashboard monitor (ONT fragment monitoring). Author: Khadim Gueye
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pysam

from catalog import DELETION_GENES
from platform_utils import barcode_dirs, list_read_files, natural_key, to_display_path

DEFAULT_SETTINGS = {
    "threshold": 100,
    "min_depth": 10,
    "min_mapq": 10,
    "min_overlap": 50,
    "refresh_seconds": 30,
    # Half of the processors by default: the sequencer (MinKNOW, basecalling) keeps the other half.
    "threads": max(1, min(16, (os.cpu_count() or 2) // 2)),
    "parallel": 5,
    "padding": 50,
    "deletion_ratio": 0.05,
    "include_unclassified": False,
}
# Analysis programs run at low priority so that they never slow down the sequencing software.
LOW_PRIORITY = ["nice", "-n", "15"] if shutil.which("nice") else []
STATS_KEYS = ("min_depth", "min_mapq", "min_overlap", "threshold", "deletion_ratio")
FILE_SETTLE_SECONDS = 10
PROFILE_BINS = 120


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_json(path: Path, payload) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


class Stopped(Exception):
    pass


class Monitor:
    """Maps new reads of each barcode on the selected fragments and keeps per fragment statistics."""

    def __init__(self, reference: Path, results_root: Path, catalog, log):
        self.reference = reference
        self.results_root = results_root
        self.catalog = catalog
        self.log = log
        self.lock = threading.RLock()
        self.state_lock = threading.Lock()
        self.publish_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.procs: list[subprocess.Popen] = []
        self.job = {"state": "idle", "message": "Select a fastq_pass folder and the fragments, then start."}
        self.results: dict | None = None
        self.results_version = 0
        self.run_dir: Path | None = None

    # ---------- public ----------

    def status(self) -> dict:
        with self.lock:
            job = dict(self.job)
        if self.run_dir:
            job["out_dir"] = str(self.run_dir)
            job["out_display"] = to_display_path(self.run_dir)
        job["results_version"] = self.results_version
        return job

    def get_results(self) -> dict | None:
        with self.lock:
            return self.results

    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, fastq_pass: Path, fragment_ids: list[str], settings: dict) -> None:
        if self.running():
            raise RuntimeError("Monitoring is already running. Stop it first.")
        fragments = self.catalog.by_ids(fragment_ids)
        if not fragments:
            raise ValueError("Select at least one fragment.")
        cfg = {**DEFAULT_SETTINGS, **{k: settings[k] for k in settings if k in DEFAULT_SETTINGS}}
        for key in ("threshold", "min_depth", "min_mapq", "min_overlap", "refresh_seconds", "threads", "padding", "parallel"):
            cfg[key] = max(0, int(cfg[key]))
        cfg["parallel"] = min(32, max(1, cfg["parallel"]))
        cfg["refresh_seconds"] = max(5, cfg["refresh_seconds"])
        cfg["threads"] = max(1, cfg["threads"])
        cfg["min_overlap"] = min(100, cfg["min_overlap"])
        cfg["deletion_ratio"] = float(cfg["deletion_ratio"])
        cfg["include_unclassified"] = bool(cfg["include_unclassified"])
        self.stop_event.clear()
        self.wake_event.clear()
        self._set_job(state="preparing", message="Preparing the fragment reference.", fastq_pass=str(fastq_pass),
                      fastq_display=to_display_path(fastq_pass), started=now_str(), cycle=0, progress=None, next_cycle_at=None)
        self.thread = threading.Thread(target=self._run, args=(fastq_pass, fragments, cfg), daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        for p in list(self.procs):
            try:
                p.terminate()
            except Exception:
                pass

    def refresh_now(self) -> None:
        self.wake_event.set()

    def load_previous(self, run_dir: Path) -> bool:
        res = run_dir / "results.json"
        if not res.exists():
            return False
        try:
            data = json.loads(res.read_text(encoding="utf-8"))
        except Exception:
            return False
        with self.lock:
            self.results = data
            self.results_version += 1
            self.run_dir = run_dir
        meta = data.get("run", {})
        self._set_job(state="stopped", message="Showing the last run. Press Start to continue monitoring it.",
                      fastq_pass=meta.get("fastq_pass"), fastq_display=meta.get("fastq_display"))
        return True

    # ---------- internals ----------

    def _set_job(self, **kw) -> None:
        with self.lock:
            self.job.update(kw)
            self.job["updated"] = now_str()

    def _check_stop(self) -> None:
        if self.stop_event.is_set():
            raise Stopped()

    def _run(self, fastq_pass: Path, fragments: list[dict], cfg: dict) -> None:
        try:
            run = self._prepare(fastq_pass, fragments, cfg)
            self.log(f"Monitoring {to_display_path(fastq_pass)} on {len(fragments)} fragments.")
            while not self.stop_event.is_set():
                with self.lock:
                    self.job["cycle"] = self.job.get("cycle", 0) + 1
                self._cycle(run)
                self._check_stop()
                wait = cfg["refresh_seconds"]
                self._set_job(state="waiting", progress=None, next_cycle_at=time.time() + wait,
                              message=f"Up to date. Next check in {wait} s.")
                self.wake_event.wait(wait)
                self.wake_event.clear()
            raise Stopped()
        except Stopped:
            self._set_job(state="stopped", message="Monitoring stopped.", progress=None, next_cycle_at=None)
            self.log("Monitoring stopped.")
        except Exception as exc:
            self._set_job(state="error", message=str(exc), progress=None, next_cycle_at=None)
            self.log("ERROR: " + str(exc))
        finally:
            self.procs.clear()

    def _prepare(self, fastq_pass: Path, fragments: list[dict], cfg: dict) -> dict:
        fasta = pysam.FastaFile(str(self.reference))
        lengths = dict(zip(fasta.references, fasta.lengths))
        for f in fragments:
            if f["chrom"] not in lengths:
                raise ValueError(f"{f['name']}: chromosome {f['chrom']} is not in the reference.")

        intervals = [(f["chrom"], f["start"] - 1, f["end"]) for f in fragments]
        # Reads from hrp2 and hrp3 align to each other. When one is monitored, the other is added
        # to the mapping reference (not displayed) so its reads cannot inflate the monitored gene.
        genes = {f["gene"] for f in fragments}
        decoys = []
        if genes & set(DELETION_GENES):
            for g in DELETION_GENES:
                spans = [(c["chrom"], c["start"] - 1, c["end"]) for c in self.catalog.all() if c["gene"] == g]
                if spans and g not in genes:
                    chrom = spans[0][0]
                    decoys.append((chrom, min(s[1] for s in spans if s[0] == chrom), max(s[2] for s in spans if s[0] == chrom)))
        loci = self._merge_loci(intervals + decoys, cfg["padding"], lengths)

        signature = json.dumps({"fq": str(fastq_pass.resolve()), "loci": loci}, sort_keys=True)
        key = hashlib.sha1(signature.encode()).hexdigest()[:8]
        run_label = re.sub(r"[^A-Za-z0-9._-]+", "_", fastq_pass.parent.name or "run")[:60]
        run_dir = self.results_root / f"{run_label}_{key}"
        (run_dir / "bam").mkdir(parents=True, exist_ok=True)
        (run_dir / "tmp").mkdir(exist_ok=True)
        # A new run starts from a clean screen; the same run started again shows its last results at once.
        previous = None
        if (run_dir / "results.json").exists():
            try:
                previous = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
            except Exception:
                previous = None
        with self.lock:
            self.run_dir = run_dir
            self.results = previous
            self.results_version += 1

        ref_fa = run_dir / "fragments_reference.fasta"
        ref_mmi = run_dir / "fragments_reference.mmi"
        if not ref_mmi.exists() or not ref_fa.exists():
            self.log(f"Extracting {len(loci)} loci from the reference for {len(fragments)} fragments.")
            with open(ref_fa, "w") as out:
                for chrom, s, e, name in loci:
                    seq = fasta.fetch(chrom, s, e)
                    out.write(f">{name}\n")
                    for i in range(0, len(seq), 80):
                        out.write(seq[i:i + 80] + "\n")
            pysam.faidx(str(ref_fa))
            self._exec(["minimap2", "-x", "map-ont", "-d", str(ref_mmi), str(ref_fa)])
        fasta.close()

        frag_pos = {}
        for f in fragments:
            s0, e0 = f["start"] - 1, f["end"]
            for chrom, ls, le, name in loci:
                if chrom == f["chrom"] and ls <= s0 and e0 <= le:
                    frag_pos[f["id"]] = (name, s0 - ls, e0 - ls)
                    break

        state_path = run_dir / "state.json"
        state = {"files": {}, "total_reads": {}, "stats": {}, "stats_sig": None}
        if state_path.exists():
            try:
                state.update(json.loads(state_path.read_text(encoding="utf-8")))
                self.log("Resuming: files already mapped in this run folder are skipped.")
            except Exception:
                pass
        meta = {"fastq_pass": str(fastq_pass), "fastq_display": to_display_path(fastq_pass),
                "fragments_reference": str(ref_fa), "loci": len(loci), "decoys": len(decoys)}
        (run_dir / "run_info.json").write_text(json.dumps({**meta, "fragments": fragments, "settings": cfg}, indent=2))
        return {"fastq_pass": fastq_pass, "fragments": fragments, "cfg": cfg, "dir": run_dir, "mmi": ref_mmi,
                "pos": frag_pos, "state": state, "state_path": state_path, "meta": meta}

    @staticmethod
    def _merge_loci(intervals, pad, lengths):
        by_chrom: dict[str, list] = {}
        for c, s, e in intervals:
            by_chrom.setdefault(c, []).append([max(0, s - pad), min(lengths[c], e + pad)])
        loci = []
        for c in sorted(by_chrom, key=natural_key):
            spans = sorted(by_chrom[c])
            merged = [spans[0]]
            for s, e in spans[1:]:
                if s <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], e)
                else:
                    merged.append([s, e])
            loci.extend((c, s, e, f"{c}_{s + 1}_{e}") for s, e in merged)
        return loci

    def _exec(self, cmd: list[str]) -> None:
        out = subprocess.run(LOW_PRIORITY + cmd, capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(f"{cmd[0]} failed: {out.stderr.strip()[-400:]}")

    def _cycle(self, run: dict) -> None:
        cfg, state = run["cfg"], run["state"]
        fq = run["fastq_pass"]
        if not fq.exists():
            raise RuntimeError(f"The fastq_pass folder is not reachable anymore: {to_display_path(fq)}")
        dirs = barcode_dirs(fq, cfg["include_unclassified"])
        groups = [(d.name, d) for d in dirs] or ([("all_reads", fq)] if list_read_files(fq) else [])
        stats_sig = json.dumps({k: cfg[k] for k in STATS_KEYS}, sort_keys=True)
        if state.get("stats_sig") != stats_sig:
            state["stats"] = {}
            state["stats_sig"] = stats_sig

        total = len(groups)
        order = [g[0] for g in groups]
        # Never more mapping jobs than CPU threads allowed, so the total load stays within the setting.
        workers = max(1, min(cfg["parallel"], cfg["threads"], total or 1))
        per_job_threads = max(1, cfg["threads"] // workers)
        self._set_job(state="mapping", next_cycle_at=None, progress={"current": 0, "total": total, "running": workers} if total else None,
                      message=f"Processing {total} barcodes, {workers} at a time." if total else "Waiting for the first reads.")

        def process(bc: str, folder: Path) -> bool:
            self._check_stop()
            with self.state_lock:
                done = set(state["files"].get(bc, []))
                has_stats = bc in state["stats"]
            cutoff = time.time() - FILE_SETTLE_SECONDS
            new = [p for p in list_read_files(folder) if p.name not in done and p.stat().st_mtime < cutoff]
            bam = run["dir"] / "bam" / f"{bc}.bam"
            if new:
                n_reads = self._map_batch(new, bam, run, per_job_threads)
                with self.state_lock:
                    state["files"][bc] = sorted(done | {p.name for p in new})
                    state["total_reads"][bc] = state["total_reads"].get(bc, 0) + n_reads
                self.log(f"{bc}: {len(new)} new file(s), {n_reads} reads processed.")
            if new or not has_stats:
                stats = self._barcode_stats(bam, run, cfg) if bam.exists() else self._empty_stats(run)
                with self.state_lock:
                    state["stats"][bc] = stats
                    write_json(run["state_path"], state)
                return True
            return False

        # Barcodes are processed several at a time, and the results are published as soon as each
        # barcode is finished, so the first barcodes are on screen while the others still run.
        stopped, finished = False, 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process, bc, folder): bc for bc, folder in groups}
            for fut in as_completed(futures):
                bc = futures[fut]
                finished += 1
                try:
                    changed = fut.result()
                except Stopped:
                    stopped = True
                    continue
                except Exception as exc:
                    self.log(f"ERROR {bc}: {exc}. It is tried again at the next check.")
                    changed = False
                self._set_job(progress={"current": finished, "total": total, "running": min(workers, total - finished)},
                              message=f"Processing barcodes: {finished} of {total} done.")
                if changed and not stopped:
                    self._publish_ready(run, order)
        if stopped or self.stop_event.is_set():
            raise Stopped()
        self._publish_ready(run, order)

    def _depth_by_contig(self, bam_path: Path, contig_len: dict, min_mapq: int) -> dict:
        # Same reads as the counts (primary, mapping quality filter). Bases inside a deletion are
        # not counted, as with pysam count_coverage used before.
        out = subprocess.run(LOW_PRIORITY + ["samtools", "depth", "-aa", "-Q", str(min_mapq), "-G", "0xF04", str(bam_path)],
                             capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError("samtools depth failed: " + out.stderr.strip()[-300:])
        depth = {c: np.zeros(n, dtype=np.int64) for c, n in contig_len.items()}
        for line in out.stdout.splitlines():
            c, p, d = line.split("\t")
            if d != "0":
                depth[c][int(p) - 1] = int(d)
        return depth

    def _publish_ready(self, run: dict, order: list[str]) -> None:
        with self.state_lock:
            ready = [bc for bc in order if bc in run["state"]["stats"]]
        with self.publish_lock:
            self._publish(run, ready)

    def _map_batch(self, files: list[Path], bam: Path, run: dict, threads: int) -> int:
        tmp_dir = run["dir"] / "tmp"
        chunk = tmp_dir / f"{bam.stem}.chunk.bam"
        mm = subprocess.Popen(LOW_PRIORITY + ["minimap2", "-t", str(threads), "-ax", "map-ont", "--secondary=no", "--sam-hit-only",
                                              str(run["mmi"]), "-"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        st = subprocess.Popen(LOW_PRIORITY + ["samtools", "sort", "-@", "1", "-m", "200M", "-T", str(tmp_dir / bam.stem), "-o", str(chunk), "-"],
                              stdin=mm.stdout, stderr=subprocess.PIPE)
        mm.stdout.close()
        with self.lock:
            self.procs.extend([mm, st])
        counter = {"lines": 0, "error": None, "bad": []}

        def feed():
            try:
                for f in files:
                    # A damaged file is read in full first, so that a truncated archive never
                    # sends half a record to the aligner. It is skipped and reported.
                    try:
                        opener = gzip.open if f.name.lower().endswith(".gz") else open
                        with opener(f, "rb") as fh:
                            data = fh.read()
                    except (OSError, EOFError) as exc:
                        counter["bad"].append(f"{f.name} ({exc})")
                        continue
                    if self.stop_event.is_set():
                        return
                    if data and not data.endswith(b"\n"):
                        data += b"\n"
                    counter["lines"] += data.count(b"\n")
                    mm.stdin.write(data)
            except (BrokenPipeError, OSError) as exc:
                counter["error"] = exc
            finally:
                try:
                    mm.stdin.close()
                except Exception:
                    pass

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        mm_err = mm.stderr.read()
        feeder.join()
        mm_rc, st_rc = mm.wait(), st.wait()
        with self.lock:
            for p in (mm, st):
                if p in self.procs:
                    self.procs.remove(p)
        self._check_stop()
        if mm_rc != 0:
            raise RuntimeError("minimap2 failed: " + mm_err.decode(errors="replace").strip()[-400:])
        if st_rc != 0:
            raise RuntimeError("samtools sort failed: " + st.stderr.read().decode(errors="replace").strip()[-400:])
        if counter["error"]:
            raise RuntimeError(f"Could not send reads to minimap2: {counter['error']}")
        for bad in counter["bad"]:
            self.log(f"WARNING {bam.stem}: unreadable file skipped: {bad}")

        if bam.exists():
            merged = tmp_dir / f"{bam.stem}.merged.bam"
            self._exec(["samtools", "merge", "-f", "-@", str(threads), "-o", str(merged), str(bam), str(chunk)])
            merged.replace(bam)
            chunk.unlink(missing_ok=True)
        else:
            chunk.replace(bam)
        self._exec(["samtools", "index", str(bam)])
        return counter["lines"] // 4

    def _empty_stats(self, run: dict) -> dict:
        ids = [f["id"] for f in run["fragments"]]
        return {"reads": {i: 0 for i in ids}, "depth": {i: 0.0 for i in ids}, "breadth": {i: 0.0 for i in ids},
                "profile": {i: [] for i in ids}, "on_target": 0}

    def _barcode_stats(self, bam_path: Path, run: dict, cfg: dict) -> dict:
        """Reads per fragment from one pass over the BAM, depth per base from samtools depth."""
        min_mapq, frac, min_depth = cfg["min_mapq"], cfg["min_overlap"] / 100.0, cfg["min_depth"]
        out = self._empty_stats(run)
        with pysam.AlignmentFile(str(bam_path), "rb") as bam:
            contig_id = {name: i for i, name in enumerate(bam.references)}
            contig_len = dict(zip(bam.references, bam.lengths))
            tids, starts, ends = [], [], []
            for r in bam.fetch(until_eof=True):
                # 0x904: unmapped, secondary or supplementary alignment
                if r.flag & 0x904 or r.mapping_quality < min_mapq:
                    continue
                tids.append(r.reference_id)
                starts.append(r.reference_start)
                ends.append(r.reference_end)
        tids, starts, ends = np.array(tids, dtype=np.int64), np.array(starts, dtype=np.int64), np.array(ends, dtype=np.int64)
        out["on_target"] = int(tids.size)
        depth = self._depth_by_contig(bam_path, contig_len, min_mapq)

        for f in run["fragments"]:
            pos = run["pos"].get(f["id"])
            if not pos:
                continue
            contig, s, e = pos
            on = tids == contig_id.get(contig, -1)
            overlap = np.minimum(ends[on], e) - np.maximum(starts[on], s)
            out["reads"][f["id"]] = int((overlap >= frac * (e - s)).sum())
            cov = depth.get(contig, np.zeros(contig_len.get(contig, e), dtype=np.int64))[s:e]
            out["depth"][f["id"]] = round(float(cov.mean()), 1) if cov.size else 0.0
            out["breadth"][f["id"]] = round(float((cov >= min_depth).mean() * 100), 1) if cov.size else 0.0
            bins = np.array_split(cov, min(PROFILE_BINS, max(1, cov.size)))
            out["profile"][f["id"]] = [int(round(b.mean())) for b in bins]
        return out

    def _publish(self, run: dict, barcodes: list[str]) -> None:
        cfg, state, frags = run["cfg"], run["state"], run["fragments"]
        thr = cfg["threshold"]
        stats = {bc: state["stats"].get(bc) or self._empty_stats(run) for bc in barcodes}

        profiles = {}
        for f in frags:
            n = len(next((stats[bc]["profile"][f["id"]] for bc in barcodes if stats[bc]["profile"].get(f["id"])), []))
            step = f["length"] / n if n else 0
            profiles[f["id"]] = {"x": [int(f["start"] + step * (i + 0.5)) for i in range(n)],
                                 "y": {bc: stats[bc]["profile"].get(f["id"], []) for bc in barcodes}}

        deletion = self._deletion_summary(frags, barcodes, stats, thr, cfg["deletion_ratio"])
        results = {
            "updated": now_str(),
            "run": {**run["meta"], "out_dir": str(run["dir"]), "out_display": to_display_path(run["dir"])},
            "settings": cfg,
            "fragments": [{k: f[k] for k in ("id", "panel", "name", "gene", "category", "chrom", "start", "end", "length")} for f in frags],
            "barcodes": barcodes,
            "reads": {bc: stats[bc]["reads"] for bc in barcodes},
            "depth": {bc: stats[bc]["depth"] for bc in barcodes},
            "breadth": {bc: stats[bc]["breadth"] for bc in barcodes},
            "totals": {bc: {"reads": state["total_reads"].get(bc, 0), "on_target": stats[bc]["on_target"]} for bc in barcodes},
            "profiles": profiles,
            "deletion": deletion,
        }
        write_json(run["dir"] / "results.json", results)
        self._write_tables(run["dir"], results)
        with self.lock:
            self.results = results
            self.results_version += 1

    @staticmethod
    def _deletion_summary(frags, barcodes, stats, thr, ratio):
        targets = {g: [f["id"] for f in frags if f["gene"] == g] for g in DELETION_GENES}
        targets = {g: ids for g, ids in targets.items() if ids}
        if not targets:
            return None
        controls = [f["id"] for f in frags if f["gene"] not in DELETION_GENES]
        rows = {}
        for bc in barcodes:
            s = stats[bc]
            ctrl = float(np.median([s["reads"][i] for i in controls])) if controls else None
            rows[bc] = {"control_median": ctrl}
            for g, ids in targets.items():
                reads = max(s["reads"][i] for i in ids)
                breadth = max(s["breadth"][i] for i in ids)
                depth = max(s["depth"][i] for i in ids)
                if reads >= thr:
                    status = "detected"
                elif ctrl is not None and ctrl >= thr and reads < ratio * ctrl:
                    status = "possible_deletion"
                elif ctrl is not None and ctrl >= thr:
                    status = "low"
                else:
                    status = "insufficient"
                rows[bc][g] = {"status": status, "reads": reads, "breadth": breadth, "depth": depth,
                               "ratio": round(reads / ctrl, 3) if ctrl else None}
        return {"genes": list(targets), "controls": len(controls), "ratio": ratio, "rows": rows}

    @staticmethod
    def _write_tables(run_dir: Path, r: dict) -> None:
        names = {f["id"]: f"{f['panel']}:{f['name']}" for f in r["fragments"]}
        with open(run_dir / "fragment_stats.tsv", "w", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["barcode", "fragment", "chrom", "start", "end", "reads", "mean_depth",
                        f"breadth_pct_depth_ge_{r['settings']['min_depth']}"])
            for bc in r["barcodes"]:
                for f in r["fragments"]:
                    w.writerow([bc, names[f["id"]], f["chrom"], f["start"], f["end"],
                                r["reads"][bc][f["id"]], r["depth"][bc][f["id"]], r["breadth"][bc][f["id"]]])
        if r["deletion"]:
            with open(run_dir / "hrp_deletion_screen.tsv", "w", newline="") as fh:
                w = csv.writer(fh, delimiter="\t")
                w.writerow(["barcode", "gene", "status", "reads", "mean_depth", "breadth_pct", "control_median_reads", "ratio_to_control"])
                for bc in r["barcodes"]:
                    row = r["deletion"]["rows"][bc]
                    for g in r["deletion"]["genes"]:
                        d = row[g]
                        w.writerow([bc, g, d["status"], d["reads"], d["depth"], d["breadth"], row["control_median"], d["ratio"]])
