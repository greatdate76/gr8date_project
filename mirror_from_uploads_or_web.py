#!/usr/bin/env python3
import csv, hashlib, mimetypes, os, re, sys, time
from pathlib import Path
from urllib.parse import urlparse
import requests

PROFILE_COL = "profile_image"
ADDITIONAL_COL = "additional_images"
PRIVATE_COL = "private_images"
MULTI_SPLIT = re.compile(r'[;,]\s*')

def nonempty(s):
    return isinstance(s, str) and s.strip() and s.strip().lower() not in ["nan","none"]

def is_url(s): return isinstance(s, str) and s.lower().startswith(("http://","https://"))

def fix_url(u: str) -> str:
    u = u.strip()
    if u.startswith('https:/') and not u.startswith('https://'): u = u.replace('https:/','https://',1)
    if u.startswith('http:/') and not u.startswith('http://'):   u = u.replace('http:/','http://',1)
    return u

def slugify(s):
    s = re.sub(r"[^\w.\-]+","_", s.strip())
    s = re.sub(r"_+","_", s).strip("_")
    return s or "file"

def rel_uploads_path(url: str):
    try: p = urlparse(url).path
    except Exception: return None
    m = re.search(r"/wp-content/uploads/(.+)$", p, re.IGNORECASE)
    return Path(m.group(1)) if m else None

def copy_local(src: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(Path(src).read_bytes())

def first_from(val):
    if not nonempty(val): return ""
    parts = [p for p in MULTI_SPLIT.split(val) if p.strip()]
    return parts[0].strip() if parts else ""

def process_cell(cell_val, user_id, uploads_root: Path, media_root: Path, session):
    """STRICT: Only copy if exact rel path exists under uploads/. No basename fallback."""
    if not nonempty(cell_val): return ""
    out_paths = []
    raw_parts = [x.strip() for x in MULTI_SPLIT.split(str(cell_val)) if nonempty(x)]
    for url in map(fix_url, raw_parts):
        if not is_url(url):  # already-local path?
            out_paths.append(url)
            continue
        rel = rel_uploads_path(url)
        if not rel:  # not in /wp-content/uploads → skip
            continue
        local_src = uploads_root / rel
        if not local_src.exists():
            # do NOT fallback by filename; skip to avoid mismatches
            continue
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        base = slugify(local_src.name).split("?")[0].split("#")[0]
        dest = (media_root / f"user_{user_id}" / f"{h}_{base}")
        if not dest.suffix:
            dest = dest.with_suffix(local_src.suffix or ".jpg")
        try:
            copy_local(local_src, dest)
            rel_out = Path("media") / dest.relative_to(media_root.parent)
            out_paths.append(str(rel_out))
        except Exception as e:
            print(f"[WARN] Copy failed {local_src} → {dest}: {e}")
    # de-dup & remove empties
    out_paths = [p for i,p in enumerate(out_paths) if p and p not in out_paths[:i]]
    return ";".join(out_paths)

def main():
    if len(sys.argv) < 5:
        print("Usage:\n  python mirror_from_uploads_or_web.py <INPUT_CSV> <OUTPUT_CSV> <UPLOADS_ROOT> <MEDIA_ROOT>\n"); sys.exit(1)
    input_csv, output_csv, uploads_root, media_root = map(lambda p: Path(p).expanduser(), sys.argv[1:5])
    import pandas as pd
    df = pd.read_csv(input_csv)

    cols = {c.lower(): c for c in df.columns}
    def get(name): return cols.get(name.lower())

    uid_col = get("user_id") or get("id") or get("uid")
    prof_col = get(PROFILE_COL) or PROFILE_COL
    addl_col = get(ADDITIONAL_COL) or ADDITIONAL_COL
    priv_col = get(PRIVATE_COL) or PRIVATE_COL
    if not uid_col: raise SystemExit("CSV must have user_id/id/uid column.")
    if prof_col not in df.columns: df[prof_col] = ""

    # promote first additional/private image to profile if profile missing
    for i,row in df.iterrows():
        if not nonempty(row.get(prof_col)):
            df.at[i, prof_col] = first_from(row.get(addl_col,"")) or first_from(row.get(priv_col,""))

    session = requests.Session()
    for col in [prof_col, addl_col, priv_col]:
        if col in df.columns:
            df[col] = [
                process_cell(row.get(col,""), row[uid_col], uploads_root, media_root, session)
                for _,row in df.iterrows()
            ]

    # drop empty image columns entirely if they ended up blank
    for col in [prof_col, addl_col, priv_col]:
        if col in df.columns and not df[col].fillna("").str.strip().any():
            df.drop(columns=[col], inplace=True)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"Done.\nCSV written to: {output_csv}\nMedia saved under: {media_root}")

if __name__ == "__main__":
    main()
