#!/usr/bin/env python3
"""
Rebuild a master CSV by merging three sources and mirroring images from uploads:

SOURCES (any can be omitted if not available):
- A: gr8date_profiles_full_local.csv (bios + extras + some image urls/paths)
- B: combined_profiles_split_images.csv (more image urls)
- C: WordPress: wp_posts.csv (attachments) + wp_postmeta.csv (_wp_attached_file)

OUTPUTS (under OUT_DIR):
- gr8_master.csv                 -> final CSV for Django importer
- missing_images.csv             -> rows we couldn't resolve to a local file
- duplicate_images_removed.csv   -> per-user list of removed duplicates
- per_user_summary.csv           -> counts per user (public/additional/private)
"""
import argparse, csv, hashlib, os, re, sys, time, mimetypes
from pathlib import Path
from urllib.parse import urlparse

try:
    import pandas as pd
except Exception:
    print("This script needs pandas: pip install pandas")
    raise

URL_RE = re.compile(r'^https?://', re.I)
MULTI_SPLIT = re.compile(r'[;,]\s*')

def nonempty(x): 
    return isinstance(x, str) and x.strip() and x.strip().lower() not in {"none","null","nan"}

def clean(x): 
    return x.strip() if isinstance(x, str) else x

def is_url(s): 
    return bool(URL_RE.match(str(s or "")))

def fix_url(u: str) -> str:
    if not isinstance(u, str): return ""
    u = u.strip()
    if u.startswith("https:/") and not u.startswith("https://"): u = u.replace("https:/","https://",1)
    if u.startswith("http:/")  and not u.startswith("http://"):  u = u.replace("http:/","http://",1)
    return u

def split_multi(cell):
    if not nonempty(cell): return []
    return [s for s in MULTI_SPLIT.split(cell) if s.strip()]

def to_int(x):
    try: return int(float(str(x).strip()))
    except Exception: return None

def rel_from_url(u):
    try: p = urlparse(u).path
    except Exception: return None
    m = re.search(r"/wp-content/uploads/(.+)$", p, re.I)
    return Path(m.group(1)) if m else None

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

def slug(s):
    s = re.sub(r"[^\w.\-]+", "_", s).strip("_")
    s = re.sub(r"_+", "_", s)
    return s or "file"

def guess_ext_from_ct(ct: str) -> str:
    ct = (ct or "").lower().split(";")[0]
    if "jpeg" in ct or "jpg" in ct: return ".jpg"
    if "png" in ct: return ".png"
    if "gif" in ct: return ".gif"
    if "webp" in ct: return ".webp"
    if "bmp" in ct: return ".bmp"
    if "avif" in ct: return ".avif"
    return mimetypes.guess_extension(ct) or ".jpg"

def load_csv(path: Path) -> "pd.DataFrame":
    if not path or not Path(path).exists(): return pd.DataFrame()
    return pd.read_csv(path)

def build_wp_attachment_maps(wp_posts: "pd.DataFrame", wp_postmeta: "pd.DataFrame"):
    """
    Build:
      - post_id -> relative uploads path (from _wp_attached_file)
      - post_id -> guid URL (from posts.guid)
      - author_id -> [post_id, ...] for attachments authored by that user

    Works even if 'post_type' is missing; falls back to post_mime_type or treats all rows as attachments.
    """
    if wp_posts is None or wp_posts.empty:
        return {}, {}, {}

    # columns already lowercased by norm_df()
    cols = set(wp_posts.columns)

    # Identify attachment rows robustly
    if "post_type" in cols:
        attach = wp_posts[wp_posts["post_type"].astype(str).str.lower() == "attachment"].copy()
    elif "post_mime_type" in cols:
        # attachments usually have a non-empty mime type
        attach = wp_posts[wp_posts["post_mime_type"].astype(str).str.strip() != ""].copy()
    else:
        # last resort: assume the whole file is attachments
        attach = wp_posts.copy()

    # Key column names (ID vs id, post_author vs author)
    id_col = "id" if "id" in cols else ("ID" if "ID" in wp_posts.columns else None)
    if id_col is None:
        # take the first column as fallback id
        id_col = attach.columns[0]

    author_col = "post_author" if "post_author" in cols else ("author" if "author" in cols else None)
    guid_col = "guid" if "guid" in cols else None

    # Map post_id -> guid
    post_to_guid = {}
    if guid_col in attach.columns and id_col in attach.columns:
        for _, r in attach.iterrows():
            pid = to_int(r.get(id_col))
            g = clean(r.get(guid_col) or "")
            if pid is not None and g:
                post_to_guid[pid] = g

    # Map post_id -> _wp_attached_file (relative path)
    post_to_rel = {}
    if wp_postmeta is not None and not wp_postmeta.empty:
        wpm = wp_postmeta.copy()
        wpm.columns = [c.strip().lower() for c in wpm.columns]
        pid_col = "post_id" if "post_id" in wpm.columns else ("id" if "id" in wpm.columns else None)
        if pid_col:
            for _, r in wpm.iterrows():
                if str(r.get("meta_key", "")).strip() == "_wp_attached_file":
                    pid = to_int(r.get(pid_col))
                    mv = clean(r.get("meta_value") or "")
                    if pid is not None and mv:
                        post_to_rel[pid] = mv

    # Map author_id -> [attachment post ids]
    author_to_posts = {}
    if id_col in attach.columns and author_col in attach.columns:
        for _, r in attach.iterrows():
            pid = to_int(r.get(id_col))
            aid = to_int(r.get(author_col))
            if pid is None or aid is None:
                continue
            author_to_posts.setdefault(aid, []).append(pid)

    return post_to_rel, post_to_guid, author_to_posts

def mirror_from_uploads_or_web(urls_or_paths, user_id, uploads_root: Path, media_root: Path, web_fallback=False):
    out = []
    for raw in urls_or_paths:
        if not nonempty(raw): continue
        raw = fix_url(raw)

        # Already local media path?
        if not is_url(raw) and raw.startswith(("media/","profiles/")):
            p = raw.split("media/",1)[-1] if raw.startswith("media/") else raw
            out.append(p); continue

        # Try locate in uploads
        rel = None
        if is_url(raw):
            rel = rel_from_url(raw)
        else:
            if "wp-content/uploads/" in raw:
                rel = Path(raw.split("wp-content/uploads/",1)[-1])
            else:
                parts = Path(raw)
                if len(parts.parts) >= 3:
                    rel = parts

        src = (uploads_root / rel) if rel else None
        if src and src.exists():
            base = slug(src.name); h = sha1(str(raw))
            dest = media_root / f"user_{user_id}" / f"{h}_{base}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
            relp = str(dest.relative_to(media_root.parent))
            out.append(relp[len("media/"):] if relp.startswith("media/") else relp)
            continue

        if web_fallback and is_url(raw):
            try:
                import requests
                with requests.get(raw, stream=True, timeout=20) as r:
                    r.raise_for_status()
                    ct = r.headers.get("Content-Type","")
                    ext = guess_ext_from_ct(ct)
                    base = slug(Path(urlparse(raw).path).name) or ("img"+ext)
                    if "." not in base: base += ext
                    h = sha1(str(raw))
                    dest = media_root / f"user_{user_id}" / f"{h}_{base}"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with open(dest, "wb") as f:
                        for chunk in r.iter_content(1024*64):
                            if chunk: f.write(chunk)
                relp = str(dest.relative_to(media_root.parent))
                out.append(relp[len("media/"):] if relp.startswith("media/") else relp)
            except Exception:
                pass
    # de-dup keep order
    seen=set(); uniq=[]
    for p in out:
        if p not in seen:
            seen.add(p); uniq.append(p)
    return uniq

def norm_df(df):
    if df.empty: return df
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    return df

def idx_by_uid(df):
    """Return {user_id: dict(row)} for easy/robust lookups (no pandas.Series truthiness)."""
    if df.empty or "user_id" not in df.columns:
        return {}
    d = {}
    for _, r in df.iterrows():
        uid = to_int(r.get("user_id"))
        if uid is None:
            continue
        d[uid] = {k: r.get(k) for k in df.columns}
    return d

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-a", help="gr8date_profiles_full_local.csv")
    ap.add_argument("--csv-b", help="combined_profiles_split_images.csv")
    ap.add_argument("--wp-posts", help="wp_posts.csv")
    ap.add_argument("--wp-postmeta", help="wp_postmeta.csv")
    ap.add_argument("--uploads", required=True)
    ap.add_argument("--media", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--web-fallback", action="store_true")
    args = ap.parse_args()

    uploads = Path(args.uploads).expanduser()
    media   = Path(args.media).expanduser()
    outdir  = Path(args.out).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    A = norm_df(load_csv(Path(args.csv_a))) if args.csv_a else pd.DataFrame()
    B = norm_df(load_csv(Path(args.csv_b))) if args.csv_b else pd.DataFrame()
    WP = norm_df(load_csv(Path(args.wp_posts))) if args.wp_posts else pd.DataFrame()
    WPM = norm_df(load_csv(Path(args.wp_postmeta))) if args.wp_postmeta else pd.DataFrame()

    post_to_rel, post_to_guid, author_to_posts = build_wp_attachment_maps(WP, WPM)

    def gather(row_dict, col):
        if not row_dict: return []
        v = row_dict.get(col)
        return split_multi(str(v)) if nonempty(str(v or "")) else []

    Aidx, Bidx = idx_by_uid(A), idx_by_uid(B)
    uids = set(Aidx.keys()) | set(Bidx.keys()) | set(author_to_posts.keys())

    master_rows=[]; missing_rows=[]; dup_removed=[]; per_user_summary=[]

    def gv(row, key):
        """Get cleaned string value from a dict row or ''."""
        if not row:
            return ""
        v = row.get(key)
        return v.strip() if isinstance(v, str) else (str(v).strip() if v is not None else "")

    def gi(row, key):
        """Get int from a dict row or None."""
        if not row:
            return None
        return to_int(row.get(key))

    for uid in sorted(uids):
        a = Aidx.get(uid)  # dict or None
        b = Bidx.get(uid)  # dict or None

        username = gv(a, "username") or gv(b, "username")
        display_name = (gv(a, "display_name") or username).strip()
        age = gi(a, "age") or gi(b, "age")
        gender = (gv(a, "gender") or gv(b, "gender")).strip()
        location = (gv(a, "location") or gv(b, "location")).strip()

        bio = (gv(a, "description") or gv(a, "bio") or gv(b, "description") or gv(b, "bio")).strip()

        extras = {
            "heading": (gv(a, "heading") or gv(b, "heading")).strip(),
            "seeking": (gv(a, "seeking") or gv(b, "seeking")).strip(),
            "relationship_status": (gv(a, "relationship_status") or gv(b, "relationship_status")).strip(),
            "body_type": (gv(a, "body_type") or gv(b, "body_type")).strip(),
            "children": (gv(a, "children") or gv(b, "children")).strip(),
            "smoker": (gv(a, "smoker") or gv(b, "smoker")).strip(),
            "height": (gv(a, "height") or gv(b, "height")).strip(),
        }

        # Collect images from A/B
        a_prof = gather(a, "profile_image"); b_prof = gather(b, "profile_image")
        raw_public = []
        if a_prof: raw_public.append(a_prof[0])
        elif b_prof: raw_public.append(b_prof[0])

        raw_additional = []
        raw_additional += (a_prof[1:] if len(a_prof)>1 else [])
        raw_additional += (b_prof[1:] if len(b_prof)>1 else [])
        raw_additional += gather(a, "additional_images") + gather(b, "additional_images")
        raw_private = gather(a, "private_images") + gather(b, "private_images")

        # WP attachments as additional (by author/user id)
        wp_urls=[]
        for pid in author_to_posts.get(uid, []) or []:
            rel = post_to_rel.get(pid)
            if rel: wp_urls.append(f"/wp-content/uploads/{rel}")
            else:
                g = post_to_guid.get(pid)
                if g: wp_urls.append(g)
        raw_additional += wp_urls

        # Mirror into media
        public_media = mirror_from_uploads_or_web(raw_public, uid, uploads, media, web_fallback=args.web_fallback)
        additional_media = mirror_from_uploads_or_web(raw_additional, uid, uploads, media, web_fallback=args.web_fallback)
        private_media = mirror_from_uploads_or_web(raw_private, uid, uploads, media, web_fallback=args.web_fallback)

        # de-dup while preserving order
        def dedup(seq):
            seen=set(); out=[]
            for p in seq:
                if p and p not in seen:
                    seen.add(p); out.append(p)
            return out
        public_media = dedup(public_media)
        additional_media = dedup(additional_media)
        private_media = dedup(private_media)

        # remove avatar from additional (avoid duplicates like user 1585)
        if public_media:
            avatar = public_media[0]
            before = len(additional_media)
            additional_media = [x for x in additional_media if x != avatar]
            if len(additional_media) < before:
                dup_removed.append({"user_id": uid, "removed_count": before-len(additional_media), "reason": "avatar_in_additional"})

        # track missings (heuristic comparison by basename)
        def unresolved(raw_list, mirrored_list):
            mset = set(mirrored_list); miss=[]
            for r in raw_list:
                base = os.path.basename(urlparse(r).path if is_url(r) else str(r))
                if not base: continue
                if not any(os.path.basename(x).endswith(base) for x in mset):
                    miss.append(r)
            return miss

        for itm in unresolved(raw_public, public_media):
            missing_rows.append({"user_id": uid, "column": "profile_image", "value": itm})
        for itm in unresolved(raw_additional, additional_media):
            missing_rows.append({"user_id": uid, "column": "additional_images", "value": itm})
        for itm in unresolved(raw_private, private_media):
            missing_rows.append({"user_id": uid, "column": "private_images", "value": itm})

        master_rows.append({
            "user_id": uid,
            "username": username,
            "display_name": display_name,
            "age": age,
            "gender": gender,
            "location": location,
            "bio": bio or "",
            "heading": extras["heading"],
            "seeking": extras["seeking"],
            "relationship_status": extras["relationship_status"],
            "body_type": extras["body_type"],
            "children": extras["children"],
            "smoker": extras["smoker"],
            "height": extras["height"],
            "profile_image": ";".join(public_media[:1]),
            "additional_images": ";".join(additional_media),
            "private_images": ";".join(private_media),
        })

        per_user_summary.append({
            "user_id": uid,
            "has_avatar": 1 if public_media else 0,
            "public_count": len(public_media),
            "additional_count": len(additional_media),
            "private_count": len(private_media),
        })

    # write outputs
    outdir = Path(args.out).expanduser()
    master_cols = ["user_id","username","display_name","age","gender","location",
                   "bio","heading","seeking","relationship_status","body_type","children","smoker","height",
                   "profile_image","additional_images","private_images"]

    pd.DataFrame(master_rows, columns=master_cols).to_csv(outdir / "gr8_master.csv", index=False)
    pd.DataFrame(missing_rows).to_csv(outdir / "missing_images.csv", index=False)
    pd.DataFrame(dup_removed).to_csv(outdir / "duplicate_images_removed.csv", index=False)
    pd.DataFrame(per_user_summary).to_csv(outdir / "per_user_summary.csv", index=False)

    dfm = pd.DataFrame(master_rows)
    print("Done.")
    print("Master CSV:", outdir / "gr8_master.csv")
    print("Missing images list:", outdir / "missing_images.csv", f"({len(missing_rows)} rows)")
    print("Duplicates removed log:", outdir / "duplicate_images_removed.csv")
    print("Per-user summary:", outdir / "per_user_summary.csv")
    print("---")
    if not dfm.empty:
        print("Users total:", len(dfm))
        print("With avatar:", (dfm["profile_image"].fillna("").str.len()>0).sum())
        print("With additional:", (dfm["additional_images"].fillna("").str.len()>0).sum())
        print("With private:", (dfm["private_images"].fillna("").str.len()>0).sum())

if __name__ == "__main__":
    main()

