#!/usr/bin/env python3
"""
translate_spt_deepl.py (with persistent replacement CSV)

- Extract JP strings from .spt (0x00-separated CP932 strings)
- Group dialogue lines for contextual translation (DeepL) but preserve 1:1 reinsertion using XML tags
- Translate label-style strings line-by-line (safe reinsertion)
- Dedupe requests (do NOT send same JP to DeepL repeatedly)
- Persist translations immediately to a CSV so you can resume/apply later if the script crashes
- Write updated .spt files as you go (per-file), only if changed

Requirements:
  pip install requests
"""

import argparse
import unicodedata
import csv
import hashlib
import html
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

ENC = "cp932"

MESSAGE_TOKENS = {"message", "\rmessage"}
MBOX_TOKENS = {"mbox0", "mbox1", "mbox2", "mbox3"}
BREAK_TOKENS = {"CLOSE_MESS0", "CLOSE_MESSWIN0", "\rmboxclear0", "mboxclear0"}
OPEN_NAME_PREFIX = "OPEN_NAME"

_TAG_RE = re.compile(r"<l(\d+)>(.*?)</l\1>", re.DOTALL)

NAME_LIKE_RE = re.compile(
    r"""^(
        [\u3040-\u30ff\u4e00-\u9fff]+[0-9]*  # kana/kanji + optional digits
        |[A-Za-z0-9_]+                       # ascii id-like
        )$""",
    re.VERBOSE
)


def has_japanese(s: str) -> bool:
    return any(
        ("\u3040" <= c <= "\u30ff") or ("\u4e00" <= c <= "\u9fff")
        for c in s
    )


def sanitize_for_cp932(s: str) -> str:
    return (
        s.replace("¥", "Y")
         .replace("·", "-")
         .replace("“", '"')
         .replace("”", '"')
         .replace("‘", "'")
         .replace("’", "'")
         .replace("—", "-")
         .replace("–", "-")
         .replace("…", "...")
         .replace("\u00a0", " ")
    )

def strip_macrons(s: str) -> str:
    table = str.maketrans({
        "Ā":"A", "ā":"a",
        "Ē":"E", "ē":"e",
        "Ī":"I", "ī":"i",
        "Ō":"O", "ō":"o",
        "Ū":"U", "ū":"u",
    })
    return s.translate(table)

def strip_accents(s: str) -> str:
    # Normalize to decomposed form, then drop combining marks
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(ch)
    )

def norm_path_str(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def deepl_api_url_from_key(auth_key: str) -> str:
    return "https://api-free.deepl.com/v2/translate" if auth_key.endswith(":fx") else "https://api.deepl.com/v2/translate"


@dataclass
class Block:
    file_path: Path
    line_indices: List[int]       # indices into 0x00 split parts
    jp_lines: List[str]           # original JP lines in order
    kind: str                     # 'dialogue' or 'label'
    speaker_hint: Optional[str] = None


def load_ignore_set(ignore_file: Optional[Path]) -> set:
    if not ignore_file:
        return set()
    ignore = set()
    with ignore_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip().strip('"')
            if s:
                ignore.add(norm_path_str(s))
    return ignore


def decode_parts(data: bytes) -> List[Optional[str]]:
    parts = data.split(b"\x00")
    decoded: List[Optional[str]] = []
    for seg in parts:
        if not seg:
            decoded.append("")
            continue
        try:
            decoded.append(seg.decode(ENC))
        except Exception:
            decoded.append(None)
    return decoded

def is_doll_arg(decoded, i, lookback=4) -> bool:
    """Return True if token i looks like it's part of a doll* command argument list."""
    j = i - 1
    steps = 0
    while j >= 0 and steps < lookback:
        t = decoded[j]
        j -= 1

        if not isinstance(t, str) or t == "":
            continue

        tn = t.lstrip("\r").strip().lower()

        # If we hit a boundary command, stop looking (this JP token is not doll-related)
        if tn in ("message", "\rmessage", "gosub") or tn.startswith("open_name") or tn in (
            "close_mess0", "close_messwin0", "mboxclear0", "\rmboxclear0"
        ):
            return False

        # If we see a doll* command recently, treat current JP token as a doll arg
        if tn.startswith("doll"):
            return True

        steps += 1

    return False

def extract_blocks_for_file(fp: Path, decoded: List[Optional[str]], max_dialogue_chars: int) -> List[Block]:
    blocks: List[Block] = []
    current_speaker: Optional[str] = None

    dlg_indices: List[int] = []
    dlg_lines: List[str] = []
    dlg_char_count = 0

    def flush_dialogue():
        nonlocal dlg_indices, dlg_lines, dlg_char_count, current_speaker
        if dlg_indices:
            blocks.append(Block(
                file_path=fp,
                line_indices=dlg_indices,
                jp_lines=dlg_lines,
                kind="dialogue",
                speaker_hint=current_speaker
            ))
        dlg_indices, dlg_lines, dlg_char_count = [], [], 0

    i = 0
    while i < len(decoded):
        tok = decoded[i]
        if tok is None or tok == "":
            i += 1
            continue

        if tok.startswith(OPEN_NAME_PREFIX):
            # OPEN_NAME0 / OPEN_NAME1 ... next token is the displayed speaker name
            if i + 1 < len(decoded) and isinstance(decoded[i + 1], str):
                name = decoded[i + 1]
                if name and has_japanese(name):
                    current_speaker = name
                    blocks.append(Block(fp, [i + 1], [name], kind="label", speaker_hint=None))
            i += 2  # consume OPEN_NAME* + its name token
            continue

        if tok in BREAK_TOKENS:
            flush_dialogue()
            i += 1
            continue

        if tok in MESSAGE_TOKENS:
            if i + 2 < len(decoded):
                mbox = decoded[i + 1]
                jp = decoded[i + 2]
                if mbox in MBOX_TOKENS and isinstance(jp, str) and jp and has_japanese(jp):
                    if dlg_char_count + len(jp) > max_dialogue_chars:
                        flush_dialogue()
                    dlg_indices.append(i + 2)
                    dlg_lines.append(jp)
                    dlg_char_count += len(jp)
                    i += 3
                    continue

        i += 1

    flush_dialogue()
    return blocks


def blocks_to_deepl_text(block: Block) -> str:
    lines = []
    for idx, jp in enumerate(block.jp_lines):
        esc = html.escape(jp, quote=False)
        lines.append(f"<l{idx}>{esc}</l{idx}>")
    return "\n".join(lines)


def parse_deepl_xml_output(xml_text: str, expected_lines: int) -> List[str]:
    matches = _TAG_RE.findall(xml_text)
    out = [""] * expected_lines
    for idx_str, content in matches:
        idx = int(idx_str)
        if 0 <= idx < expected_lines:
            out[idx] = html.unescape(content).strip()
    return out

def load_done_set(replacements_csv: Path) -> set[tuple[str, int]]:
    done = set()
    if not replacements_csv.exists():
        return done
    with replacements_csv.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                done.add((row["file_rel"], int(row["part_index"])))
            except Exception:
                pass
    return done

class DeepLTranslator:
    def __init__(
        self,
        auth_key: str,
        api_url: Optional[str] = None,
        source_lang: str = "JA",
        target_lang: str = "EN",
        split_sentences: str = "nonewlines",
        preserve_formatting: int = 1,
        tag_handling: str = "xml",
        request_timeout: int = 60,
        sleep_between: float = 0.5,
        max_retries: int = 8,
    ):
        self.auth_key = auth_key
        self.api_url = api_url or deepl_api_url_from_key(auth_key)
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.split_sentences = split_sentences
        self.preserve_formatting = preserve_formatting
        self.tag_handling = tag_handling
        self.request_timeout = request_timeout
        self.sleep_between = sleep_between
        self.max_retries = max_retries

    def translate_texts(self, texts: List[str]) -> List[str]:
        if not texts:
            return []

        base = {
            "auth_key": self.auth_key,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "split_sentences": self.split_sentences,
            "preserve_formatting": str(self.preserve_formatting),
            "tag_handling": self.tag_handling,
        }

        payload = list(base.items())
        for t in texts:
            payload.append(("text", t))

        backoff = 1.0
        for _attempt in range(self.max_retries):
            resp = requests.post(self.api_url, data=payload, timeout=self.request_timeout)
            if resp.status_code == 200:
                j = resp.json()
                out = [item.get("text", "") for item in j.get("translations", [])]
                if self.sleep_between > 0:
                    time.sleep(self.sleep_between)
                return out

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait_s = float(retry_after) if (retry_after and retry_after.isdigit()) else backoff
                time.sleep(wait_s)
                backoff = min(backoff * 2, 60.0)
                continue

            raise RuntimeError(f"DeepL HTTP {resp.status_code}: {resp.text[:500]}")

        raise RuntimeError("DeepL HTTP 429: exceeded retries (still rate-limited).")


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def ensure_csv_header(path: Path, header: List[str]) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)


def append_rows(path: Path, rows: List[Tuple]) -> None:
    if not rows:
        return
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerows(rows)
        f.flush()
        os.fsync(f.fileno())


def main():
    ap = argparse.ArgumentParser()

    # Defaults are safe; remove required=True so you can run without args
    ap.add_argument("--root", type=Path, default=Path(r"...\ExtractedRomFS\story\spt"))
    ap.add_argument("--out", type=Path, default=Path(r"...\Downloads\spt"))
    ap.add_argument("--auth-key", type=str, default="key-here")
    ap.add_argument("--ignore-file", type=Path, default=Path(r"...\Downloads\ignore-list.txt"))
    ap.add_argument("--api-url", type=str, default="")
    ap.add_argument("--max-dialogue-chars", type=int, default=2000)
    ap.add_argument("--batch-size", type=int, default=50)
    ap.add_argument("--cache-json", type=Path, default=Path(r"...\Downloads\deepl_cache.json"))
    ap.add_argument("--encoding-errors", choices=["strict", "replace"], default="strict")
    ap.add_argument("--skip-name-like-labels", action="store_true")

    # NEW: Persist replacements continuously
    ap.add_argument(
        "--replacements-csv",
        type=Path,
        default=Path(r"...\Downloads\translations_replacements.csv"),
        help="Append-safe CSV storing file_rel,part_index,kind,speaker,jp,en"
    )

    # NEW: Option if you ONLY want the CSV and NOT to write .spt outputs this run
    ap.add_argument("--translate-only", default="--translate-only", action="store_true", help="Translate + write replacements CSV, but do not write .spt output files.")

    args = ap.parse_args()

    if not args.auth_key:
        raise SystemExit("Missing DeepL key. Provide --auth-key or set DEEPL_AUTH_KEY.")

    args.out.mkdir(parents=True, exist_ok=True)
    ensure_csv_header(args.replacements_csv, ["file_rel", "part_index", "kind", "speaker", "jp", "en"])
    done_set = load_done_set(args.replacements_csv)
    ignore_set = load_ignore_set(args.ignore_file)

    cache: Dict[str, List[str]] = {}
    if args.cache_json and args.cache_json.exists():
        try:
            cache = json.loads(args.cache_json.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    translator = DeepLTranslator(
        auth_key=args.auth_key,
        api_url=(args.api_url or None),
        sleep_between=0.5,
    )

    updated_files: List[str] = []
    skipped_files: List[str] = []

    spt_files = sorted(args.root.rglob("*.spt"))

    # Per-file processing (safer: writes CSV + outputs progressively)
    for fp in spt_files:
        if norm_path_str(str(fp)) in ignore_set:
            skipped_files.append(str(fp))
            continue

        data = fp.read_bytes()
        parts = data.split(b"\x00")
        decoded = decode_parts(data)

        blocks = extract_blocks_for_file(fp, decoded, max_dialogue_chars=args.max_dialogue_chars)
        blocks = [b for b in blocks if any(isinstance(x, str) and x and has_japanese(x) for x in b.jp_lines)]
        if not blocks:
            continue

        # Cache key rules:
        # - dialogue: include speaker_hint for safer context
        # - label: ignore speaker_hint so identical labels dedupe across files
        def block_cache_key(b: Block) -> str:
            joined = "\n".join(b.jp_lines)
            if b.kind == "label":
                return f"label|{sha1(joined)}"
            return f"dialogue|{b.speaker_hint or ''}|{sha1(joined)}"

        # Determine which unique blocks in THIS FILE need translation
        to_translate: List[Tuple[str, Block]] = []
        planned = set()

        for b in blocks:
            if args.skip_name_like_labels and b.kind == "label" and len(b.jp_lines) == 1:
                if NAME_LIKE_RE.match(b.jp_lines[0].strip()):
                    continue

            k = block_cache_key(b)
            if k in cache:
                continue
            if k in planned:
                continue
            planned.add(k)
            to_translate.append((k, b))

        # Translate in batches
        i = 0
        while i < len(to_translate):
            batch = to_translate[i:i + args.batch_size]
            texts = [blocks_to_deepl_text(b) for (_k, b) in batch]
            keys = [k for (k, _b) in batch]
            blks = [b for (_k, b) in batch]

            out_xml_list = translator.translate_texts(texts)
            if len(out_xml_list) != len(blks):
                raise RuntimeError("DeepL response count mismatch.")

            # Persist to cache immediately (so crash later still keeps results if cache-json writes)
            for k, b, out_xml in zip(keys, blks, out_xml_list):
                en_lines = parse_deepl_xml_output(out_xml, expected_lines=len(b.jp_lines))
                cache[k] = en_lines

            # Write cache to disk progressively too (extra safety)
            args.cache_json.parent.mkdir(parents=True, exist_ok=True)
            args.cache_json.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

            i += args.batch_size

        # Apply + write replacement rows immediately for THIS FILE
        rel = fp.relative_to(args.root)
        replacement_rows: List[Tuple[str, int, str, str, str, str]] = []
        changed = False

        for b in blocks:
            if args.skip_name_like_labels and b.kind == "label" and len(b.jp_lines) == 1:
                if NAME_LIKE_RE.match(b.jp_lines[0].strip()):
                    continue

            k = block_cache_key(b)
            en_lines = cache.get(k)
            if not en_lines:
                continue

            for idx_in_block, part_index in enumerate(b.line_indices):
                done_key = (str(rel), int(part_index))
                if done_key in done_set:
                    continue
                jp = b.jp_lines[idx_in_block]
                en = (en_lines[idx_in_block] or "").strip()
                if not en:
                    continue

                en = strip_macrons(sanitize_for_cp932(en))
                en = strip_accents(en)

                # Persist mapping row (so you can reapply later even if writing fails)
                replacement_rows.append((str(rel), int(part_index), b.kind, b.speaker_hint or "", jp, en))
                done_set.add(done_key)
                # Update binary parts now (unless translate-only)
                try:
                    en_bytes = en.encode(ENC, errors=args.encoding_errors)
                except UnicodeEncodeError as e:
                    raise UnicodeEncodeError(
                        e.encoding, e.object, e.start, e.end,
                        f"{e.reason} (file={fp}, jp={jp!r}, en={en!r})"
                    )

                parts[part_index] = en_bytes
                changed = True

        # Append rows for this file immediately (crash-safe)
        append_rows(args.replacements_csv, replacement_rows)

        if changed and not args.translate_only:
            out_fp = args.out / rel
            out_fp.parent.mkdir(parents=True, exist_ok=True)
            out_fp.write_bytes(b"\x00".join(parts))
            updated_files.append(str(rel))

    # Reports
    (args.out / "updated_files.txt").write_text("\n".join(updated_files), encoding="utf-8")
    (args.out / "skipped_files.txt").write_text("\n".join(skipped_files), encoding="utf-8")

    print(f"Files scanned: {len(spt_files)}")
    print(f"Files skipped (ignore list): {len(skipped_files)}")
    print(f"Updated files written: {len(updated_files)}")
    print(f"Replacements CSV: {args.replacements_csv}")
    print(f"Cache JSON: {args.cache_json}")


if __name__ == "__main__":
    main()
