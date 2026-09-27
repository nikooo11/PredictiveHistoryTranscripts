#!/usr/bin/env python3
"""Build the searchable transcript library from the untouched archive in source/.

Reads source/ (never modifies it) and writes:
  transcripts/<series>/<date>-<title>.md  one file per video, timestamped paragraphs
  catalog.csv, catalog.json               one row per video
  INDEX.md                                browsable index, grouped by series

Text comes from the "lightly edited" edition. Each paragraph is matched back to
the caption timings in source/raw_api_responses/ to get its timestamp. Paragraphs
longer than KEEP_WORDS (the unpunctuated auto-captions arrive as one paragraph per
video) are split into ~1-minute chunks. Wording is never changed: joining a file's
paragraphs reproduces the edited source text exactly, and the build checks this.

Usage (from the repo root):  python3 tools/build.py
"""
import csv
import difflib
import hashlib
import json
import re
import shutil
import sys
import unicodedata
import zlib
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source"
EDITED = SRC / "lightly edited"
OUT = ROOT / "transcripts"

KEEP_WORDS = 250    # source paragraphs up to this length are kept whole
TARGET_WORDS = 120  # when splitting, break at the first good boundary after this
MAX_WORDS = 200     # ...and force a break here if no good boundary appeared
DUPLICATE_OVERLAP = 0.6  # share of each upload's 5-word runs that must appear in the other

FILLER = re.compile(r"^(?:um+|uh+|er+|erm|hmm+|mm+)$")
WORD = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)*")
SENTENCE_END = re.compile(r"[.?!]")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_source(manifest, editorial):
    """Fail loudly if any archive file differs from the hashes recorded in its audit."""
    bad = []
    for r in manifest["transcripts"]:
        if sha256(SRC / "transcripts" / r["relative_path"]) != r["archive_file_sha256"]:
            bad.append(r["relative_path"])
        if sha256(SRC / r["raw_api_response"]) != r["raw_api_response_sha256"]:
            bad.append(r["raw_api_response"])
    for t in editorial["transcripts"]:
        if sha256(EDITED / "transcripts" / t["relative_path"]) != t["editorial_file_sha256"]:
            bad.append("lightly edited/transcripts/" + t["relative_path"])
    if bad:
        sys.exit("source/ does not match its audit hashes:\n  " + "\n  ".join(bad))


def tokens(text):
    """(normalized word, start char, end char) for each non-filler word."""
    out = []
    for m in WORD.finditer(text):
        w = m.group().lower().replace("’", "'")
        if not FILLER.match(w):
            out.append((w, m.start(), m.end()))
    return out


def caption_segments(raw):
    """[(start seconds, text)] from either provider's response format."""
    if "content" in raw:  # Supadata: milliseconds
        return [(s["offset"] / 1000.0, s["text"]) for s in raw["content"]]
    return [(float(s["start"]), s["text"]) for s in raw["transcript"]]  # TranscriptAPI


def caption_duration(raw):
    """Video length in seconds: reported by TranscriptAPI, else the end of the last caption."""
    if raw.get("length_seconds"):
        return int(raw["length_seconds"])
    if "content" in raw:
        return int(max(s["offset"] + s["duration"] for s in raw["content"]) / 1000)
    return int(max(float(s["start"]) + float(s["duration"]) for s in raw["transcript"]))


def fmt_time(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def slugify(text, maxlen=80):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"['’]", "", text.replace("&", " and "))
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    if len(slug) > maxlen:
        slug = slug[:maxlen].rsplit("-", 1)[0]
    return slug


def episode_of(title):
    m = re.search(r"#\s*(\d+|END)\b", title, re.I)
    if m:
        return int(m.group(1)) if m.group(1).isdigit() else m.group(1).upper()
    for tag in ("BONUS", "END"):
        if re.search(rf"\b{tag}\b", title):
            return tag
    return None


def parse_date(date_text):
    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", date_text)
    if not m:
        sys.exit(f"cannot parse YouTube date {date_text!r}")
    date = datetime.strptime(" ".join(m.groups()), "%b %d %Y").date().isoformat()
    kind = "streamed live" if date_text.startswith("Streamed") else (
        "premiered" if date_text.startswith("Premiered") else "published")
    return date, kind


def mark_duplicates(rows):
    """Flag uploads of the same session: audio-fixed re-uploads, and the Dante livestreams
    that were re-published as "Dante #N". In every such pair each upload has at least 73%
    of its 5-word runs in the other; for distinct lectures it is at most 24%, one way.
    Both directions must pass, so a short clip can never swallow the long video it came
    from. The later upload is kept as primary."""
    shingles = {}
    for x in rows:
        w = re.findall(r"[a-z']+", x["_body"].lower())
        shingles[x["video_id"]] = {zlib.crc32(" ".join(w[i:i + 5]).encode())
                                   for i in range(len(w) - 4)}
    for x in rows:
        x["duplicate_of"], x["duplicate_overlap"] = None, None
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            sa, sb = shingles[a["video_id"]], shingles[b["video_id"]]
            shared = len(sa & sb)
            if shared >= DUPLICATE_OVERLAP * max(len(sa), len(sb), 1):
                older, newer = sorted((a, b), key=lambda x: (x["date"], -x["_index"]))
                older["duplicate_of"] = newer["video_id"]
                older["duplicate_overlap"] = round(shared / len(shingles[older["video_id"]]), 2)


def timestamped_paragraphs(body, segs):
    """Split the edited body into paragraphs, each with the caption time it starts at.

    Returns (paragraphs, stats) where paragraphs is [(seconds, text)].
    """
    source_paras = body.split("\n\n")

    # One token stream for the whole edited text, one for the raw captions.
    ed = []  # (word, paragraph index, start char, end char)
    for pi, p in enumerate(source_paras):
        ed.extend((w, pi, s, e) for w, s, e in tokens(p))
    raw_words, raw_seg = [], []
    for si, (_, text) in enumerate(segs):
        for w, _, _ in tokens(text):
            raw_words.append(w)
            raw_seg.append(si)

    # autojunk is fast but can skip whole stretches of a long lecture; redo exactly if it does.
    for autojunk in (True, False):
        matcher = difflib.SequenceMatcher(None, [t[0] for t in ed], raw_words, autojunk=autojunk)
        ed_to_raw = {}
        for a, b, n in matcher.get_matching_blocks():
            for k in range(n):
                ed_to_raw[a + k] = b + k
        matched = len(ed_to_raw) / max(1, len(ed))
        if matched >= 0.99:
            break

    by_para = defaultdict(list)
    for i, (w, pi, s, e) in enumerate(ed):
        j = ed_to_raw.get(i)
        by_para[pi].append((s, e, raw_seg[j] if j is not None else None))

    out, forced = [], 0
    for pi, text in enumerate(source_paras):
        toks = by_para[pi]
        starts = [0]  # token indices where output paragraphs begin
        if len(toks) > KEEP_WORDS:
            punctuated = len(SENTENCE_END.findall(text)) >= len(toks) / 100
            for k in range(1, len(toks)):
                run = k - starts[-1]
                if run < TARGET_WORDS or len(toks) - k < 40 or not text[toks[k][0] - 1].isspace():
                    continue  # too soon, too near the end, or inside e.g. "nation-state"
                gap = text[toks[k - 1][1]:toks[k][0]]
                seg_break = toks[k][2] is not None and toks[k][2] != toks[k - 1][2]
                if SENTENCE_END.search(gap) or (not punctuated and seg_break):
                    starts.append(k)
                elif run >= MAX_WORDS and (seg_break or run >= MAX_WORDS + 30):
                    starts.append(k)
                    forced += 1
        bounds = [0] + [toks[k][0] for k in starts[1:]] + [len(text)]
        for n, k in enumerate(starts):
            end_k = starts[n + 1] if n + 1 < len(starts) else len(toks)
            seg = next((t[2] for t in toks[k:end_k] if t[2] is not None), None)
            chunk = text[bounds[n]:bounds[n + 1]].strip()
            if chunk:
                out.append([segs[seg][0] if seg is not None else None, chunk])

    # Fill any unaligned paragraph with its predecessor's time; keep times monotonic
    # (overlapping auto-caption cues can start a hair before the previous one).
    filled = 0
    prev = 0.0
    for p in out:
        if p[0] is None or p[0] < prev:
            filled += p[0] is None or p[0] < prev - 1
            p[0] = prev
        prev = p[0]

    joined = " ".join(p[1] for p in out)
    if joined.split() != body.split():
        raise AssertionError("paragraph split changed the text")
    return [tuple(p) for p in out], {"matched": matched, "forced": forced, "filled": filled}


def main():
    manifest = json.loads((SRC / "audit_manifest.json").read_text())
    editorial = json.loads((EDITED / "editorial_audit.json").read_text())
    youtube = json.loads((SRC / "youtube_metadata.json").read_text())["videos"]
    verify_source(manifest, editorial)

    rows = []
    for r in manifest["transcripts"]:
        vid = r["video_id"]
        raw = json.loads((SRC / r["raw_api_response"]).read_text())
        segs = caption_segments(raw)
        edited_path = EDITED / "transcripts" / r["relative_path"]
        text = edited_path.read_text(encoding="utf-8")
        header = r["video_url"] + "\n\n"
        assert text.startswith(header), edited_path
        body = text[len(header):].rstrip("\n")
        date, date_kind = parse_date(youtube[vid]["date_text"])
        words = len(body.split())
        rows.append({
            "_index": r["index"],  # archive order: newest upload first within a channel tab
            "video_id": vid,
            "title": r["title"],
            "series": r["series_folder"],
            "episode": episode_of(r["title"]),
            "date": date,
            "date_kind": date_kind,
            "duration_seconds": caption_duration(raw),
            "words": words,
            "punctuated": len(SENTENCE_END.findall(body)) >= words / 100,
            "caption_provider": r["source_provider"],
            "caption_language": r["returned_caption_language"],
            "url": r["video_url"],
            "description": youtube[vid]["description"].strip(),
            "source_verbatim": f"source/transcripts/{r['relative_path']}",
            "source_edited": f"source/lightly edited/transcripts/{r['relative_path']}",
            "source_raw": f"source/{r['raw_api_response']}",
            "_body": body,
            "_segs": segs,
        })

    mark_duplicates(rows)
    for x in rows:
        x["file"] = f"transcripts/{slugify(x['series'])}/{x['date']}-{slugify(x['title'])}.md"
    files = [x["file"] for x in rows]
    assert len(set(files)) == len(files), "file name collision"
    by_id = {x["video_id"]: x for x in rows}

    if OUT.exists():
        shutil.rmtree(OUT)
    totals = defaultdict(int)
    for x in sorted(rows, key=lambda x: (x["date"], x["title"])):
        paras, stats = timestamped_paragraphs(x.pop("_body"), x.pop("_segs"))
        x["paragraphs"] = len(paras)
        totals["paragraphs"] += len(paras)
        totals["forced"] += stats["forced"]
        totals["filled"] += stats["filled"]
        if stats["matched"] < 0.95:
            print(f"warning: only {stats['matched']:.0%} of words aligned in {x['file']}")
        write_transcript(x, paras, by_id)

    rows.sort(key=lambda x: (x["date"], x["title"]))
    write_catalog(rows)
    write_index(rows)
    print(f"{len(rows)} transcripts, {totals['paragraphs']} timestamped paragraphs "
          f"({totals['forced']} forced splits, {totals['filled']} times carried forward)")


def rel_link(from_file, to_file):
    return "../" * (from_file.count("/") - 1) + to_file[len("transcripts/"):] \
        if to_file.startswith("transcripts/") else to_file


def write_transcript(x, paras, by_id):
    vid = x["video_id"]
    title = " ".join(x["title"].split())
    fm = {
        "title": x["title"],
        "series": x["series"],
        "episode": x["episode"],
        "date": x["date"],
        "date_kind": x["date_kind"],
        "video_id": vid,
        "url": x["url"],
        "duration": fmt_time(x["duration_seconds"]),
        "words": x["words"],
        "punctuated_captions": x["punctuated"],
        "duplicate_of": x["duplicate_of"],
        "source_edited": x["source_edited"],
    }
    lines = ["---"]
    lines += [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fm.items()]
    lines += ["---", "", f"# {title}", ""]
    lines.append(f"{x['series']} · {x['date_kind'].capitalize()} {x['date']} · "
                 f"{fmt_time(x['duration_seconds'])} · {x['words']:,} words · "
                 f"[Watch on YouTube]({x['url']})")
    lines.append("")
    if x["duplicate_of"]:
        d = by_id[x["duplicate_of"]]
        lines += [f"> **Near-duplicate.** The same session was uploaded again as "
                  f"[{' '.join(d['title'].split())}]({rel_link(x['file'], d['file'])}); "
                  f"{x['duplicate_overlap']:.0%} of this transcript's 5-word runs appear there too. "
                  "`tools/search.py` skips this file unless you pass `--all`.", ""]
    if not x["punctuated"]:
        lines += ["> **Unpunctuated captions.** The source captions for this video have no "
                  "punctuation or capitalisation, so the text is split into ~1-minute chunks "
                  "instead of real paragraphs.", ""]
    if x["description"]:
        lines += ["## YouTube description", ""]
        lines += [("> " + l) if l.strip() else ">" for l in x["description"].splitlines()]
        lines.append("")
    lines += ["## Transcript", ""]
    for sec, text in paras:
        lines += [f"[{fmt_time(sec)}](https://youtu.be/{vid}?t={int(sec)}) {text}", ""]
    path = ROOT / x["file"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


CSV_FIELDS = ["date", "series", "episode", "title", "duration", "words", "punctuated",
              "duplicate_of", "video_id", "url", "file"]


def write_catalog(rows):
    with open(ROOT / "catalog.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for x in rows:
            w.writerow({**{k: x.get(k) for k in CSV_FIELDS},
                        "duration": fmt_time(x["duration_seconds"]),
                        "episode": "" if x["episode"] is None else x["episode"],
                        "duplicate_of": x["duplicate_of"] or ""})
    keys = ["date", "date_kind", "series", "episode", "title", "video_id", "url", "file",
            "duration_seconds", "words", "paragraphs", "punctuated", "duplicate_of",
            "duplicate_overlap", "caption_provider", "caption_language", "description",
            "source_verbatim", "source_edited", "source_raw"]
    (ROOT / "catalog.json").write_text(
        json.dumps([{k: x[k] for k in keys} for x in rows], indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")


def md_cell(text):
    return " ".join(text.split()).replace("|", "\\|")


def write_index(rows):
    series = defaultdict(list)
    for x in rows:
        series[x["series"]].append(x)
    order = sorted(series, key=lambda s: series[s][0]["date"])
    total_words = sum(x["words"] for x in rows)
    hours = sum(x["duration_seconds"] for x in rows) / 3600
    dups = sum(1 for x in rows if x["duplicate_of"])
    out = [
        "# Predictive History: video index",
        "",
        f"{len(rows)} videos ({len(rows) - dups} distinct, {dups} near-duplicate re-uploads) · "
        f"{rows[0]['date']} to {rows[-1]['date']} · {hours:,.0f} hours · "
        f"{total_words / 1e6:.1f}M words.",
        "",
        "Generated by `tools/build.py`; don't edit by hand. Dates are YouTube publish dates "
        "(US Pacific time). Machine-readable versions: `catalog.csv`, `catalog.json`.",
        "",
        "Marks: **†** unpunctuated auto-captions (text in ~1-minute chunks) · "
        "**dup** near-duplicate of another video (skipped by search unless `--all`).",
        "",
        "| Series | Videos | First | Last | Hours |",
        "|---|---:|---|---|---:|",
    ]
    for s in order:
        v = series[s]
        anchor = slugify(s)
        out.append(f"| [{s}](#{anchor}) | {len(v)} | {v[0]['date']} | {v[-1]['date']} | "
                   f"{sum(x['duration_seconds'] for x in v) / 3600:.0f} |")
    for s in order:
        v = series[s]
        out += ["", f"## {s}", "", "| Date | # | Title | Length | Video |", "|---|---:|---|---:|---|"]
        for x in v:
            marks = ("" if x["punctuated"] else " †") + (" dup" if x["duplicate_of"] else "")
            ep = "" if x["episode"] is None else x["episode"]
            out.append(f"| {x['date']} | {ep} | [{md_cell(x['title'])}]({x['file']}){marks} | "
                       f"{fmt_time(x['duration_seconds'])} | [▶]({x['url']}) |")
    (ROOT / "INDEX.md").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
