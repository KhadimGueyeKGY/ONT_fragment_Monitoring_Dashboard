from __future__ import annotations

import csv
import re
import threading
from pathlib import Path

COLUMNS = ["panel", "name", "gene", "gene_id", "chrom", "start", "end", "category"]
DELETION_GENES = ("hrp2", "hrp3")


def fragment_id(panel: str, name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"{panel}__{name}")


class Catalog:
    """Fragments available for monitoring: built-in panels plus user fragments."""

    def __init__(self, builtin: Path, custom: Path):
        self.builtin = builtin
        self.custom = custom
        self.lock = threading.Lock()

    @staticmethod
    def _read(path: Path, editable: bool) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                if not row.get("chrom") or not row.get("start"):
                    continue
                start, end = int(row["start"]), int(row["end"])
                rows.append({
                    "id": fragment_id(row["panel"], row["name"]),
                    "panel": row["panel"],
                    "name": row["name"],
                    "gene": row.get("gene") or row["name"],
                    "gene_id": row.get("gene_id") or "",
                    "chrom": row["chrom"],
                    "start": start,
                    "end": end,
                    "length": end - start + 1,
                    "category": row.get("category") or "Custom",
                    "custom": editable,
                })
        return rows

    def all(self) -> list[dict]:
        """Built-in fragments, with user edits applied, followed by user fragments."""
        with self.lock:
            builtin = {f["id"]: f for f in self._read(self.builtin, False)}
            extra = []
            for f in self._read(self.custom, True):
                if f["id"] in builtin:
                    orig = builtin[f["id"]]
                    builtin[f["id"]] = {**f, "custom": False, "edited": True,
                                        "default": {k: orig[k] for k in ("chrom", "start", "end", "category")}}
                else:
                    extra.append(f)
            return list(builtin.values()) + extra

    def infer_category(self, gene: str) -> str:
        g = (gene or "").strip().lower()
        if not g:
            return "Other"
        token = re.split(r"[-_ .:]", g)[0]
        builtin = self._read(self.builtin, False)
        for cand in dict.fromkeys([g, token, token.rstrip("0123456789"), {"k13": "kelch13"}.get(token, token)]):
            for f in builtin:
                if cand and (f["gene"].lower() == cand or f["name"].lower() == cand):
                    return f["category"]
        if g.startswith(("hrp", "pfhrp")):
            return "Diagnostic"
        return "Other"

    def by_ids(self, ids: list[str]) -> list[dict]:
        wanted = set(ids)
        return [f for f in self.all() if f["id"] in wanted]

    def add_custom(self, items: list[dict], contigs: dict[str, int]) -> list[dict]:
        clean = []
        for item in items:
            name = str(item.get("name", "")).strip()
            chrom = str(item.get("chrom", "")).strip()
            if not name or not chrom:
                raise ValueError("Each fragment needs a name and a chromosome.")
            if contigs and chrom not in contigs:
                raise ValueError(f"Unknown chromosome {chrom}. Expected names like Pf3D7_07_v3.")
            start, end = int(item["start"]), int(item["end"])
            if start < 1 or end <= start:
                raise ValueError(f"{name}: start must be at least 1 and lower than end.")
            if contigs and end > contigs[chrom]:
                raise ValueError(f"{name}: end is beyond the length of {chrom}.")
            clean.append({
                "panel": str(item.get("panel") or "Custom").strip() or "Custom",
                "name": name,
                "gene": str(item.get("gene") or name).strip(),
                "gene_id": str(item.get("gene_id") or "").strip(),
                "chrom": chrom,
                "start": start,
                "end": end,
                "category": self._category(item, name),
            })
        with self.lock:
            existing = self._read(self.custom, True)
            keep = {fragment_id(r["panel"], r["name"]): r for r in existing}
            for row in clean:
                keep[fragment_id(row["panel"], row["name"])] = row
            self._write(list(keep.values()))
        return clean

    def _category(self, item: dict, name: str) -> str:
        cat = str(item.get("category") or "").strip()
        if not cat or cat.lower() == "auto":
            return self.infer_category(str(item.get("gene") or name))
        return cat

    def delete_custom(self, ids: list[str]) -> None:
        """Remove user fragments, or restore the default position of an edited built-in fragment."""
        with self.lock:
            rows = [r for r in self._read(self.custom, True) if r["id"] not in set(ids)]
            self._write(rows)

    def _write(self, rows: list[dict]) -> None:
        self.custom.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.custom.with_suffix(".tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(COLUMNS)
            for r in rows:
                w.writerow([r[c] for c in COLUMNS])
        tmp.replace(self.custom)


def parse_bed_or_tsv(text: str) -> list[dict]:
    """Read fragments from a BED file (0-based) or a TSV with the catalog columns (1-based)."""
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith(("#", "track", "browser"))]
    if not lines:
        return []
    header = [h.strip().lower() for h in lines[0].split("\t")]
    if {"chrom", "start", "end"} <= set(header) or {"chromosome", "start_position", "end_position"} <= set(header):
        alias = {"chromosome": "chrom", "start_position": "start", "end_position": "end", "gene_symbol": "gene"}
        header = [alias.get(h, h) for h in header]
        out = []
        for l in lines[1:]:
            row = dict(zip(header, [v.strip() for v in l.split("\t")]))
            row.setdefault("name", row.get("gene") or f"{row['chrom']}_{row['start']}")
            out.append(row)
        return out
    out = []
    for l in lines:
        parts = re.split(r"\t|\s+", l.strip())
        if len(parts) < 3:
            continue
        chrom, start, end = parts[0], int(parts[1]) + 1, int(parts[2])
        name = parts[3] if len(parts) > 3 else f"{chrom}_{start}_{end}"
        out.append({"chrom": chrom, "start": start, "end": end, "name": name, "gene": re.sub(r"-p\d.*$", "", name)})
    return out
