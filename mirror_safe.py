#!/usr/bin/env python3
import csv, hashlib, re, sys
from pathlib import Path
from urllib.parse import urlparse

PROFILE_COL = "profile_image"
ADDITIONAL_COL = "additional_images"
PRIVATE_COL = "private_images"
MULTI_SPLIT = re.compile(r'[;,]\s*')

def nonempty(s):
    return isinstance(s, str) and s.strip() and s.strip().lower() not in ["nan", "none"]

def fix_url(u: str) -> str:
    u = u.strip()
    if u.startswith('https:/') and not u.startswith('https://'):
        u = u.replace('https:/', 'https://', 1)
    if u.startswith('http:/') and not u.startswith('http://'):
        u = u.replace('http:/', 'http://', 1)
    return u

def rel_uploads_path(url: str):
    try:
        p = urlparse(url).path
    except Exception:
        return None
    m = re.search(r"/wp-content/uploads/(.+)$", p, re.IGNORECASE)
    return Path(m.group(1)) if m else None

def first_from(val):
    if not nonempty(val):
        return ""
    parts = [p for p in MULTI_SPLIT.split(val) if p.strip()]
    return parts[0].strip() if parts else ""

def unique_basename(uploads_root: Path, base: str):
    hits = list(uploads_root.rglob(base))
    return hits[0] if len(hits) == 1 else None

def map_one(url: str, uploads_root: Path):
    url = fix_url(url)
    rel = rel_uploads_path(url)
    if rel:
        p = uploads_root / rel
        if p.exists():
            return p
    base = Path(urlparse(url).path).name.split("?")[0].split("#")[0]
    if base:
        hit = unique_basename(uploads_root, base)
        if hit and hit.exists():
            return hit
    return None

def process_cell(cell_val, user_id, uploads_root: Path, media_root: Path):
    if not nonempty(cell_val):
        return ""
    out = []
    parts = [x.strip() for x in MULTI_SPLIT.split(str(cell_val)) if nonempty(x)]
    for raw in parts:
        src = map_one(raw, uploads_root)
        if not src:
            continue
        h = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:12]
        dest = (media_root / f"user_{user_id}" / f"{h}_{src.name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(src.read_bytes())
        rel_out = Path("media") / dest.relative_to(media_root.parent)
        out.append(str(rel_out))
    # de-dup while preserving order
    seen, out2 = set(), []
    for p in out:
        if p not in seen:
            out2.append(p)
            seen.add(p)
    return ";".join(out2)

def open_csv_any(path: Path):
    # Try a few encodings to be resilient
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            f = open(path, newline="", encoding=enc)
            # Peek first char to ensure not empty
            pos = f.tell()
            first = f.read(1)
            f.seek(pos)
            if first == "":
                f.close()
                continue
            return f
        except UnicodeDecodeError:
            continue
    # final attempt (may still raise if truly empty)
    return open(path, newline="", encoding="utf-8")

def main():
    if len(sys.argv) < 5:
        print("Usage: python mirror_safe.py <INPUT_CSV> <OUTPUT_CSV> <UPLOADS_ROOT> <MEDIA_ROOT>")
        sys.exit(1)
    in_csv, out_csv, uploads, media = map(lambda p: Path(p).expanduser(), sys.argv[1:5])
    uploads_root = uploads
    media_root = media

    # Read input robustly
    with open_csv_any(in_csv) as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit(f"No columns detected in: {in_csv}")
        headers = [h or "" for h in reader.fieldnames]
        # Case-insensitive map
        def get_key(name):
            for h in headers:
                if h.lower() == name.lower():
                    return h
            return None

        uid_key  = get_key("user_id") or get_key("id") or get_key("uid")
        prof_key = get_key(PROFILE_COL) or PROFILE_COL
        addl_key = get_key(ADDITIONAL_COL) or ADDITIONAL_COL
        priv_key = get_key(PRIVATE_COL) or PRIVATE_COL
        if not uid_key:
            raise SystemExit("CSV must have a 'user_id' (or 'id'/'uid') column.")

        # Ensure output has at least these columns
        out_headers = list(headers)
        for must in [prof_key, addl_key, priv_key]:
            if must not in out_headers:
                out_headers.append(must)

        rows_out = []
        for row in reader:
            uid = row.get(uid_key, "").strip()
            if not uid:
                continue
            # promote a first image if profile_image is blank
            prof_val = row.get(prof_key, "")
            if not nonempty(prof_val):
                first = first_from(row.get(addl_key, "")) or first_from(row.get(priv_key, ""))
                if first:
                    row[prof_key] = first

            # map each image column to local paths
            for key in [prof_key, addl_key, priv_key]:
                if key in row:
                    row[key] = process_cell(row.get(key, ""), uid, uploads_root, media_root)

            rows_out.append(row)

    # Write output
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as g:
        writer = csv.DictWriter(g, fieldnames=out_headers)
        writer.writeheader()
        for r in rows_out:
            writer.writerow({h: r.get(h, "") for h in out_headers})
    print(f"Wrote: {out_csv}")

if __name__ == "__main__":
    main()
