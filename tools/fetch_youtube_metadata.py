#!/usr/bin/env python3
"""Fetch each video's publish date and description from YouTube into source/youtube_metadata.json.

The caption archive has no dates, and its numbering is not chronological, so dates
come from YouTube's watch-page data (the internal youtubei/v1/next endpoint, which
still answers when the public watch page is bot-blocked). Existing entries are kept
unless --refresh is given. Run tools/build.py afterwards.

Usage (from the repo root):  python3 tools/fetch_youtube_metadata.py [--refresh]
"""
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "source" / "youtube_metadata.json"
URL = "https://www.youtube.com/youtubei/v1/next?prettyPrint=false"


def find(obj, key):
    """Every value stored under `key` anywhere in a nested JSON structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from find(v, key)
    elif isinstance(obj, list):
        for item in obj:
            yield from find(item, key)


def fetch(video_id):
    body = json.dumps({"context": {"client": {"clientName": "WEB", "clientVersion": "2.20240101.00.00",
                                              "hl": "en", "gl": "US"}},
                       "videoId": video_id}).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            date_text = next(find(data, "dateText"))
            date_text = date_text.get("simpleText") or "".join(x["text"] for x in date_text["runs"])
            desc = next((b["attributedDescriptionBodyText"].get("content", "")
                         for b in find(data, "expandableVideoDescriptionBodyRenderer")
                         if "attributedDescriptionBodyText" in b), "")
            info = next(find(data, "videoPrimaryInfoRenderer"))
            title = "".join(x["text"] for x in info["title"]["runs"])
            return video_id, {"title": title, "date_text": date_text, "description": desc}
        except Exception as e:  # noqa: BLE001 - retry anything, report the last error
            error = e
            time.sleep(2 * (attempt + 1))
    return video_id, {"error": str(error)}


def main():
    manifest = json.loads((ROOT / "source" / "audit_manifest.json").read_text())
    ids = [r["video_id"] for r in manifest["transcripts"]]
    doc = json.loads(OUT.read_text()) if OUT.exists() else {"videos": {}}
    todo = ids if "--refresh" in sys.argv else [v for v in ids if v not in doc["videos"]]
    with ThreadPoolExecutor(max_workers=3) as ex:
        results = dict(ex.map(fetch, todo))
    failed = {v: r["error"] for v, r in results.items() if "error" in r}
    doc["videos"].update({v: r for v, r in results.items() if "error" not in r})
    doc["source"] = ("YouTube watch-page data (youtubei/v1/next), fetched "
                     f"{date.today().isoformat()} by tools/fetch_youtube_metadata.py")
    doc["note"] = ("date_text is YouTube's displayed date (US Pacific time). Livestreams from "
                   "Beijing can show the previous calendar day.")
    doc["videos"] = {v: doc["videos"][v] for v in ids if v in doc["videos"]}
    OUT.write_text(json.dumps({k: doc[k] for k in ("source", "note", "videos")},
                              indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"fetched {len(results) - len(failed)}, failed {len(failed)}, "
          f"have {len(doc['videos'])}/{len(ids)}")
    for v, err in failed.items():
        print(f"  {v}: {err}")
    sys.exit(1 if len(doc["videos"]) < len(ids) else 0)


if __name__ == "__main__":
    main()
