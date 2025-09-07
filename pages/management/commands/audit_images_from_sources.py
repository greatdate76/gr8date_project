from django.core.management.base import BaseCommand
from django.conf import settings
from pathlib import Path
import csv, re, hashlib, sys
from collections import defaultdict

from pages.models import Profile, ProfileImage as PI

SEP = re.compile(r'[;,]\s*')
HEX_PREFIX = re.compile(r'^[0-9a-f]{8,16}_', re.IGNORECASE)

def split_multi(val):
    if val is None:
        return []
    s = str(val).strip()
    if not s or s.lower() in {"nan","none","null"}:
        return []
    return [p.strip() for p in SEP.split(s) if p.strip()]

def basename_from_url_or_path(p):
    try:
        p = str(p).split("?")[0].split("#")[0].strip()
        # url → take last segment
        if "://" in p:
            p = p.rsplit("/", 1)[-1]
        else:
            p = Path(p).name
        # when mirrored locally we prefix with a short hash → strip it
        p = HEX_PREFIX.sub("", p)
        return p
    except Exception:
        return ""

def file_sha1_under_media(rel_path):
    if not rel_path:
        return None
    p = Path(settings.MEDIA_ROOT) / rel_path
    if not p.exists() or not p.is_file():
        return None
    h = hashlib.sha1()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def load_expected_from_csv(csv_path):
    """
    Returns: dict[user_id] -> {
        'profile': set(basenames),
        'additional': set(basenames),
        'private': set(basenames),
        'all': set(basenames),
    }
    """
    expected = defaultdict(lambda: {"profile": set(), "additional": set(), "private": set(), "all": set()})
    cols_seen = set()

    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        hdr = [h.strip() for h in r.fieldnames or []]
        cols_seen.update(hdr)

        # Column guessing
        has_images_combo = "images" in r.fieldnames
        prof_col = next((c for c in r.fieldnames if c and c.lower() == "profile_image"), None)
        addl_col = next((c for c in r.fieldnames if c and c.lower() == "additional_images"), None)
        priv_col = next((c for c in r.fieldnames if c and c.lower() == "private_images"), None)
        uid_col  = next((c for c in r.fieldnames if c and c.lower() in {"user_id","id","uid"}), None)

        for row in r:
            try:
                uid = row.get(uid_col) if uid_col else None
                if uid is None:
                    continue
                uid = int(float(uid))
            except Exception:
                continue

            if has_images_combo:
                for part in split_multi(row.get("images")):
                    bn = basename_from_url_or_path(part)
                    if bn:
                        expected[uid]["additional"].add(bn)  # treat “images” as additional by default
                        expected[uid]["all"].add(bn)

            if prof_col:
                for part in split_multi(row.get(prof_col)):
                    bn = basename_from_url_or_path(part)
                    if bn:
                        expected[uid]["profile"].add(bn)
                        expected[uid]["all"].add(bn)

            if addl_col:
                for part in split_multi(row.get(addl_col)):
                    bn = basename_from_url_or_path(part)
                    if bn:
                        expected[uid]["additional"].add(bn)
                        expected[uid]["all"].add(bn)

            if priv_col:
                for part in split_multi(row.get(priv_col)):
                    bn = basename_from_url_or_path(part)
                    if bn:
                        expected[uid]["private"].add(bn)
                        expected[uid]["all"].add(bn)

    return expected, cols_seen

class Command(BaseCommand):
    help = (
        "Audit current DB profile images against one or more CSV sources.\n"
        "Compares by image basename (hash prefixes stripped). Writes CSV reports."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv", action="append", required=True,
            help="Path to a source CSV. Repeat --csv to include multiple sources (order does not matter)."
        )
        parser.add_argument(
            "--out", required=True,
            help="Output directory for reports (will be created)."
        )

    def handle(self, *args, **opts):
        out_dir = Path(opts["out"]).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)

        # 1) Build expected sets from all CSVs
        grand_expected = defaultdict(lambda: {"profile": set(), "additional": set(), "private": set(), "all": set()})
        all_cols = set()

        for csv_path in opts["csv"]:
            exp, cols = load_expected_from_csv(Path(csv_path).expanduser())
            all_cols |= set(cols)
            for uid, buckets in exp.items():
                for k in ("profile","additional","private","all"):
                    grand_expected[uid][k] |= buckets[k]

        # 2) Build current sets from DB
        current_basenames = defaultdict(lambda: {"profile": set(), "additional": set(), "private": set(), "all": set()})
        sha_map = defaultdict(list)  # sha1 -> [(user_id, kind, rel)]

        for p in Profile.objects.all().iterator():
            # primary (avatar) → treat as 'profile'
            if p.primary_image and p.primary_image.name:
                rel = p.primary_image.name
                bn = basename_from_url_or_path(rel)
                if bn:
                    current_basenames[p.user_id]["profile"].add(bn)
                    current_basenames[p.user_id]["all"].add(bn)
                    sh = file_sha1_under_media(rel)
                    if sh:
                        sha_map[sh].append((p.user_id, "primary", rel))

            # gallery
            for img in p.images.all():
                rel = (img.image.name or "").strip()
                if not rel:
                    continue
                bn = basename_from_url_or_path(rel)
                if not bn:
                    continue

                kind = img.kind
                if kind == PI.PUBLIC:
                    bucket = "profile"  # PUBLIC pos=0 is effectively hero; but we record too
                elif kind == PI.ADDITIONAL:
                    bucket = "additional"
                else:
                    bucket = "private"

                current_basenames[p.user_id][bucket].add(bn)
                current_basenames[p.user_id]["all"].add(bn)

                sh = file_sha1_under_media(rel)
                if sh:
                    sha_map[sh].append((p.user_id, bucket, rel))

        # 3) Compare and emit reports
        unexpected_rows = []
        missing_rows = []

        all_user_ids = set(grand_expected.keys()) | set(current_basenames.keys())

        for uid in sorted(all_user_ids):
            exp_all = grand_expected[uid]["all"]
            cur_all = current_basenames[uid]["all"]

            # unexpected in DB (not expected by any CSV)
            for bn in sorted(cur_all - exp_all):
                unexpected_rows.append({"user_id": uid, "basename": bn})

            # missing (expected by CSVs but not present in DB)
            for bn in sorted(exp_all - cur_all):
                missing_rows.append({"user_id": uid, "basename": bn})

        # Cross-user collisions by hash (same file used by different users)
        cross_user = []
        for sh, uses in sha_map.items():
            users = sorted({u for (u, _, _) in uses})
            if len(users) > 1:
                for u, kind, rel in uses:
                    cross_user.append({
                        "sha1": sh, "user_id": u, "kind": kind, "rel": rel
                    })

        # 4) Write CSVs
        def write_csv(path, rows, fieldnames):
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                for r in rows:
                    w.writerow(r)

        write_csv(out_dir / "unexpected_current.csv", unexpected_rows, ["user_id","basename"])
        write_csv(out_dir / "missing_expected.csv", missing_rows, ["user_id","basename"])
        write_csv(out_dir / "cross_user_collisions.csv", cross_user, ["sha1","user_id","kind","rel"])

        # 5) Summary
        summary = (
            f"CSV columns seen: {sorted(all_cols)}\n"
            f"Users in expected: {len(grand_expected)}\n"
            f"Users in DB: {len(current_basenames)}\n"
            f"Unexpected in DB (rows): {len(unexpected_rows)}\n"
            f"Missing from DB (rows): {len(missing_rows)}\n"
            f"Cross-user identical-file collisions (rows): {len(cross_user)}\n"
        )
        (out_dir / "summary.txt").write_text(summary, encoding="utf-8")

        self.stdout.write(self.style.SUCCESS("Audit complete.\n" + summary))

