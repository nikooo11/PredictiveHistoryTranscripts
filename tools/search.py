#!/usr/bin/env python3
"""Search every Predictive History transcript and print citable, timestamped passages.

  python3 tools/search.py hundred years war            ranked passages (BM25), best first
  python3 tools/search.py --videos nikki haley         which videos discuss it most
  python3 tools/search.py --phrase "nikki haley"       every exact phrase match, oldest first
  python3 tools/search.py --regex "haley|nikki"        regular expression (case-insensitive)
  python3 tools/search.py --count --phrase "iran"      matches per video, oldest first
  python3 tools/search.py --list --series civ          list videos (with any filters)

Filters: --series, --after/--before YYYY-MM-DD, --video (title/id/file substring).
Near-duplicate uploads (re-uploads, and Dante livestreams re-published as Dante #1-12)
are skipped unless you pass --all.
Standard library only; run from anywhere.
"""
import argparse
import json
import math
import re
import signal
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARA = re.compile(r"^\[([\d:]+)\]\((https://youtu\.be/[^)]+)\) (.*)$")
WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)*")
STOP = set("""
a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further
had has have having he her here hers herself him himself his how i if in into is it its itself
just me more most my myself no nor not now of off on once only or other our ours ourselves out
over own same she should so some such than that the their theirs them themselves then there
these they this those through to too under until up very was we were what when where which
while who whom why will with would you your yours yourself yourselves okay ok um uh yeah gonna
""".split())


def terms(text):
    out = []
    for w in WORD.findall(text.lower().replace("’", "'")):
        if w.endswith("'s"):
            w = w[:-2]
        if w in STOP:
            continue
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
            w = w[:-1]
        out.append(w)
    return out


def normalized(text):
    return " " + " ".join(WORD.findall(text.lower().replace("’", "'"))) + " "


def pick_series(videos, wanted):
    """Series names matching --series: exact name/folder wins, else substring."""
    folders = {v["series"]: v["file"].split("/")[1] for v in videos}
    chosen = set()
    for s in (w.lower() for w in wanted):
        exact = {n for n, f in folders.items() if s in (n.lower(), f)}
        chosen |= exact or {n for n, f in folders.items() if s in n.lower() or s in f}
    if not chosen:
        sys.exit(f"no series matches {wanted}; choose from: {', '.join(sorted(folders))}")
    return chosen


def load(args):
    videos = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    series = pick_series(videos, args.series) if args.series else None
    kept = []
    for v in videos:
        if v["duplicate_of"] and not args.all:
            continue
        if series and v["series"] not in series:
            continue
        if args.after and v["date"] < args.after:
            continue
        if args.before and v["date"] > args.before:
            continue
        if args.video and not any(q.lower() in f"{v['title']} {v['video_id']} {v['file']}".lower()
                                  for q in args.video):
            continue
        v["paras"] = []
        for n, line in enumerate((ROOT / v["file"]).read_text(encoding="utf-8").splitlines(), 1):
            m = PARA.match(line)
            if m:
                v["paras"].append({"video": v, "i": len(v["paras"]), "line": n,
                                   "time": m.group(1), "link": m.group(2), "text": m.group(3)})
        # Title + YouTube description, searchable in ranked modes only: they spell names
        # correctly where the auto-captions often don't.
        v["about"] = {"video": v, "i": None, "line": 1, "time": "title/description",
                      "link": v["url"], "text": " ".join(f"{v['title']} {v['description']}".split())}
        kept.append(v)
    return kept


def title(v):
    return " ".join(v["title"].split())


def snippet(text, query, width=220):
    """~width characters of text around the exact query, else its first query word."""
    words = [re.escape(w) for w in WORD.findall(query.lower()) if w not in STOP]
    at = None
    for pattern in [r"\W+".join(words)] + words:
        m = re.search(r"\b" + pattern, text, re.I) if pattern else None
        if m:
            at = m.start()
            break
    if len(text) <= width or at is None:
        return text if len(text) <= width else text[:width] + "…"
    start = max(0, min(at - width // 3, len(text) - width))
    return ("…" if start else "") + text[start:start + width] + ("…" if start + width < len(text) else "")


def show(p, context, rank=None):
    v = p["video"]
    head = f"[{rank}] " if rank else ""
    print(f"{head}{v['date']} · {title(v)}")
    print(f"    {p['time']} {p['link']} · {v['file']}:{p['line']}")
    if p["i"] is None:  # the title/description entry
        print(f"    {p['text']}\n")
        return
    lo, hi = max(0, p["i"] - context), min(len(v["paras"]), p["i"] + context + 1)
    for q in v["paras"][lo:hi]:
        mark = "" if q is p else f"({q['time']}) "
        print(f"    {mark}{q['text']}")
    print()


def ranked(videos, query, args):
    paras = [p for v in videos for p in v["paras"] + [v["about"]]]
    qterms = list(dict.fromkeys(terms(query)))
    if not qterms:
        sys.exit("query has no searchable words (only stopwords?)")
    df = Counter()
    tfs = []
    for p in paras:
        tf = Counter(terms(p["text"]))
        tfs.append(tf)
        df.update(t for t in qterms if t in tf)
    n = len(paras)
    avg = sum(sum(tf.values()) for tf in tfs) / max(1, n)
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in qterms}
    phrase = normalized(query)
    k1, b = 1.2, 0.75
    scored = []
    for p, tf in zip(paras, tfs):
        s = 0.0
        length = sum(tf.values())
        for t in qterms:
            f = tf.get(t)
            if f:
                s += idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * length / avg))
        if s:
            present = sum(1 for t in qterms if t in tf)
            s *= (present / len(qterms)) ** 2  # favour passages that have every term
            if len(qterms) > 1 and phrase in normalized(p["text"]):
                s *= 3  # the exact phrase is the strongest signal there is
            p["all_terms"] = present == len(qterms)
            scored.append((s, p))
    scored.sort(key=lambda x: -x[0])
    missing = [t for t in qterms if not df[t]]
    if missing:
        print(f"(nothing contains: {', '.join(missing)}. Auto-captions misspell names and split "
              "compounds, e.g. 'psycho history', so try variants.)\n")

    if args.videos:
        by_video = defaultdict(list)
        for s, p in scored:
            by_video[p["video"]["video_id"]].append((s, p))
        rows = sorted(by_video.values(), key=lambda hits: -sum(s for s, _ in hits[:3]))
        print(f"{len(rows)} videos match; showing {min(args.top, len(rows))} most relevant.\n")
        for r, hits in enumerate(rows[:args.top], 1):
            best = hits[0][1]
            full = sum(1 for _, p in hits if p["all_terms"])
            print(f"[{r}] {best['video']['date']} · {title(best['video'])}")
            print(f"    {len(hits)} matching passages ({full} with every term) · best at "
                  f"{best['time']} {best['link']}")
            print(f"    {best['video']['file']}:{best['line']}")
            print(f"    {snippet(best['text'], query)}\n")
        return

    shown, per_video = [], Counter()
    for s, p in scored:
        vid = p["video"]["video_id"]
        if args.per_video and per_video[vid] >= args.per_video:
            continue
        per_video[vid] += 1
        shown.append(p)
        if len(shown) == args.top:
            break
    print(f"{len(scored)} passages in {len({p['video']['video_id'] for _, p in scored})} videos "
          f"match; showing {len(shown)} (max {args.per_video or 'unlimited'} per video).\n")
    for r, p in enumerate(shown, 1):
        show(p, args.context, r)


def exact(videos, args):
    if args.phrase:
        needle = normalized(args.phrase)
        label = f'phrase "{args.phrase}"'

        def occurrences(text):
            return normalized(text).count(needle)
    else:
        try:
            rx = re.compile(args.regex, re.I)
        except re.error as e:
            sys.exit(f"bad --regex: {e}")
        label = f"regex /{args.regex}/"

        def occurrences(text):
            return len(rx.findall(text))
    hits = [(p, c) for v in videos for p in v["paras"] if (c := occurrences(p["text"]))]
    total = sum(c for _, c in hits)
    nvid = len({p["video"]["video_id"] for p, _ in hits})
    print(f"{label}: {total} occurrences in {len(hits)} passages across {nvid} of "
          f"{len(videos)} videos.\n")
    if args.count:
        counts = Counter()
        for p, c in hits:
            counts[p["video"]["video_id"]] += c
        for v in videos:
            if counts[v["video_id"]]:
                print(f"{counts[v['video_id']]:5d}  {v['date']}  {title(v)}  ({v['file']})")
        return
    for p, _ in hits[:args.top]:
        show(p, args.context)
    if len(hits) > args.top:
        print(f"... {len(hits) - args.top} more passages. Raise --top, narrow with filters, "
              "or use --count.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="*", help="words to rank passages by (BM25)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--phrase", help="exact phrase (ignores case and punctuation)")
    mode.add_argument("--regex", help="Python regular expression, case-insensitive")
    mode.add_argument("--list", action="store_true", help="list the videos that pass the filters")
    ap.add_argument("--videos", action="store_true", help="rank whole videos instead of passages")
    ap.add_argument("--count", action="store_true", help="with --phrase/--regex: matches per video")
    ap.add_argument("-n", "--top", type=int, default=10, help="results to show (default 10)")
    ap.add_argument("-C", "--context", type=int, default=0, help="paragraphs of context either side")
    ap.add_argument("--per-video", type=int, default=3,
                    help="max ranked passages per video (default 3, 0 = no limit)")
    ap.add_argument("-s", "--series", action="append", help="series name or folder (repeatable)")
    ap.add_argument("--after", help="only videos published on/after YYYY-MM-DD")
    ap.add_argument("--before", help="only videos published on/before YYYY-MM-DD")
    ap.add_argument("-v", "--video", action="append", help="title, video id or file substring (repeatable)")
    ap.add_argument("--all", action="store_true", help="include near-duplicate videos")
    args = ap.parse_args()
    if hasattr(signal, "SIGPIPE"):  # exit quietly when piped into head
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    videos = load(args)
    if not videos:
        sys.exit("no videos match those filters")
    if args.list:
        for v in videos:
            print(f"{v['date']}  {v['series']:<22} {title(v)}\n            {v['url']} · {v['file']}")
        print(f"\n{len(videos)} videos")
    elif args.phrase or args.regex:
        exact(videos, args)
    elif args.count:
        sys.exit("--count works with --phrase or --regex; to rank videos by words, use --videos")
    elif args.query:
        ranked(videos, " ".join(args.query), args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
