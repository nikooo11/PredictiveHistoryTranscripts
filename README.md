# Predictive History transcripts

Transcripts of all 191 uploads on the [Predictive History](https://www.youtube.com/@PredictiveHistory) YouTube channel (Professor Jiang Xueqin), June 2023 to September 2026. They're organized by series, dated, and searchable, and every paragraph links to its moment in the video.

**191 videos** (175 distinct sessions plus 16 re-uploads) · **12 series** · **273 hours** · **2.4M words**

## Ask questions

Open the repo in [Claude Code](https://claude.ai/code) and ask. [`CLAUDE.md`](CLAUDE.md) tells Claude how to search all the transcripts, read the context around each hit, and cite the timestamped moments it relies on. For example:

- *What did he predict about a US–Iran war before June 2025? Cite each video.*
- *How does he define psychohistory, and where does it come back after Geo-Strategy?*
- *Summarize the argument of Secret History #END, then find where he revisits it later.*

## Browse

- [`INDEX.md`](INDEX.md): every video grouped by series, with date, length, transcript link and YouTube link.
- [`catalog.csv`](catalog.csv) opens as a spreadsheet. [`catalog.json`](catalog.json) is the same list plus the YouTube descriptions.

## Search from the terminal

Needs Python 3.8 or later and nothing else.

```sh
python3 tools/search.py hundred years war              # best passages, ranked
python3 tools/search.py --videos nikki haley           # which videos cover it most
python3 tools/search.py --phrase "psycho history"      # every exact occurrence, oldest first
python3 tools/search.py --regex "world war (ii|iii)" --count --series "game theory"
python3 tools/search.py --list --after 2026-07-01      # videos in a date range
```

Every result carries the date, title, a `youtu.be/…?t=` link and `file:line`.

## Layout

| Path | What it is |
|---|---|
| `transcripts/<series>/<date>-<title>.md` | One file per video: metadata front matter, YouTube description, then the transcript with a timestamp link on every paragraph. |
| `INDEX.md`, `catalog.csv`, `catalog.json` | The video list, generated. |
| `tools/search.py` | Search. |
| `tools/build.py` | Rebuilds `transcripts/`, `INDEX.md` and `catalog.*` from `source/`. |
| `tools/fetch_youtube_metadata.py` | Fetches publish dates and descriptions from YouTube. |
| `source/` | The original archive, byte-for-byte. See Provenance. |

## About the text

- **The wording is the archive's "lightly edited" edition.** Fillers (um/uh) and immediate word repeats are removed and sentence starts capitalised. Nothing else changed. The build checks that each transcript file contains exactly that text, and only adds paragraph breaks and timestamps.
- **Timestamps come from the original caption timings.** The edited text was matched back, word by word, to the raw captions. For 47,249 of the 47,259 paragraphs (99.98%), the first three words appear in the captions at the linked time.
- **Auto-captions make mistakes.** Names get mangled ("Jiang" often comes out as "Jang"), and "World War III" is almost always captioned as "World War II". Treat exact counts as approximate.
- **74 distinct videos have no punctuation in their captions.** That's nearly everything before July 2025: all of Geo-Strategy, Civilization #1–58 and Geo-Strategy Update #2–4. Their text is split into roughly one-minute chunks and marked † in the index.
- **16 near-duplicates.** Four audio-fixed re-uploads and the 12 Dante livestreams, which were re-published as Dante #1–12, repeat other videos. They're marked `dup` in the index and skipped by search unless you pass `--all`.
- **Dates are YouTube publish dates** (US Pacific time). The archive's own numbering isn't chronological, so these dates are the reliable order.

## Provenance

`source/` is an unmodified copy of the Google Drive archive [Predictive History](https://drive.google.com/drive/folders/1FYN5Fwht-RaEcOs3vyv4YJoc53VNF0ZD). Its [README](source/README.md) explains how it was made. In short:

- `source/transcripts/`: verbatim caption text as returned by the caption APIs (Supadata for 100 videos, TranscriptAPI for 91).
- `source/raw_api_responses/`: the raw API responses, with timings.
- `source/lightly edited/`: the edited edition, with its rule-by-rule audit.
- `source/audit_manifest.json`: SHA-256 hashes for everything above.

`tools/build.py` re-checks every file against those hashes before building. The one addition is `source/youtube_metadata.json`, with publish dates and descriptions fetched from YouTube on 2026-09-27.

To rebuild after changing `source/`, run `python3 tools/build.py` (about a minute).
