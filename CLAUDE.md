# Answering questions about the Predictive History videos

This repo holds the transcripts of every video on the Predictive History YouTube channel (Professor Jiang Xueqin): 191 uploads (175 distinct after removing re-uploads), June 2023 to September 2026, about 2.4 million words. That's far more than fits in context, so answer by searching, then reading around the hits, then citing.

## Layout

- `INDEX.md`: every video grouped by series, with date, length and links. Titles are descriptive, so it's the fastest way to scope a question.
- `catalog.csv`, `catalog.json`: the same list as data. `catalog.json` also has each YouTube description and the source file paths.
- `transcripts/<series>/<YYYY-MM-DD>-<title>.md`: one file per video. Front matter has the metadata. After `## Transcript`, each paragraph is a single line that starts with a timestamp link:
  `[17:38](https://youtu.be/exRK-85630k?t=1058) text…`
- `tools/search.py`: ranked search across all transcripts (Python standard library only).
- `source/`: the original archive, byte-for-byte (verbatim captions, raw caption JSON with timings, audit files, YouTube dates). `.ignore` hides it from default Grep. Search it only when you need exact caption wording or raw timings, by passing its path explicitly.

## How to answer

1. **Scope.** Work out which series and dates matter. Skim `INDEX.md` or run `python3 tools/search.py --list --series <name>`.
2. **Search.** `tools/search.py` output already carries the date, title, timestamp link and `file:line`:
   - `python3 tools/search.py <words>`: best passages, at most 3 per video (`--per-video 0` lifts the cap).
   - `python3 tools/search.py --videos <words>`: which videos cover a topic most.
   - `--phrase "exact words"` or `--regex "pattern"`: every occurrence, oldest first. Add `--count` for per-video counts.
   - Filters: `--series`, `--after YYYY-MM-DD`, `--before`, `--video <title/id substring>`. Use `-C 1` for neighbouring paragraphs and `-n` for more results.
   - Grep on `transcripts/` also works. Every hit line includes its timestamp link.
3. **Read before answering.** Open the file around each important hit (Read with `offset` near the line number) and read enough on both sides to know who is speaking and what the point is. A single paragraph out of context misleads, especially in class Q&A where students talk.
4. **Cite.** Back every substantive claim with the timestamp link, the title and the date, e.g. [Geo-Strategy #5, 2024-05-16, 17:38](https://youtu.be/exRK-85630k?t=1058). Quote exactly and briefly. Paraphrase otherwise.

### Broad questions ("what's his view on X", "how did Y evolve")

- Search several phrasings and synonyms. Use `--videos` to find the densest sources. Check across series and across time.
- When a question needs many long transcripts read, delegate: give each subagent one video (or a few) and have it return findings with timestamp links. That keeps your own context for the synthesis. A median video is about 9k words; the Dante sessions run 35–48k.
- Say what you covered: which videos you read closely and which you only searched. Don't imply completeness you don't have.
- Chronology matters on a channel built around predictions. Date every claim, and separate what he predicted before an event from what he said after it. Catalog dates are YouTube publish dates (US Pacific). The YouTube description often gives the real lecture or event date, which can differ: Beijing classes often show a day later than the publish date, and meet-ups go up days after the event.

## Accuracy traps

- **Auto-caption errors are common.** "Jiang" usually comes out as "Jang", "John", "Jen" or "Jung". "World War III" almost always appears as "World War II": there are 211 hits for II/2/two against 5 for III/3/three. In *Game Theory #23: The WWIII Chessboard*, for example, the captions read "In World War II, there will be four major players. United States, Israel, Iran, and Russia". So search "world war" and judge from context and date. Compound words get split ("psycho history"), and names get mangled ("Nikki haly", "Nikki Hy"). If a search finds nothing, try variants before concluding he never said it. Treat any count as approximate and say so.
- **74 distinct videos have unpunctuated captions.** That's nearly everything published before July 2025: all of Geo-Strategy, Civilization #1–58 and Geo-Strategy Update #2–4. Their text is lowercase run-on speech in roughly one-minute chunks, so sentence boundaries in a quote are your own inference. They're marked † in `INDEX.md` and `punctuated_captions: false` in front matter.
- **Not every word is Jiang's.** Students ask and answer questions in class; hosts, guests and callers speak at meet-ups and livestreams. Some captions mark speaker changes with `>>`, most don't. Attribute carefully, e.g. "a student suggests…".
- **Near-duplicates.** 16 uploads repeat another session: four audio-fixed re-uploads, plus the 12 Dante livestreams that were re-published as Dante #1–12. Search skips them by default (`--all` includes them), and their front matter has `duplicate_of`. Don't count them twice.
- **Light edits.** The text is the archive's "lightly edited" edition: fillers (um/uh) and immediate word repeats removed, sentence starts capitalised, nothing else changed. When exact wording matters, check the verbatim captions: `source_edited` in the front matter gives the file name, and the same name sits under `source/transcripts/`.
- **Report, don't endorse.** Present his arguments and predictions as his, not as established fact. Label any outside knowledge you add.

## Maintenance

- `transcripts/`, `INDEX.md` and `catalog.*` are generated by `python3 tools/build.py` from `source/`. Never edit them by hand. The build checks every source file against its recorded SHA-256 hash, and checks that each generated transcript contains exactly the source text.
- To add videos: put them into `source/` in the same archive format (audit manifest, edited transcript, raw JSON), run `python3 tools/fetch_youtube_metadata.py`, then `python3 tools/build.py`.
