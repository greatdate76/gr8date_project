#!/usr/bin/env python3
import csv, re, sys, os, time
from pathlib import Path
from urllib.parse import urlparse

MULTI = re.compile(r"[;,]\s*")
YEAR_MONTH = re.compile(r"/(20\d{2})/(\d{1,2})(?:/|$)")
IMG_EXT = re.compile(r"\.(?:jpe?g|png|gif|webp|bmp|avif)(?:\?|#|$)", re.I)

def nonempty(s): return isinstance(s,str) and s.strip() and s.strip().lower() not in {"nan","none","null"}
def split_multi(v): return [s.strip() for s in MULTI.split(str(v)) if s.strip()] if nonempty(v) else []

def path_tail(value: str) -> str:
    """Extract a meaningful tail from URL or path and normalise common prefixes."""
    if not isinstance(value, str): return ""
    raw = value.strip()
    if raw.lower().startswith(("http://","https://")):
        raw = urlparse(raw).path or raw
    raw = raw.split("?")[0].split("#")[0].lstrip("/")
    for prefix in ("wp-content/uploads/", "uploads/"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
            break
    # if any plugin folder appears, keep from there
    for key in ("gravity_forms/", "formidable/", "avatars/"):
        i = raw.lower().find(key)
        if i != -1:
            return raw[i:]
    return raw

def strip_gf_face(name):
    n = re.sub(r"^face_[^_]+_(.+)$", r"\1", name)
    n = re.sub(r"^face_(.+)$", r"\1", n)
    return n

def find_candidates(uploads_root: Path, rel_hint: str):
    """Return (candidates, y, m) where candidates is a list[Path]."""
    # year/month from hint if present
    y = m = None
    mo = YEAR_MONTH.search("/"+rel_hint)  # add leading slash to simplify regex
    if mo:
        y, m = mo.group(1), mo.group(2).zfill(2)
    # try exact relative first
    exact = uploads_root / rel_hint
    hits = []
    if exact.exists():
        hits.append(exact)
    # then basename search
    base = strip_gf_face(Path(rel_hint).name)
    if base and IMG_EXT.search(base):
        # search everywhere for basename
        hits += [p for p in uploads_root.rglob(base) if p.is_file()]
    # de-dup while preserving order
    seen=set(); uniq=[]
    for p in hits:
        if p not in seen:
            seen.add(p); uniq.append(p)
    return uniq, y, m

def choose_best(hits, uploads_root: Path, year, month):
    if not hits: return None
    if len(hits) == 1: return hits[0]
    # prefer those under the hinted year/month
    if year:
        ym_hits = [p for p in hits if f"/{year}/" in str(p)]
        if ym_hits:
            if month:
                ymm_hits = [p for p in ym_hits if f"/{year}/{month}/" in str(p)]
                if ymm_hits:
                    hits = ymm_hits
                else:
                    hits = ym_hits
            else:
                hits = ym_hits
    # if still many, prefer shortest path (closer match)
    min_len = min(len(str(p)) for p in hits)
    short = [p for p in hits if len(str(p)) == min_len]
    if len(short) == 1:
        return short[0]
    # else newest mtime
    newest = max(short, key=lambda p: p.stat().st_mtime)
    return newest

def process_field(raw, uploads_root: Path):
    rels = []; missing = []; dups = []
    for token in split_multi(raw):
        rel_hint = path_tail(token)
        hits, y, m = find_candidates(uploads_root, rel_hint)
        pick = choose_best(hits, uploads_root, y, m)
        if pick:
            rels.append(str(pick.relative_to(uploads_root)))
            if len(hits) > 1:
                dups.append({"value": token, "chosen": str(pick), "alts": "|".join(str(h) for h in hits[:10])})
        else:
            missing.append(token)
    # de-dup keep order
    seen=set(); out=[]
    for s in rels:
        if s not in seen:
            seen.add(s); out.append(s)
    return out, missing, dups

def main():
    if len(sys.argv)<5:
        print("Usage:\n  python remap_images_relaxed_v4.py <INPUT_CSV> <OUTPUT_CSV> <UPLOADS_ROOT> <REPORT_DIR>")
        sys.exit(1)
    in_csv, out_csv, uploads, repdir = map(lambda p: Path(p).expanduser(), sys.argv[1:5])
    repdir.mkdir(parents=True, exist_ok=True)
    if not uploads.exists():
        sys.exit(f"Uploads root not found: {uploads}")

    rows = list(csv.DictReader(open(in_csv, newline="", encoding="utf-8")))
    headers = rows[0].keys() if rows else []
    cols = {c.lower(): c for c in headers}
    def getcol(*names):
        for n in names:
            if n and n.lower() in cols: return cols[n.lower()]
        return None

    uid_col  = getcol("user_id","uid","id")
    prof_col = getcol("profile_image")
    addl_col = getcol("additional_images","additional")
    priv_col = getcol("private_images","private")
    if not uid_col: sys.exit("CSV must have user_id/uid/id column.")

    out_rows=[]; miss=[]; dup_log=[]
    for row in rows:
        uid = (row.get(uid_col) or "").strip()

        def mapcol(col):
            if not col or col not in row: return []
            rels, missing, dups = process_field(row[col], uploads)
            for m in missing: miss.append({"user_id":uid,"field":col,"value":m})
            for d in dups: dup_log.append({"user_id":uid,"field":col, **d})
            return rels

        prof = mapcol(prof_col)
        addl = mapcol(addl_col)
        priv = mapcol(priv_col)

        # promote first available to avatar if avatar missing
        if not prof and addl:
            prof = [addl[0]]; addl = addl[1:]
        elif not prof and priv:
            prof = [priv[0]]; priv = priv[1:]

        new = dict(row)
        if prof_col: new[prof_col] = ";".join(prof)
        if addl_col: new[addl_col] = ";".join(addl)
        if priv_col: new[priv_col] = ";".join(priv)
        out_rows.append(new)

    with open(out_csv,"w",newline="",encoding="utf-8") as g:
        w=csv.DictWriter(g, fieldnames=headers); w.writeheader(); w.writerows(out_rows)

    with open(repdir/"remap_relaxed_missing.csv","w",newline="",encoding="utf-8") as g:
        w=csv.DictWriter(g, fieldnames=["user_id","field","value"]); w.writeheader(); w.writerows(miss)

    with open(repdir/"remap_relaxed_duplicates.csv","w",newline="",encoding="utf-8") as g:
        w=csv.DictWriter(g, fieldnames=["user_id","field","value","chosen","alts"]); w.writeheader(); w.writerows(dup_log)

    print("Wrote:", out_csv)
    print("Missing report:", repdir/"remap_relaxed_missing.csv", "rows:", len(miss))
    print("Duplicate-choice report:", repdir/"remap_relaxed_duplicates.csv", "rows:", len(dup_log))
if __name__ == "__main__":
    main()
