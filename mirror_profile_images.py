#!/usr/bin/env python3
import csv, hashlib, mimetypes, os, re, sys, time
from pathlib import Path
from urllib.parse import urlparse
import requests

# ---- Config (defaults) ----
PROFILE_COL = "profile_image"
ADDITIONAL_COL = "additional_images"
PRIVATE_COL = "private_images"
SEP = ";"  # delimiter for multi-image columns

def slugify(s):
    s = re.sub(r"[^\w.\-]+", "_", s.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "file"

def guess_ext(resp, url):
    # 1) From URL
    path = urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif"]:
        return ext
    # 2) From content-type
    ct = (resp.headers.get("Content-Type") or "").lower()
    for k, v in [("jpeg",".jpg"),("jpg",".jpg"),("png",".png"),("gif",".gif"),("webp",".webp"),("bmp",".bmp"),("avif",".avif")]:
        if k in ct:
            return v
    # 3) Fallback
    ext2 = mimetypes.guess_extension(ct.split(";")[0]) if ct else None
    return ext2 or ".jpg"

def fetch(url, dest_path, session, retries=2, timeout=20):
    for attempt in range(retries+1):
        try:
            with session.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                # sanity check: size & content-type
                ct = (r.headers.get("Content-Type") or "").lower()
                if "text/html" in ct:
                    raise ValueError(f"Not an image: {ct}")
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(1024 * 64):
                        if chunk:
                            f.write(chunk)
            return True
        except Exception as e:
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
            else:
                print(f"[WARN] Failed: {url} → {e}")
                return False

def process_cell(cell_val, user_id, media_root, cache, session):
    """Download and map one cell (may contain multiple URLs separated by SEP)."""
    if not cell_val or str(cell_val).strip().lower() in ["", "none", "nan"]:
        return ""
    urls = [u.strip() for u in str(cell_val).split(SEP) if u.strip()]
    out_local_paths = []
    for url in urls:
        # Skip non-http values
        if not url.lower().startswith(("http://", "https://")):
            # Keep as-is if already local path
            out_local_paths.append(url)
            continue

        # Cache by URL to avoid duplicate downloads
        if url in cache:
            out_local_paths.append(cache[url])
            continue

        # Build deterministic filename
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        base = slugify(os.path.basename(urlparse(url).path)) or f"img_{h}"
        # Remove any querystring suffixes in basename
        base = base.split("?")[0].split("#")[0]
        # temp ext (will correct after first request)
        tentative = Path(media_root, f"user_{user_id}", f"{h}_{base}")
        tentative.parent.mkdir(parents=True, exist_ok=True)

        # Probe and download
        try:
            r = session.get(url, stream=True, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"[WARN] HEAD/GET failed, skipping: {url} ({e})")
            continue

        ext = guess_ext(r, url)
        final_path = tentative.with_suffix(ext)
        # Reset stream (we already started a GET)
        ok = False
        try:
            # We already hold the response; write it
            ct = (r.headers.get("Content-Type") or "").lower()
            if "text/html" in ct:
                raise ValueError(f"Not an image: {ct}")
            with open(final_path, "wb") as f:
                for chunk in r.iter_content(1024 * 64):
                    if chunk:
                        f.write(chunk)
            ok = True
        except Exception as e:
            print(f"[WARN] Stream write failed for {url}: {e}")

        if not ok:
            # Try fresh GET
            ok = fetch(url, final_path, session)

        if ok:
            # Store as /media-relative path for Django
            rel = Path("media") / final_path.relative_to(Path(media_root).parent)
            cache[url] = str(rel)
            out_local_paths.append(str(rel))
        else:
            print(f"[WARN] Giving up on {url}")

    return SEP.join(out_local_paths)

def main():
    if len(sys.argv) < 4:
        print("Usage:\n  python mirror_profile_images.py <INPUT_CSV> <OUTPUT_CSV> <MEDIA_ROOT>\n")
        print("Example:\n  python mirror_profile_images.py "
              '"/Users/carlsng/Downloads/gr8date_profiles_with_images.csv" '
              '"/Users/carlsng/Downloads/gr8date_profiles_with_images_local.csv" '
              '"/Users/carlsng/Projects/gr8date/media/profiles"')
        sys.exit(1)

    input_csv  = Path(sys.argv[1]).expanduser()
    output_csv = Path(sys.argv[2]).expanduser()
    media_root = Path(sys.argv[3]).expanduser()

    import pandas as pd
    df = pd.read_csv(input_csv)

    # Column existence checks (be forgiving with case)
    cols = {c.lower(): c for c in df.columns}
    def get(name): return cols.get(name.lower())

    uid_col = get("user_id") or get("id") or get("uid")
    prof_col = get(PROFILE_COL) or PROFILE_COL
    addl_col = get(ADDITIONAL_COL) or ADDITIONAL_COL
    priv_col = get(PRIVATE_COL) or PRIVATE_COL

    for need in [uid_col]:
        if not need:
            raise SystemExit("CSV must have a user_id (or id/uid) column.")

    # Create media root (…/media/profiles)
    media_root.mkdir(parents=True, exist_ok=True)
    # We’ll produce /media/profiles/user_<id>/<hash>_name.ext paths in the CSV
    # (MEDIA_ROOT should be the folder '.../media/profiles')

    sess = requests.Session()
    cache = {}

    # Promote a profile image if missing (from additional/private first item)
    def first_from(cell):
        if not isinstance(cell, str): return ""
        return cell.split(SEP)[0].strip() if cell.strip() else ""

    if prof_col not in df.columns:
        df[prof_col] = ""

    for idx, row in df.iterrows():
        uid = row[uid_col]
        # Promote profile image if empty
        if not isinstance(row.get(prof_col), str) or not row.get(prof_col).strip():
            promoted = first_from(row.get(addl_col, "")) or first_from(row.get(priv_col, ""))
            df.at[idx, prof_col] = promoted

    # Now mirror each image column
    for col in [prof_col, addl_col, priv_col]:
        if col in df.columns:
            new_vals = []
            for idx, row in df.iterrows():
                new_vals.append(
                    process_cell(row.get(col, ""), row[uid_col], media_root, cache, sess)
                )
            df[col] = new_vals

    # Save the rewritten CSV
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"Done.\nCSV written to: {output_csv}\nMedia saved under: {media_root}")

if __name__ == "__main__":
    main()

