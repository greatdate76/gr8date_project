#!/usr/bin/env python3
import csv, hashlib, re, sys
from pathlib import Path
from typing import List, Dict

MULTI_SPLIT = re.compile(r"[;,]\s*")
UPLOADS_RE  = re.compile(r"/wp-content/uploads/(.+)$", re.IGNORECASE)

def nonempty(s): 
    return isinstance(s, str) and s.strip() and s.strip().lower() not in {"nan","none","null"}

def fix_url(u: str) -> str:
    if not isinstance(u, str): return ""
    u = u.strip()
    if u.startswith("https:/") and not u.startswith("https://"): u = u.replace("https:/","https://",1)
    if u.startswith("http:/")  and not u.startswith("http://"):  u = u.replace("http:/","http://",1)
    return u

def split_multi(val) -> List[str]:
    if not nonempty(val): return []
    return [x.strip() for x in MULTI_SPLIT.split(str(val)) if x.strip()]

def rel_uploads_path(url: str):
    m = UPLOADS_RE.search(url or "")
    return Path(m.group(1)) if m else None

def digest_file(p: Path) -> str:
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def unique_keep_order(items: List[str]) -> List[str]:
    seen = set(); out=[]
    for s in items:
        if s not in seen:
            seen.add(s); out.append(s)
    return out

def process_field(raw: str, uploads_root: Path):
    valids = []; missing=[]
    for part in split_multi(raw):
        u = fix_url(part)
        rel = rel_uploads_path(u)
        if not rel:
            maybe = uploads_root / part.lstrip("/")
            if maybe.exists():
                try:
                    rel2 = maybe.relative_to(uploads_root)
                    valids.append(str(rel2))
                except Exception:
                    missing.append(part)
            else:
                missing.append(part)
            continue
        candidate = uploads_root / rel
        if candidate.exists():
            valids.append(str(rel))
        else:
            missing.append(part)
    return unique_keep_order(valids), missing

def main():
    if len(sys.argv) < 4:
        print("Usage:\\n  python audit_and_clean_profiles.py <INPUT_CSV> <UPLOADS_ROOT> <OUT_DIR>")
        sys.exit(1)
    in_csv = Path(sys.argv[1]).expanduser()
    uploads_root = Path(sys.argv[2]).expanduser()
    out_dir = Path(sys.argv[3]).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(open(in_csv, newline="", encoding="utf-8")))
    headers = rows[0].keys() if rows else []

    cols = {c.lower(): c for c in headers}
    def getcol(*names):
        for n in names:
            if n and n.lower() in cols: return cols[n.lower()]
        return None

    uid_col   = getcol("user_id","uid","id")
    name_col  = getcol("username","display_name","name")
    prof_col  = getcol("profile_image")
    addl_col  = getcol("additional_images","additional")
    priv_col  = getcol("private_images","private")
    if not uid_col: raise SystemExit("CSV must contain a 'user_id' column.")

    cleaned_rows = []
    audit_rows   = []
    missing_rows = []
    cross_hash: Dict[str,List[str]] = {}

    for row in rows:
        uid = (row.get(uid_col) or "").strip()
        def handle(colname):
            raw = row.get(colname, "") if colname else ""
            return process_field(raw, uploads_root)

        prof_valid, prof_miss = handle(prof_col)
        addl_valid, addl_miss = handle(addl_col)
        priv_valid, priv_miss = handle(priv_col)

        if not prof_valid:
            if addl_valid:
                prof_valid = [addl_valid[0]]; addl_valid = addl_valid[1:]
            elif priv_valid:
                prof_valid = [priv_valid[0]]; priv_valid = priv_valid[1:]

        for rel in prof_valid + addl_valid + priv_valid:
            p = uploads_root / rel
            try:
                h = digest_file(p)
                cross_hash.setdefault(h, []).append(f"{uid}:{rel}")
            except Exception:
                pass

        new_row = dict(row)
        if prof_col: new_row[prof_col] = ";".join(prof_valid)
        if addl_col: new_row[addl_col] = ";".join(addl_valid)
        if priv_col: new_row[priv_col] = ";".join(priv_valid)
        cleaned_rows.append(new_row)

        audit_rows.append({
            "user_id": uid,
            "avatar_count": len(prof_valid),
            "additional_count": len(addl_valid),
            "private_count": len(priv_valid),
            "avatar_missing_items": len(prof_miss),
            "additional_missing_items": len(addl_miss),
            "private_missing_items": len(priv_miss),
            "any_missing": int(bool(prof_miss or addl_miss or priv_miss)),
        })

        for m in prof_miss: missing_rows.append({"user_id": uid, "field": "profile_image", "value": m})
        for m in addl_miss: missing_rows.append({"user_id": uid, "field": "additional_images", "value": m})
        for m in priv_miss: missing_rows.append({"user_id": uid, "field": "private_images", "value": m})

    cleaned_csv = out_dir / (in_csv.stem + "_CLEANED.csv")
    audit_csv   = out_dir / "audit_report_per_user.csv"
    missing_csv = out_dir / "missing_images.csv"
    dups_csv    = out_dir / "cross_user_duplicates.csv"

    with open(cleaned_csv, "w", newline="", encoding="utf-8") as g:
        w = csv.DictWriter(g, fieldnames=headers); w.writeheader(); w.writerows(cleaned_rows)

    with open(audit_csv, "w", newline="", encoding="utf-8") as g:
        w = csv.DictWriter(g, fieldnames=[
            "user_id","avatar_count","additional_count","private_count",
            "avatar_missing_items","additional_missing_items","private_missing_items","any_missing"
        ])
        w.writeheader(); w.writerows(audit_rows)

    with open(missing_csv, "w", newline="", encoding="utf-8") as g:
        import csv as _csv
        w = _csv.writer(g); w.writerow(["sha1","occurrences"])
        for m in missing_rows: pass  # no-op, just to keep similar structure
        # write missing list
    with open(missing_csv, "w", newline="", encoding="utf-8") as g:
        w = csv.DictWriter(g, fieldnames=["user_id","field","value"])
        w.writeheader(); w.writerows(missing_rows)

    with open(dups_csv, "w", newline="", encoding="utf-8") as g:
        import csv as _csv
        w = _csv.writer(g); w.writerow(["sha1","occurrences"])
        for sha1, lst in cross_hash.items():
            users = {x.split(":",1)[0] for x in lst}
            if len(users) > 1:
                w.writerow([sha1, "; ".join(lst)])

    print("Done.")
    print("Cleaned CSV:", cleaned_csv)
    print("Audit per user:", audit_csv)
    print("Missing list:", missing_csv)
    print("Cross-user duplicates:", dups_csv)

if __name__ == "__main__":
    main()
