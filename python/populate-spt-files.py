from pathlib import Path
import csv
import os

ENC = "cp932"

#use full paths "C:\blahbalh\downloads\...\story\spt"
root = Path(r"...\story\spt") #original M9 story/spt .spt files
out  = Path(r"...\spt-out") #output path
csv_path = Path(r"...\M9-translations-initial.csv") #translation .csv file

out.mkdir(parents=True, exist_ok=True)

# Load replacements grouped by file_rel
repls = {}  # file_rel -> list of (part_index, en)
with csv_path.open("r", encoding="utf-8", newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        file_rel = row["file_rel"].strip()
        part_index = int(row["part_index"])
        en = (row["en"] or "").strip()
        if not file_rel or not en:
            continue
        repls.setdefault(file_rel, []).append((part_index, en))

updated = []
missing = []

for file_rel, items in repls.items():
    src = root / file_rel
    if not src.exists():
        missing.append(file_rel)
        continue

    data = src.read_bytes()
    parts = data.split(b"\x00")

    changed = False
    for part_index, en in items:
        if 0 <= part_index < len(parts):
            parts[part_index] = en.encode(ENC, errors="strict")
            changed = True

    if changed:
        dst = out / file_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"\x00".join(parts))
        updated.append(file_rel)

(out / "updated_files.txt").write_text("\n".join(updated), encoding="utf-8")
(out / "missing_files.txt").write_text("\n".join(missing), encoding="utf-8")

print(f"Updated: {len(updated)}")
print(f"Missing: {len(missing)}")
print(f"Output: {out}")
