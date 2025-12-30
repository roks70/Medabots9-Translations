import os, csv
from pathlib import Path

ENC = "cp932"

def has_japanese(s: str) -> bool:
    return any(
        ('\u3040' <= c <= '\u30ff') or ('\u4e00' <= c <= '\u9fff')
        for c in s
    )

root = Path(r"...\romfs\story\spt") # <-- change to your file location
tsv  = Path("M9-translations.csv") # <-- your filled TSV
out  = Path(r"...\Documents\test\spt")  # <-- output folder

out.mkdir(parents=True, exist_ok=True)

# Load JP->EN map
jp2en = {}
with tsv.open("r", encoding="utf-8", newline="") as f:
    r = csv.DictReader(f, delimiter=",")
    for row in r:
        jp = (row.get("jp") or "").strip()
        en = (row.get("en") or "").strip()
        if jp and en:
            # Avoid smart quotes etc that CP932 can't encode
            en = en.replace("“", '"').replace("”", '"').replace("’", "'")
            jp2en[jp] = en

updated_files = []

for fp in root.rglob("*.spt"):
    rel = fp.relative_to(root)
    out_fp = out / rel
    out_fp.parent.mkdir(parents=True, exist_ok=True)

    data = fp.read_bytes()
    parts = data.split(b"\x00")
    changed = False
    new_parts = []

    for seg in parts:
        if not seg:
            new_parts.append(seg)
            continue
        try:
            s = seg.decode(ENC)
        except Exception:
            new_parts.append(seg)
            continue

        if has_japanese(s) and s in jp2en:
            en_bytes = jp2en[s].encode(ENC, errors="strict")
            new_parts.append(en_bytes)
            changed = True
        else:
            new_parts.append(seg)

    out_fp.write_bytes(b"\x00".join(new_parts))
    if changed:
        updated_files.append(str(rel))

# Report
(out / "updated_files.txt").write_text("\n".join(updated_files), encoding="utf-8")
print(f"Done. Updated {len(updated_files)} files. Report: {out/'updated_files.txt'}")
