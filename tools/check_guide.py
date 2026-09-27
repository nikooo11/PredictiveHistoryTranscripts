#!/usr/bin/env python3
"""Verify the study guide in guide/ against the transcripts, and keep its apparatus in order.

Checks every citation link [label](https://youtu.be/ID?t=SECONDS):
  - the video exists, and SECONDS is the exact start of one of its transcript paragraphs;
  - every quotation of 4+ words on the same line appears in the transcript near a cited moment.

With --write it also rewrites every citation label to the canonical form ("Civ 15 · 12:34"),
regenerates each chapter's "## Sources" list, and regenerates the A–Z index of figures in
guide/README.md (between the INDEX markers).

Usage (from the repo root):  python3 tools/check_guide.py [--write]
Exit status is 1 if any citation or quote fails.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "guide"
PARA = re.compile(r"^\[[\d:]+\]\(https://youtu\.be/([^?]+)\?t=(\d+)\) (.*)$")
LINK = re.compile(r"\[([^\]]*)\]\(https://youtu\.be/([A-Za-z0-9_-]{11})\?t=(\d+)\)")
QUOTE = re.compile(r"“([^”]+)”|\"([^\"]+)\"")
INDEX_START, INDEX_END = "<!-- INDEX:START -->", "<!-- INDEX:END -->"


def fmt_time(sec):
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def abbreviation(v):
    """Short label for a video, e.g. 'Civ 15', 'GSU 3', 'Dante 7'."""
    t = " ".join(v["title"].split())
    num = re.search(r"#\s*(\d+|END)\b", t, re.I)
    n = num.group(1).upper() if num else None
    rules = [
        (r"^Civilization", "Civ"), (r"^Geo-Strategy Update", "GSU"), (r"^Geo-Strategy", "GS"),
        (r"^Secret History", "SH"), (r"^Game Theory", "GT"), (r"^Great Books", "GB"),
        (r"^Dante Livestream", "Dante Live"), (r"^Dante", "Dante"), (r"^Global Meet-Up", "Meet-Up"),
        (r"^Emergency Discussion", "Emergency"), (r"^Live with Predictive History", "Live"),
        (r"^Substack Live", "Substack Live"), (r"Founding Members", "Members"),
    ]
    for pattern, prefix in rules:
        if re.search(pattern, t):
            if prefix == "Civ" and "BONUS" in t:
                n = "BONUS"
            if prefix == "GSU" and n is None:
                n = "1"  # "Geo-Strategy Update: US-Iran War Incoming", the unnumbered first update
            if prefix == "GS" and n is None and "END" in t:
                n = "END"
            label = f"{prefix} {n}" if n else prefix
            return label + (" (orig.)" if v["duplicate_of"] and prefix != "Dante Live" else "")
    if "Gay Talese" in t:
        return "Talese 2023"
    return t[:30]


def load_corpus():
    videos = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    corpus = {}
    for v in videos:
        paras = []
        for line in (ROOT / v["file"]).read_text(encoding="utf-8").splitlines():
            m = PARA.match(line)
            if m:
                paras.append((int(m.group(2)), m.group(3)))
        corpus[v["video_id"]] = {"meta": v, "abbr": abbreviation(v), "paras": paras,
                                 "starts": {t: i for i, (t, _) in reversed(list(enumerate(paras)))}}
    return corpus


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower().replace("’", "'").replace("'", ""))


def quote_found(quote, windows):
    """Every fragment of the quote (split at ellipses and [insertions]) appears, in order."""
    frags = [words(f) for f in re.split(r"\[[^\]]*\]|\.\.\.|…", quote)]
    frags = [f for f in frags if f]
    if sum(len(f) for f in frags) < 4:
        return True  # too short to check meaningfully
    for text in windows:
        hay = " " + " ".join(words(text)) + " "
        pos, ok = 0, True
        for f in frags:
            at = hay.find(" " + " ".join(f) + " ", pos)
            if at < 0:
                ok = False
                break
            pos = at + 1
        if ok:
            return True
    return False


def chapter_files():
    return sorted(p for p in GUIDE.glob("*.md") if p.name != "README.md")


def check(corpus):
    errors = []
    cited = defaultdict(set)
    for path in chapter_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            links = LINK.findall(line)
            windows = []
            for _, vid, sec in links:
                v = corpus.get(vid)
                if v is None:
                    errors.append(f"{path.name}:{n}: unknown video {vid}")
                    continue
                i = v["starts"].get(int(sec))
                if i is None:
                    errors.append(f"{path.name}:{n}: {v['abbr']} has no paragraph starting at t={sec}")
                    continue
                cited[path.name].add(vid)
                lo, hi = max(0, i - 3), min(len(v["paras"]), i + 4)
                windows.append(" ".join(t for _, t in v["paras"][lo:hi]))
            if not windows:
                continue
            for m in QUOTE.finditer(line):
                q = m.group(1) or m.group(2)
                if len(words(q)) >= 4 and not quote_found(q, windows):
                    errors.append(f"{path.name}:{n}: quote not found near its citation: \"{q[:80]}\"")
    return errors, cited


def slug(heading):
    return re.sub(r"\s+", "-", re.sub(r"[^\w\s-]", "", heading.lower()).strip())


def write(corpus, cited):
    entries = []
    for path in chapter_files():
        text = path.read_text(encoding="utf-8")
        text = LINK.sub(lambda m: f"[{corpus[m.group(2)]['abbr']} · {fmt_time(m.group(3))}]"
                        f"(https://youtu.be/{m.group(2)}?t={m.group(3)})"
                        if m.group(2) in corpus else m.group(0), text)
        text = re.sub(r"\n## Sources\n.*\Z", "\n", text, flags=re.S).rstrip() + "\n"
        vids = sorted(cited.get(path.name, ()), key=lambda vid: corpus[vid]["meta"]["date"])
        if vids:
            lines = ["", "## Sources", "",
                     "Videos cited in this chapter, oldest first. Each label links to its transcript.", ""]
            for vid in vids:
                v = corpus[vid]["meta"]
                lines.append(f"- [{corpus[vid]['abbr']}](../{v['file']}): {' '.join(v['title'].split())} "
                             f"({v['date']}) · [YouTube]({v['url']})")
            text += "\n".join(lines) + "\n"
        path.write_text(text, encoding="utf-8")

        title = re.search(r"^# (.+)$", text, re.M)
        title = title.group(1) if title else path.stem
        section = None
        for line in text.splitlines():
            if line.startswith("## "):
                section = line[3:].strip()
            elif line.startswith("### ") and section in ("The main figures", "Influences he names"):
                name = line[4:].strip()
                entries.append((name, path.name, slug(name), title))
            elif section == "Also mentioned":
                m = re.match(r"- \*\*(.+?)\*\*", line)
                if m:
                    entries.append((m.group(1).strip(), path.name, "also-mentioned", title))

    readme = GUIDE / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        def sort_key(name):  # "The Vikings" files under V, "St Bernard" under B
            return re.sub(r"^(the|st\.?|saint)\s+", "", name, flags=re.I).lower()

        by_letter = defaultdict(list)
        for name, fname, anchor, title in sorted(entries, key=lambda e: sort_key(e[0])):
            by_letter[sort_key(name)[:1].upper()].append(f"[{name}]({fname}#{anchor})")
        block = [INDEX_START, "",
                 f"{len(entries)} entries. Names in bold in a chapter's \"Also mentioned\" list link to that list.", ""]
        for letter in sorted(by_letter):
            block.append(f"**{letter}** · " + " · ".join(by_letter[letter]) + "  ")
        block += ["", INDEX_END]
        if INDEX_START in text and INDEX_END in text:
            text = re.sub(re.escape(INDEX_START) + r".*?" + re.escape(INDEX_END), "\n".join(block), text,
                          flags=re.S)
            readme.write_text(text, encoding="utf-8")
    return len(entries)


def main():
    corpus = load_corpus()
    errors, cited = check(corpus)
    total = sum(len(LINK.findall(p.read_text(encoding="utf-8"))) for p in chapter_files())
    for e in errors:
        print(e)
    print(f"{total} citations in {len(chapter_files())} files; {len(errors)} problems.")
    if "--write" in sys.argv:
        n = write(corpus, cited)
        print(f"labels normalized, sources rebuilt, index has {n} entries.")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
