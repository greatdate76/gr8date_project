#!/usr/bin/env python3
import csv, hashlib, os, sys
from pathlib import Path

def nonempty(s): 
    return isinstance(s,str) and s.strip() and s.strip().lower() not in {"nan","none","null"}

def sha12(p: Path) -> str:
    h=hashlib.sha1()
    with open(p,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()[:12]

def mkdest(media_root: Path, user_id, src: Path) -> Path:
    return media_root / f"user_{user_id}" / f"{sha12(src)}_{src.name}"

def copy_to_media(src: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    dest.write_bytes(data)
    # return media-relative path expected by your importer: starts with "media/"
    return str(Path("media") / dest.relative_to(dest.parents[3]))  # media/profiles/...

def split_multi(val):
    if not nonempty(val): return []
    parts = []
    for raw in str(val).split(";"):
        for seg in raw.split(","):
            s = seg.strip()
            if s: parts.append(s)
    return parts

def main():
    if len(sys.argv) < 5:
        print("Usage:\n  python mirror_local_paths_only.py <INPUT_CSV> <OUTPUT_CSV> <UPLOADS_ROOT> <MEDIA_ROOT>")
        sys.exit(1)

    in_csv   = Path(sys.argv[1]).expanduser()
    out_csv  = Path(sys.argv[2]).expanduser()
    uploads  = Path(sys.argv[3]).expanduser()
    media    = Path(sys.argv[4]).expanduser()

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
    if not uid_col:
        raise SystemExit("CSV must have user_id/uid/id column.")

    created = skipped = 0
    out_rows = []

    for row in rows:
        uid = row.get(uid_col, "").strip()
        def process_field(field_name):
            if not field_name or field_name not in row: return ""
            vals = split_multi(row[field_name])
            out = []
            for v in vals:
                # treat as uploads-relative first (from CLEANED.csv e.g. "gravity_forms/.../file.jpg")
                # also tolerate paths that already start with "wp-content/uploads/..."
                rel = v.lstrip("/")
                if rel.startswith("wp-content/uploads/"):
                    rel = rel[len("wp-content/uploads/"):]
                cand = uploads / rel
                if not cand.exists():
                    # as a last fallback, try if the value is already an absolute file path on disk
                    cand = Path(v)
                if cand.exists() and cand.is_file():
                    dest = mkdest(media, uid or "unknown", cand)
                    try:
                        media_rel = copy_to_media(cand, dest)
                        out.append(media_rel)
                        created += 1
                    except Exception as e:
                        skipped += 1
                else:
                    skipped += 1
            # de-dup, keep order
            seen=set(); uniq=[]
            for s in out:
                if s not in seen:
                    seen.add(s); uniq.append(s)
            return ";".join(uniq)

        # build new row with media-relative paths
        new_row = dict(row)
        if prof_col: new_row[prof_col] = process_field(prof_col)
        if addl_col: new_row[addl_col] = process_field(addl_col)
        if priv_col: new_row[priv_col] = process_field(priv_col)
        out_rows.append(new_row)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as g:
        w = csv.DictWriter(g, fieldnames=headers)
        w.writeheader(); w.writerows(out_rows)

    print(f"Done. Wrote: {out_csv}")
    print(f"Copied images: {created}; skipped: {skipped}")
