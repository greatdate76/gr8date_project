#!/usr/bin/env python3
import csv, re, sys
from pathlib import Path

MULTI = re.compile(r"[;,]\s*")
UP_RE = re.compile(r"/wp-content/uploads/(.+)$", re.IGNORECASE)

def nonempty(s): return isinstance(s,str) and s.strip() and s.strip().lower() not in {"nan","none","null"}
def fix_url(u):
    if not isinstance(u,str): return ""
    u=u.strip()
    if u.startswith("https:/") and not u.startswith("https://"): u=u.replace("https:/","https://",1)
    if u.startswith("http:/")  and not u.startswith("http://"):  u=u.replace("http:/","http://",1)
    return u

def split_multi(v):
    if not nonempty(v): return []
    return [s.strip() for s in MULTI.split(str(v)) if s.strip()]

def rel_from_value(v):
    m = UP_RE.search(v or "")
    return m.group(1) if m else str(v).lstrip("/")

def strip_gf_face(name):
    n = re.sub(r"^face_[^_]+_(.+)$", r"\1", name)
    n = re.sub(r"^face_(.+)$", r"\1", n)
    return n

def find_unique_by_basename(uploads_root: Path, basename: str):
    hits = list(uploads_root.rglob(basename))
    return hits[0] if len(hits)==1 else None

def process_field(raw, uploads_root: Path):
    rels = []; missing=[]
    for p in split_multi(raw):
        p = fix_url(p)
        rel = rel_from_value(p)
        cand = (uploads_root / rel)
        if cand.exists():
            try:
                rel2 = cand.relative_to(uploads_root)
                rels.append(str(rel2)); continue
            except Exception:
                pass
        base = strip_gf_face(Path(rel).name)
        hit = find_unique_by_basename(uploads_root, base) if base else None
        if hit and hit.exists():
            rels.append(str(hit.relative_to(uploads_root)))
        else:
            missing.append(p)
    seen=set(); out=[]
    for s in rels:
        if s not in seen:
            seen.add(s); out.append(s)
    return out, missing

def main():
    if len(sys.argv)<5:
        print("Usage:\n  python remap_images_relaxed.py <INPUT_CSV> <OUTPUT_CSV> <UPLOADS_ROOT> <REPORT_DIR>")
        sys.exit(1)
    in_csv  = Path(sys.argv[1]).expanduser()
    out_csv = Path(sys.argv[2]).expanduser()
    uploads = Path(sys.argv[3]).expanduser()
    repdir  = Path(sys.argv[4]).expanduser(); repdir.mkdir(parents=True, exist_ok=True)

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

    out_rows=[]; miss=[]
    for row in rows:
        uid = (row.get(uid_col) or "").strip()

        def mapcol(col):
            if not col or col not in row: return []
            rels, missing = process_field(row[col], uploads)
            for m in missing: miss.append({"user_id":uid,"field":col,"value":m})
            return rels

        prof = mapcol(prof_col)
        addl = mapcol(addl_col)
        priv = mapcol(priv_col)

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

    print("Wrote:", out_csv)
    print("Missing (relaxed):", (repdir/"remap_relaxed_missing.csv"))
if __name__ == "__main__":
    main()
