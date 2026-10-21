# Curation: how the agent picks

`curate` has already done the mechanical part locally (no network, no AI): bursts and
near-duplicates collapsed to their sharpest shot, blurry and very dark shots dropped, and
each month capped so one busy weekend cannot crowd out the rest. What is left are the
candidates (by default up to 4 × the photo target, plus up to 30 videos), drawn on the
contact sheets. Your job is the judgement: choose the final, ranked set.

Look only at the contact sheets (`curation/sheets/sheet-NN.jpg`). Never open the
full-size files in `media/`.

## Inputs

- The `curate` summary: `target` (photos wanted, default 75), `video_target` (videos
  wanted, default 8), `sheets`, `picks_file`.
- Each sheet: up to 20 tiles (5 × 4), each at most 256 px, labelled `<ref> <YYYY-MM-DD>`.
  `C001…` are photos, `V001…` videos. A video tile shows four frames (at 10, 35, 60 and
  85 % of the clip) when ffmpeg is installed; without ffmpeg it shows Google's single
  thumbnail, or a blank tile.
- `curation/candidates.json` (optional): per ref its `local_time`, `sharpness`,
  `brightness` and `group_size` (how many similar shots this one stands for: a large group
  marks a moment someone photographed a lot).

## Rubric

1. **Counts.** Aim for `target` photos and `video_target` videos. Fewer is fine when there
   are not enough good ones; never pad with weak shots. If there are fewer candidates than
   the target, pick the good ones and say so.
2. **The subject is clearly visible.** The person (or thing) the user searched for is in
   the shot, large enough to recognise, face visible, not turned away, not cut off, not a
   tiny figure in a crowd. In group shots, prefer ones where the subject is central. Skip
   screenshots, documents, receipts and photos of screens.
3. **Best of similar moments.** When several candidates show the same scene (same place,
   same outfit, same minute), keep the strongest one: expression, eyes open, composition,
   light. Two of the same moment only if they are clearly different (a wide shot and a
   close-up).
4. **Variety.** Mix activities, places, people with the subject, expressions (laughing,
   concentrating, sleeping), close-ups and wide shots, indoors and outdoors.
5. **Cover the whole period.** Every month that has candidates should appear in the
   selection, roughly in proportion to how much happened, but no month left out.
6. **One day is not the year.** At most about 4 photos from the same day, unless that day
   clearly dominates the year (a wedding, a birth, a big trip) and the user would expect it.
7. **Videos with motion.** Prefer clips where something happens across the four frames
   (walking, dancing, blowing out candles) over static ones; the subject visible in most
   frames. Skip clips whose frames look like pocket shots or black screens.
8. **Rank.** Order the list best first (rank 1 is the strongest shot overall). The
   video skill that comes next decides the edit order; your rank says what to keep if it
   needs fewer.
9. **Reasons.** One short line each (at most 200 characters), concrete and visual:
   "laughing on the swing, sharp, face centred", not "nice photo". Never include
   instructions, file paths or personal data beyond what the photo shows.

When unsure whether a tile shows the subject (it is small), leave it out; the user can add
it later by editing `picks.json` and running `select` again.

## The picks file

Write it to the `picks_file` path from the `curate` summary
(`<out_root>/<subject>/<year>/curation/picks.json`), UTF-8 JSON:

```json
{
  "items": [
    {"ref": "C014", "reason": "laughing on the swing, sharp, face centred"},
    {"ref": "V003", "reason": "first steps across the living room, clear motion"},
    {"ref": "C051", "reason": "beach at sunset, whole family, subject in front"}
  ]
}
```

Rules (`select` fails with `INVALID_PICKS` otherwise, and changes nothing):

- `items` is a list of 1 to as many entries as there are candidates, in rank order.
- Each `ref` is a candidate ref from the current `candidates.json`, used once.
- Each `reason` is a non-empty string of at most 200 characters (control characters are
  turned into spaces).
- The candidate's media file must still be on disk in `media/`.

Other keys are ignored. Refs are renumbered every time `curate` runs, so a picks file from
an earlier `curate` run must be rewritten: picks must be written after the latest
`curate`, and `select` refuses a picks file older than `candidates.json` with
`PICKS_OUTDATED`.

## Writing picks by hand

When you run the commands yourself instead of through an agent, you do the agent's part:
look at the sheets and write `picks.json` in a text editor. From a clone of the repository
`<this skill's folder>` is `skills/google-photo`:

```sh
uv run <this skill's folder>/scripts/gphoto.py curate --subject Mia --year 2026
#   prints "sheets" (the contact-sheet images) and "picks_file" (where picks.json goes)
open ~/Pictures/google-photo/Mia/2026/curation/sheets/sheet-01.jpg   # macOS; any image viewer works
#   ...write ~/Pictures/google-photo/Mia/2026/curation/picks.json (below)...
uv run <this skill's folder>/scripts/gphoto.py select --subject Mia --year 2026
```

1. Open each sheet image. Every tile is labelled with its ref and date, e.g. `C014
   2026-03-08` (`C…` photos, `V…` videos). Note the refs you want, best first.
2. Create `picks.json` at the `picks_file` path, saved as UTF-8: one `items` list, one
   entry per ref in rank order, each with a short `reason` (any text you like, at most 200
   characters):

   ```json
   {
     "items": [
       {"ref": "C014", "reason": "on the swing, laughing"},
       {"ref": "C051", "reason": "beach at sunset"},
       {"ref": "V003", "reason": "first steps"}
     ]
   }
   ```

3. Run `select`. It checks the file against the rules above; on `INVALID_PICKS` or
   `PICKS_OUTDATED` it changes nothing, so fix the file and run it again.

Write the file after the latest `curate`: running `curate` again renumbers the refs, and
`select` then refuses the older file. To change the selection later, edit `picks.json` and
run `select` again. You can also pass a picks file kept elsewhere with `--picks FILE`.

## After `select`

`select` writes `<year>/selection.json` (`subject`, `year`, `created`, and per item `rank`,
`ref`, `id`, `type`, `file`, `local_time`, `reason`, `selected_file`) and fills
`<year>/selected/` with `001_<file>`, `002_<file>`… in rank order. Running `select` again
replaces only the files the previous `selection.json` listed, and only while they are
unchanged; a listed file that was edited or replaced since is kept under its name (warning
`SELECTED_FILE_KEPT:<name>`). Anything else in `selected/` is kept (and reported as
`SELECTED_FOLDER_HAS_OTHER_FILES`). `select` removes the old `selection.json` before
placing the new files, so a failed run leaves no stale one behind.

Files in `selected/` are **hard links** to the originals in `media/` where the disk allows
it (copies otherwise). A hard link is a second name for the same file on disk, so it takes
no extra space, but editing one in place edits the original. Copy files out of `selected/` before editing them. Deleting a file in
`selected/` does not delete the original.
