# Agentic Cinema — Remaining Work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the working dailies-triage prototype to a submittable hackathon entry: one coherent production's vocabulary across real and synthetic footage, running on Google Cloud, deployed, documented, and written up.

**Architecture:** The pipeline already works end to end — a screenplay generates a controlled vocabulary, Gemini logs clips against it, rows land in ClickHouse, and an ADK agent answers questions through the official ClickHouse MCP server. What remains is coherence (one vocabulary everywhere), real matched footage, migration from an AI Studio key to Vertex, deployment, and submission materials.

**Tech Stack:** Python 3.12, google-genai, google-adk, mcp-clickhouse, clickhouse-connect, ClickHouse Cloud, Vertex AI, Cloud Run.

## Global Constraints

- Python 3.12; all commands run through `.venv/Scripts/python.exe` on Windows.
- Tests: `pytest`, run with `.venv/Scripts/python.exe -m pytest -q`. Currently 44 passing. Never let this number go down.
- TDD: write the failing test, run it, confirm the failure reason, implement, confirm pass, commit.
- Secrets live only in `.env` (gitignored). Never commit a key, host, or password.
- `assets/` is gitignored — media and the vocabulary cache are local only.
- ClickHouse table is `shots`; column order comes from `INSERT_COLUMNS` in `db.py`, never hand-written.
- Every insert must carry a fresh `insert_deduplication_token` — ClickHouse silently drops identical blocks.
- Hackathon requires: Gemini + Google Cloud, and ClickHouse used **at runtime via the official MCP server**.
- Commit messages end with: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## Current State

Working and verified:

- `vocab.py` — `CRAFT_VOCAB` (fixed) + `ProjectVocabulary` (screenplay-derived), `enum_of()`
- `parse_script.py` — `parse_screenplay(pdf_bytes, client, model)` → `ProjectVocabulary`
- `shot_schema.py` — `MODEL_FIELDS` drives `shot_response_schema()`, `clickhouse_ddl()`, `agent_instruction()`
- `ingest.py` — `log_clip(video_uri, vocabulary, client, model, source_file)` → validated rows
- `synth.py` — `generate_rows()`, `demo_vocabulary()`
- `db.py` — `connect()`, `insert_rows()`, `replace_clip()`, `load()`, `demo()`
- `smoke.py` — screenplay → vocabulary → clip → rows → ClickHouse
- `dailies_agent/agent.py` — ADK `LlmAgent` + `McpToolset` over `mcp-clickhouse`

Live: 2,000,018 rows in ClickHouse (2M synthetic + 18 real from `sintel_trailer.mp4`).

Gaps this plan closes:

1. The agent's prompt is built from `demo_vocabulary()` (invented names), but the real ingested rows used the *Night of the Living Dead* vocabulary. Two vocabularies in one table.
2. The only real footage is a Sintel trailer, which has nothing to do with the NOTLD screenplay.
3. Running on an AI Studio key, not Google Cloud.
4. No `requirements.txt`, not deployed.
5. No README, no submission materials.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `vocab.py` | Vocabulary types + cache loading | Modify — add `load_vocabulary()` |
| `synth.py` | Synthetic rows + archive vocabulary | Modify — `demo_vocabulary()` derives from the real one |
| `parse_script.py` | Screenplay → vocabulary | Modify — prompt excludes non-embodied cues |
| `clips.py` | Cut source footage into clips | Create |
| `ingest_all.py` | Batch-ingest a directory of clips | Create |
| `dailies_agent/agent.py` | The query agent | Modify — container-safe server lookup |
| `requirements.txt` | Deployment dependencies | Create |
| `README.md` | Project documentation | Create |
| `docs/SUBMISSION.md` | Devpost copy + demo script | Create |

---

### Task 1: One vocabulary across the whole archive

`synth.py:demo_vocabulary()` invents characters ("Sarah", "Det. Ruiz") while real ingested rows use the parsed NOTLD vocabulary. The agent is told about the invented ones. Fix: the parsed screenplay becomes the single source, and synthetic rows borrow it.

**Files:**
- Modify: `vocab.py` (add `load_vocabulary`)
- Modify: `synth.py:demo_vocabulary`
- Modify: `parse_script.py:PROMPT`
- Test: `test_vocab.py`, `test_synth.py`

**Interfaces:**
- Consumes: `ProjectVocabulary` from `vocab.py`
- Produces: `vocab.load_vocabulary(path) -> ProjectVocabulary`; `synth.demo_vocabulary()` returns the parsed vocabulary with synthetic scene ids attached.

- [ ] **Step 1: Write the failing test for cache loading**

Append to `test_vocab.py` (add `import json` and `import pytest` at the top if absent):

```python
def test_load_vocabulary_reads_a_cached_parse(tmp_path):
    from vocab import load_vocabulary

    cache = tmp_path / "vocabulary.json"
    cache.write_text(json.dumps({
        "characters": ["Ben", "Barbara"], "locations": ["Farmhouse"],
        "props": ["Tyre Iron"], "scenes": [],
    }))
    pv = load_vocabulary(cache)
    assert pv.characters == ["Ben", "Barbara"]
    assert pv.locations == ["Farmhouse"]


def test_load_vocabulary_errors_clearly_when_missing(tmp_path):
    from vocab import load_vocabulary

    with pytest.raises(FileNotFoundError, match="smoke.py"):
        load_vocabulary(tmp_path / "nope.json")
```

- [ ] **Step 2: Run it and confirm the failure**

Run: `.venv/Scripts/python.exe -m pytest test_vocab.py -q`

Expected: FAIL with `ImportError: cannot import name 'load_vocabulary'`

- [ ] **Step 3: Implement `load_vocabulary`**

Add `import json` and `from pathlib import Path` to the top of `vocab.py`, then append:

```python
VOCABULARY_CACHE = Path("assets/vocabulary.json")


def load_vocabulary(path: Path = VOCABULARY_CACHE) -> ProjectVocabulary:
    """Load a vocabulary parsed earlier from a screenplay.

    Values are already normalised, so this constructs directly rather than
    going through from_raw.
    """
    if not Path(path).exists():
        raise FileNotFoundError(
            f"No vocabulary at {path}. Run smoke.py against a screenplay first."
        )
    return ProjectVocabulary(**json.loads(Path(path).read_text()))
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/Scripts/python.exe -m pytest test_vocab.py -q`

Expected: PASS

- [ ] **Step 5: Write the failing test for the shared archive vocabulary**

Append to `test_synth.py`:

```python
def test_demo_vocabulary_uses_the_parsed_screenplay(tmp_path, monkeypatch):
    import json
    import synth
    from vocab import ProjectVocabulary

    cache = tmp_path / "vocabulary.json"
    cache.write_text(json.dumps({
        "characters": ["Ben", "Barbara"], "locations": ["Farmhouse", "Cellar"],
        "props": ["Tyre Iron"], "scenes": [],
    }))
    monkeypatch.setattr(synth, "VOCABULARY_CACHE", cache)

    pv = synth.demo_vocabulary()
    assert isinstance(pv, ProjectVocabulary)
    # Characters come from the screenplay, not from invented names.
    assert pv.characters == ["Ben", "Barbara"]
    assert "Sarah" not in pv.characters
    # Scene ids stay synthetic: the archive spans many productions.
    assert len(pv.scenes) > 100
    assert pv.scenes[0].startswith("P01-")
```

- [ ] **Step 6: Run it and confirm the failure**

Run: `.venv/Scripts/python.exe -m pytest test_synth.py -q`

Expected: FAIL — `demo_vocabulary` returns hardcoded names, so `pv.characters == ["Ben", "Barbara"]` fails.

- [ ] **Step 7: Rewrite `demo_vocabulary`**

Replace the existing `from vocab import ...` line in `synth.py` with:

```python
import dataclasses

from vocab import CRAFT_VOCAB, VOCABULARY_CACHE, ProjectVocabulary, load_vocabulary
```

Replace the whole `demo_vocabulary` function with:

```python
def demo_vocabulary() -> ProjectVocabulary:
    """The archive's vocabulary: one screenplay's words, many productions' scenes.

    Characters, locations and props come from the parsed screenplay so the
    synthetic filler and the real logged clips speak the same language, and
    the agent only has to be told one set of values.

    Scene ids stay synthetic and production-prefixed ("P07-14B") because two
    million clips is a studio archive, not one shoot - a feature's dailies
    run to a few thousand. Without that spread the table holds a hundred
    distinct setups and every specific filter returns nothing.
    """
    base = load_vocabulary(VOCABULARY_CACHE)
    return dataclasses.replace(base, scenes=[
        f"P{p:02d}-{n}{s}"
        for p in range(1, 41)
        for n in range(1, 40)
        for s in ("", "A", "B")
    ])
```

- [ ] **Step 8: Run and confirm pass**

Run: `.venv/Scripts/python.exe -m pytest -q`

Expected: PASS, 46 tests. If other `test_synth.py` tests fail because `assets/vocabulary.json` is missing, regenerate it:

```bash
.venv/Scripts/python.exe smoke.py assets/notld_1968_screenplay.pdf assets/sintel_trailer.mp4
```

- [ ] **Step 9: Stop the parser inventing characters from dialogue cues**

The 1968 parse returned `Announcer`, `Commentator` and `Voice` as characters. They are cue labels, not people, and one got attached to a shot. In `parse_script.py`, replace this part of `PROMPT`:

```
characters - every named character with a dialogue cue or a named appearance
  in the action. Use the name as written in the cue. Ignore (V.O.), (O.S.)
  and (CONT'D) decorations.
```

with:

```
characters - every named character who physically appears on screen. Use the
  name as written in the cue, ignoring (V.O.), (O.S.) and (CONT'D)
  decorations. Exclude labels that denote a disembodied source rather than a
  person on camera - VOICE, ANNOUNCER, COMMENTATOR, NEWSCASTER, RADIO,
  TELEVISION - unless the script shows them in frame.
```

- [ ] **Step 10: Re-parse to pick up the improved prompt**

```bash
rm assets/vocabulary.json
.venv/Scripts/python.exe smoke.py assets/notld_1968_screenplay.pdf assets/sintel_trailer.mp4
```

Expected: the printed `characters` list no longer contains `Announcer`, `Commentator` or `Voice`. If it still does, the model judges them to appear on camera — check the screenplay before overriding, and record the decision in the commit message.

- [ ] **Step 11: Confirm the agent now speaks the real vocabulary**

```bash
.venv/Scripts/python.exe -c "from dailies_agent.agent import root_agent; print(root_agent.instruction[:600])"
```

Expected: the listed characters are the NOTLD cast (Ben, Barbara, Harry, Helen, Judy, Tom), not Sarah or Det. Ruiz.

- [ ] **Step 12: Rebuild the synthetic archive on the new vocabulary**

The 2M existing rows still carry invented names. Replace them:

```bash
.venv/Scripts/python.exe -c "from db import connect; connect().command('TRUNCATE TABLE shots')"
.venv/Scripts/python.exe db.py load 2000000
```

The `"every take Sarah handles the letter"` entry in `DEMO_QUERIES` in `db.py` will now return 0. Find real replacements:

```bash
.venv/Scripts/python.exe -c "from synth import demo_vocabulary as v; print(v().characters); print(v().props[:12])"
```

Then edit that entry in `db.py` to use a character and prop that exist, for example:

```python
    "every take Ben handles the tyre iron": f"""
        SELECT count() FROM {TABLE}
        WHERE has(characters, 'Ben') AND has(props, 'Tyre Iron')""",
```

Verify:

```bash
.venv/Scripts/python.exe db.py demo
```

Expected: every query returns a non-zero count.

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "One vocabulary across real and synthetic footage

The archive now speaks the screenplay's language throughout: synthetic rows
borrow the parsed characters, locations and props, and only the scene ids
stay invented, because two million clips is an archive rather than one shoot.

The parse prompt now excludes disembodied cues - ANNOUNCER and VOICE were
being logged as people.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: A matched corpus — real Night of the Living Dead footage

The screenplay is already parsed. The film is public domain and on archive.org, so script and footage finally describe the same production. This is what makes the demo honest.

**Files:**
- Create: `clips.py`
- Create: `ingest_all.py`
- Test: `test_clips.py`

**Interfaces:**
- Consumes: `ingest.log_clip`, `db.connect`, `db.replace_clip`, `vocab.load_vocabulary`
- Produces: `clips.cut_plan(duration_s, clip_s, count, trim_s) -> list[tuple[float, float]]`, `clips.duration_of(path) -> float`, `clips.cut(video, out_dir, clip_s, count, trim_s) -> list[Path]`; `ingest_all.main()` CLI over a directory.

- [ ] **Step 1: Install ffmpeg**

```bash
winget install --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
```

Then in a **new** terminal check `ffmpeg -version`. If it is not on PATH, locate it with `where.exe ffmpeg`.

- [ ] **Step 2: Download the film**

List the available files and pick the smallest mp4:

```bash
curl -s https://archive.org/metadata/Night_Of_The_Living_Dead_raw_HD_WS | .venv/Scripts/python.exe -c "import json,sys; [print(f['name'], f.get('size')) for f in json.load(sys.stdin)['files'] if f['name'].endswith('.mp4')]"
```

Then download it into `assets/notld_full.mp4`:

```bash
curl -L -o assets/notld_full.mp4 "https://archive.org/download/Night_Of_The_Living_Dead_raw_HD_WS/<filename-from-above>"
```

- [ ] **Step 3: Write the failing test for the cut plan**

Create `test_clips.py`:

```python
import pytest

from clips import cut_plan


def test_spreads_clips_across_the_whole_film():
    plan = cut_plan(duration_s=6000.0, clip_s=60.0, count=10)
    assert len(plan) == 10
    starts = [s for s, _ in plan]
    assert starts == sorted(starts)
    assert starts[0] >= 0
    assert plan[-1][1] <= 6000.0


def test_clips_do_not_overlap():
    plan = cut_plan(duration_s=1200.0, clip_s=60.0, count=5)
    for (_, prev_end), (next_start, _) in zip(plan, plan[1:]):
        assert next_start >= prev_end


def test_skips_the_opening_and_closing_credits():
    # Credits are title cards, not coverage - they teach the agent nothing.
    plan = cut_plan(duration_s=6000.0, clip_s=60.0, count=4, trim_s=120.0)
    assert plan[0][0] >= 120.0
    assert plan[-1][1] <= 6000.0 - 120.0


def test_refuses_a_plan_that_will_not_fit():
    with pytest.raises(ValueError, match="does not fit"):
        cut_plan(duration_s=100.0, clip_s=60.0, count=5)
```

- [ ] **Step 4: Run and confirm the failure**

Run: `.venv/Scripts/python.exe -m pytest test_clips.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'clips'`

- [ ] **Step 5: Implement `clips.py`**

```python
"""Cut a feature into evenly spread clips that stand in for dailies.

A finished film is not dailies - it has no takes and no slate - but its
shots are real photography with real coverage, which is what the logger
needs to be tested against.

    python clips.py assets/notld_full.mp4 assets/clips 20 45
"""

import subprocess
import sys
from pathlib import Path


def cut_plan(
    duration_s: float, clip_s: float, count: int, trim_s: float = 0.0
) -> list[tuple[float, float]]:
    """Evenly spaced, non-overlapping (start, end) pairs across the film.

    `trim_s` drops that much from each end, to skip credits.
    """
    usable = duration_s - 2 * trim_s
    if usable < clip_s * count:
        raise ValueError(
            f"{count} clips of {clip_s}s does not fit in {usable}s of usable film"
        )
    stride = usable / count
    return [
        (round(trim_s + i * stride, 1), round(trim_s + i * stride + clip_s, 1))
        for i in range(count)
    ]


def duration_of(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def cut(video: Path, out_dir: Path, clip_s: float, count: int,
        trim_s: float) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = cut_plan(duration_of(video), clip_s, count, trim_s)
    written = []
    for index, (start, end) in enumerate(plan, start=1):
        # Reel/clip naming mirrors a camera roll, so source_file reads like
        # something an assistant editor would recognise.
        target = out_dir / f"A001_C{index:04d}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start),
             "-i", str(video), "-t", str(end - start),
             "-c:v", "libx264", "-c:a", "aac", str(target)],
            check=True,
        )
        print(f"  {target.name}  {start:.0f}s-{end:.0f}s")
        written.append(target)
    return written


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    clip_s = float(sys.argv[4]) if len(sys.argv) > 4 else 45.0
    cut(Path(sys.argv[1]), Path(sys.argv[2]), clip_s, count, trim_s=120.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run and confirm pass**

Run: `.venv/Scripts/python.exe -m pytest test_clips.py -q`

Expected: PASS, 4 tests.

- [ ] **Step 7: Cut the clips**

```bash
.venv/Scripts/python.exe clips.py assets/notld_full.mp4 assets/clips 20 45
```

Expected: `A001_C0001.mp4` … `A001_C0020.mp4` in `assets/clips`, each about 45 seconds.

- [ ] **Step 8: Write `ingest_all.py`**

No new test: it is a loop over `log_clip`, which `test_ingest.py` already covers with 11 tests, and the only added behaviour is per-clip error reporting that the batch prints.

```python
"""Ingest a directory of clips into ClickHouse.

    python ingest_all.py assets/clips

One clip at a time, on purpose. A failure mid-batch leaves everything already
logged in place, and re-running is always safe - replace_clip makes each clip
idempotent, so the right move after any failure is to run it again.
"""

import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from db import connect, replace_clip
from ingest import log_clip
from vocab import load_vocabulary


def upload(video: Path, client):
    handle = client.files.upload(file=str(video))
    while handle.state.name == "PROCESSING":
        time.sleep(2)
        handle = client.files.get(name=handle.name)
    if handle.state.name != "ACTIVE":
        raise RuntimeError(f"upload ended in state {handle.state.name}")
    return handle.uri


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    load_dotenv()
    client = genai.Client()
    db = connect()
    vocabulary = load_vocabulary()

    videos = sorted(Path(sys.argv[1]).glob("*.mp4"))
    if not videos:
        print(f"no .mp4 files in {sys.argv[1]}")
        return 1

    total, failed = 0, []
    for index, video in enumerate(videos, start=1):
        print(f"[{index}/{len(videos)}] {video.name}", flush=True)
        try:
            start = time.perf_counter()
            rows = log_clip(upload(video, client), vocabulary, client,
                            source_file=video.name)
            written = replace_clip(db, rows)
            total += written
            print(f"    {written} shots in {time.perf_counter() - start:.0f}s")
        except Exception as error:
            print(f"    FAILED: {type(error).__name__}: {error}")
            failed.append(video.name)

    print(f"\n{total} shots from {len(videos) - len(failed)}/{len(videos)} clips")
    if failed:
        print("failed: " + ", ".join(failed))
        print("re-run to retry - already-logged clips are replaced, not duplicated")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 9: Ingest the corpus**

```bash
.venv/Scripts/python.exe ingest_all.py assets/clips
```

Expected: roughly 25-85 seconds per clip, so 10-30 minutes for 20 clips. Free-tier rate limits will likely bite — if you see 429s, do Task 3 first and come back.

- [ ] **Step 10: Verify the corpus is real and queryable**

```bash
.venv/Scripts/python.exe -c "from db import connect; c = connect(); print('clips:', c.query(\"SELECT uniq(source_file) FROM shots WHERE source_file LIKE 'A001_%'\").result_rows[0][0]); print('shots:', c.query(\"SELECT count() FROM shots WHERE source_file LIKE 'A001_%'\").result_rows[0][0]); [print(' ', r) for r in c.query(\"SELECT source_file, shot_size, characters, action FROM shots WHERE source_file LIKE 'A001_%' AND notEmpty(characters) LIMIT 5\").result_rows]"
```

Expected: named NOTLD characters appearing in real logged shots, not `unknown`. If everything is `unknown`, the vocabulary and the footage have drifted apart — confirm `assets/vocabulary.json` came from the NOTLD screenplay.

- [ ] **Step 11: Ask the agent about the real footage**

```bash
echo "Which clips show Ben inside the farmhouse?" | .venv/Scripts/adk.exe run dailies_agent
```

Expected: it names `A001_C####.mp4` files. This is the demo moment — capture it.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "Add a matched corpus: real Night of the Living Dead footage

clips.py cuts the public-domain feature into camera-roll-named clips and
ingest_all.py logs the batch. Script and footage now describe the same
production, so characters resolve to real names instead of unknown.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Move to Vertex AI

> **AMENDED 2026-08-23:** the billing account has no credits, so this task is DROPPED. Do not link billing - it would charge a real card. Staying on the AI Studio free tier. Revisit only if the hackathon's $100 credit grant arrives.

An AI Studio key does not satisfy "powered by Gemini and Google Cloud", and its free tier dies after about one query a minute. Both problems have the same fix.

**Files:**
- Modify: `.env`, `.env.example`
- Modify: `parse_script.py:DEFAULT_MODEL`, `ingest.py:DEFAULT_MODEL`, `dailies_agent/agent.py`
- Modify: `ingest_all.py` (switch to `gs://`)

**Interfaces:**
- Consumes: `ingest.log_clip` (already accepts `gs://`)
- Produces: no code interface change — `genai.Client()` switches backend by environment variable alone.

- [ ] **Step 1: Check the credit balance before linking anything**

Open **console.cloud.google.com/billing**, select **My Billing Account 2** (`0187B3-8B0A24-6CD50F` — the only open account of the three), then **Credits** in the left menu. Note the amount and expiry.

If there are no credits, stop: submit the hackathon's $100 credit form instead (1-5 business days) and keep working on the API key meanwhile. Linking a billing account with no credits means real charges to a real card.

- [ ] **Step 2: Link the project**

```bash
gcloud billing projects link devpost-506321 --billing-account=0187B3-8B0A24-6CD50F
```

- [ ] **Step 3: Confirm the link and enable the API**

```bash
gcloud billing projects describe devpost-506321
```

Expected: `billingEnabled: true`

```bash
gcloud services enable aiplatform.googleapis.com
```

- [ ] **Step 4: Find out which model ids Vertex actually serves**

Availability differs between AI Studio and Vertex, and between Vertex regions. Do not assume `gemini-3.6-flash` carries over.

```bash
GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=devpost-506321 GOOGLE_CLOUD_LOCATION=us-central1 .venv/Scripts/python.exe -c "from google import genai; [print(m.name) for m in genai.Client().models.list() if 'gemini' in m.name]"
```

- [ ] **Step 5: Probe the shortlist for real availability**

Listing is not availability — on the API key, three listed models turned out to be 404 or 503.

Create `probe_models.py`:

```python
"""Which model ids can this project actually call? Delete after use."""

import os

from google import genai

os.environ.update(
    GOOGLE_GENAI_USE_VERTEXAI="true",
    GOOGLE_CLOUD_PROJECT="devpost-506321",
    GOOGLE_CLOUD_LOCATION="us-central1",
)

CANDIDATES = [
    "gemini-3.6-flash", "gemini-3.5-flash",
    "gemini-3.1-pro-preview", "gemini-2.5-pro",
]

client = genai.Client()
for model in CANDIDATES:
    try:
        client.models.generate_content(model=model, contents="Reply with: ok")
        print(f"{model:26} OK")
    except Exception as error:
        print(f"{model:26} {type(error).__name__} {str(error)[:80]}")
```

Run it:

```bash
.venv/Scripts/python.exe probe_models.py
```

Pick the best flash model that returns OK. If a pro model is affordable now, prefer it for `ingest.py` only — video logging is the quality-critical call and runs as a batch, where latency does not matter. Delete `probe_models.py` afterwards; it is a throwaway.

- [ ] **Step 6: Switch the environment**

Edit `.env`:

```
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=devpost-506321
GOOGLE_CLOUD_LOCATION=us-central1
AGENT_MODEL=<the flash model that passed>
```

Delete the `GOOGLE_API_KEY` line — leaving it risks silently falling back to the metered path. Mirror the change in `.env.example` with an empty placeholder.

- [ ] **Step 7: Update the model constants**

Set `DEFAULT_MODEL` in both `parse_script.py` and `ingest.py` to the confirmed model, and the fallback in `dailies_agent/agent.py:root_agent` to the flash one.

- [ ] **Step 8: Re-verify the pipeline on Vertex**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: all tests pass. They are offline, so this only proves nothing broke syntactically.

```bash
.venv/Scripts/python.exe smoke.py assets/notld_1968_screenplay.pdf assets/clips/A001_C0001.mp4
```

Expected: a parse and a clip log, both through Vertex.

```bash
echo "Which clips show Ben inside the farmhouse?" | .venv/Scripts/adk.exe run dailies_agent
```

Expected: same answer quality as on the API key, without a 429.

- [ ] **Step 9: Move ingest to Cloud Storage**

Vertex reads `gs://` directly, so clips no longer need uploading through this process.

```bash
gcloud storage buckets create gs://devpost-506321-dailies --location=us-central1
gcloud storage cp assets/clips/*.mp4 gs://devpost-506321-dailies/clips/
```

In `ingest_all.py`, replace the `log_clip(upload(video, client), ...)` call with:

```python
            rows = log_clip(f"gs://devpost-506321-dailies/clips/{video.name}",
                            vocabulary, client, source_file=video.name)
```

The `upload` helper can then be deleted from `ingest_all.py` — `log_clip` already accepts `gs://`, and `test_ingest.py` covers that path.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Run on Vertex AI instead of an AI Studio key

Satisfies the hackathon's Google Cloud requirement and removes the free-tier
rate limit that capped us at roughly one agent query a minute. Ingest now
reads clips straight from Cloud Storage, so video bytes no longer pass
through the ingest process.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Deploy the agent

> **AMENDED 2026-08-23:** Steps 1-2 are done. Steps 3-6 are DROPPED - Cloud Run needs a billing account on the project and there are no credits. The project ships undeployed.

Phase 5 of the brief asks for a deployed agent, and "production-ready" is in the challenge text. The agent spawns `mcp-clickhouse` as a subprocess, so the container must contain it.

**Files:**
- Create: `requirements.txt`
- Modify: `dailies_agent/agent.py` (container-safe server lookup)

**Interfaces:**
- Consumes: `dailies_agent.agent.root_agent`
- Produces: a deployed HTTPS endpoint.

- [ ] **Step 1: Write `requirements.txt`**

Write the direct dependencies by hand rather than freezing, so the image is not pinned to incidental packages:

```
google-adk
google-genai
mcp<2
mcp-clickhouse
clickhouse-connect
python-dotenv
```

`mcp<2` is not cosmetic — ADK 2.7.1 imports `mcp.shared.session.ProgressFnT`, which mcp 2.0 removed. Installing mcp 2.x breaks the agent at import time.

- [ ] **Step 2: Make the MCP server discoverable inside the container**

`dailies_agent/agent.py` looks for `mcp-clickhouse` next to `sys.executable`. Widen the lookup so a container layout also resolves:

```python
SERVER = (
    shutil.which("mcp-clickhouse", path=SCRIPTS)
    or shutil.which("mcp-clickhouse")
    or "mcp-clickhouse"
)
```

Confirm it still resolves locally:

```bash
.venv/Scripts/python.exe -c "from dailies_agent.agent import SERVER; print(SERVER)"
```

Expected: an absolute path ending in `mcp-clickhouse.EXE`, not the bare string.

- [ ] **Step 3: Deploy to Cloud Run**

ADK ships the deploy command; do not hand-write a Dockerfile.

```bash
.venv/Scripts/adk.exe deploy cloud_run --project=devpost-506321 --region=us-central1 --service_name=dailies-agent --with_ui dailies_agent
```

- [ ] **Step 4: Give the service its credentials**

The container has no `.env`. Put the password in Secret Manager — this is what Phase 5's "Studio Secrets" link is about — and the rest in plain env vars:

```bash
gcloud secrets create clickhouse-password --data-file=-
```

(Type the password, then Ctrl+Z and Enter on Windows to end input. Do not put it in a shell argument, where it lands in history.)

```bash
gcloud run services update dailies-agent --region=us-central1 --set-env-vars=CLICKHOUSE_HOST=tblno83wun.ap-south-1.aws.clickhouse.cloud,CLICKHOUSE_PORT=8443,CLICKHOUSE_USER=default,CLICKHOUSE_SECURE=true,GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=devpost-506321,GOOGLE_CLOUD_LOCATION=us-central1 --set-secrets=CLICKHOUSE_PASSWORD=clickhouse-password:latest
```

- [ ] **Step 5: Verify the deployment answers a real question**

```bash
gcloud run services describe dailies-agent --region=us-central1 --format="value(status.url)"
```

Open that URL, select the `dailies` agent, and ask: *Which clips show Ben inside the farmhouse?*

Expected: the same answer the local agent gives. If the tool call fails, read the logs:

```bash
gcloud run services logs read dailies-agent --region=us-central1 --limit=50
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt dailies_agent/agent.py
git commit -m "Deploy the agent to Cloud Run

Direct dependencies pinned in requirements.txt; mcp is held below 2.0 because
ADK imports a symbol that release removed. ClickHouse credentials come from
Cloud Run env vars with the password in Secret Manager.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: README

The repository is 16 files with no explanation. A judge reading it cold needs the idea, the architecture, and a way to run it.

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write it**

Create `README.md`:

```markdown
# Dailies Triage

An assistant editor that watches your footage and lets you ask for shots in
plain English.

> *"Which takes of scene 14B have Ben holding the tyre iron, before dark?"*

## The problem

Every shooting day produces hours of footage. Someone watches all of it
overnight and writes down what is in each clip - who is in frame, how close
the camera is, whether the take was usable. That is called logging, it is done
by hand, and it is the reason nobody can find anything three weeks later.

## How it works

    SCREENPLAY (pdf)
          |  Gemini extracts the cast, locations and props
          v
    PROJECT VOCABULARY  ------------------+
          |                               |
          v                               v
    FOOTAGE --> Gemini logs each shot   AGENT PROMPT
                against that vocabulary   |
          |                               |
          v                               |
      ClickHouse  <--- MCP ---------------+
                       (official mcp-clickhouse server)

The screenplay is the schema. Every production names its own characters,
locations and props, so the vocabulary is generated per project rather than
hardcoded - and because the same vocabulary constrains what Gemini may write
and tells the agent what it may filter on, the two cannot drift apart.

That matters more than it sounds. If the logger writes `"wide shot"` and the
agent filters for `'wide'`, every query returns nothing while every component
reports success. One field table in `shot_schema.py` generates the Gemini
response schema, the ClickHouse DDL and the agent's prompt, and a test fails
if they ever disagree.

## Layout

| File | What it does |
|---|---|
| `vocab.py` | Fixed cinematographic vocabulary + the per-project one |
| `parse_script.py` | Screenplay PDF to vocabulary |
| `shot_schema.py` | The one field table, and the three artefacts it generates |
| `ingest.py` | One clip to validated shot rows |
| `clips.py` | Cuts a feature into camera-roll-named clips |
| `ingest_all.py` | Batch ingest a directory |
| `synth.py` | Synthetic dailies, for testing search at archive scale |
| `db.py` | ClickHouse connection, schema, bulk load |
| `dailies_agent/` | The ADK agent |
| `smoke.py` | Whole pipeline in one run |

## Running it

    python -m venv .venv
    .venv/Scripts/python.exe -m pip install -r requirements.txt
    cp .env.example .env    # then fill it in

    .venv/Scripts/python.exe db.py init
    .venv/Scripts/python.exe smoke.py script.pdf clip.mp4
    .venv/Scripts/adk.exe web

## Tests

    .venv/Scripts/python.exe -m pytest -q

No test makes a network call. The Gemini client is injected everywhere, so the
whole pipeline is testable without a key.

## Credits

Test assets are *Night of the Living Dead* (1968), public domain.
```

- [ ] **Step 2: Check every command in it actually runs**

Work through the Running-it block on a clean shell. A README with a wrong command is worse than no README.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Add README

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Devpost submission

**Files:**
- Create: `docs/SUBMISSION.md`

- [ ] **Step 1: Draft the submission copy**

Create `docs/SUBMISSION.md` with these sections:

**Inspiration** — an assistant editor logs dailies by hand, overnight, every night of a shoot. Weeks later a director asks for "the take where she's holding the letter and the light was still warm", and someone goes digging.

**What it does** — parses the screenplay into a controlled vocabulary, has Gemini log every shot against it, stores the result in ClickHouse, and answers plain-English questions about the footage with clip names and timecodes.

**How we built it** — Gemini for screenplay parsing and video logging, ADK for the agent, the official ClickHouse MCP server for retrieval at runtime, Cloud Run for hosting.

**Challenges** — the three real ones, which are the strongest part of the story:

1. A fixed vocabulary cannot describe every production, so the screenplay generates it.
2. ClickHouse silently drops identical insert blocks, so re-logging a clip wrote nothing and reported success.
3. An empty result looks identical to an empty archive, so the agent follows an explicit protocol before it says "no footage".

**Accomplishments** — the write and read vocabularies are generated from one source and a test fails if they diverge; 62 ms filtered queries over 2M shots.

**What we learned** — availability is not the same as listing; three Gemini models appeared in `models.list()` but were not callable.

**What's next** — unscripted footage needs a two-pass vocabulary; continuity checking reuses the same pipeline.

**Built with** — `google-gemini`, `google-adk`, `vertex-ai`, `clickhouse`, `mcp`, `cloud-run`, `python`

- [ ] **Step 2: Write the demo video script**

Two minutes, in this order. Do not open with architecture.

1. **0:00-0:20 — the problem.** A folder of 20 identically named clips. "An assistant editor watches all of this overnight and writes down what is in it."
2. **0:20-0:40 — the screenplay.** Run `smoke.py`; show the cast and locations appearing out of the PDF. "The script is the schema."
3. **0:40-1:10 — the logging.** Show shots streaming out of one clip: shot size, characters, action. "Nobody typed any of this."
4. **1:10-1:40 — the payoff.** Ask the agent *"Which clips show Ben inside the farmhouse?"* and get named clips back. Then ask for something that is not there and show it saying so honestly.
5. **1:40-2:00 — the scale.** `db.py demo` — 2 million shots, 62 ms. Say plainly that beyond the real clips the archive is synthetic.

Record the terminal at a readable font size. Judges watch on laptops.

- [ ] **Step 3: Rotate the exposed credentials**

The ClickHouse password and the AI Studio key were both pasted into a chat transcript during development.

- ClickHouse Cloud console → your service → Settings → reset the `default` password, then update `.env` and the Cloud Run secret.
- AI Studio → delete the old key. Vertex is doing the work now, so nothing needs replacing.

- [ ] **Step 4: Final check before submitting**

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
git status --short
```

```bash
git ls-files | grep -E "\.env$|\.pdf|\.mp4"
```

Expected: all tests pass, nothing uncommitted, and the last command returns nothing.

- [ ] **Step 5: Commit**

```bash
git add docs/SUBMISSION.md
git commit -m "Add submission copy and demo script

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Dependency Order

Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6

Tasks 1 and 2 change what the demo *is*; everything after is packaging. Task 3 unblocks doing Task 2 at any real scale, so if rate limits bite during Task 2, jump to Task 3 and come back.

Tasks 5 and 6 need nothing from Tasks 3 and 4 except the deployed URL, so they can be drafted in parallel while a deployment is in flight.
