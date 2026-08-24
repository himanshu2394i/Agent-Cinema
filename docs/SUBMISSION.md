# Dailies Triage — Devpost submission

## Inspiration

An assistant editor logs dailies by hand, overnight, every night of a shoot -
writing down who's in each clip, how close the camera is, whether the take is
usable. Weeks later a director asks for "the take where she's holding the
letter and the light was still warm," and someone goes digging through
handwritten logs to find it.

## What it does

Dailies Triage parses a screenplay into a controlled vocabulary - the cast,
locations, and props that production actually uses - then has Gemini log
every shot of footage against that vocabulary: shot size, characters,
location, props, time of day, quality. The result lands in ClickHouse as
structured rows, and an agent answers plain-English questions about the
footage ("which clips show Ben inside the farmhouse?") with named clips and
timecodes, by writing real SQL against those rows.

We've run this on real footage, not just a demo case: *Night of the Living
Dead* (1968) cut into 20 camera-roll-named clips, all of them logged into
ClickHouse as 177 shot rows. Characters resolve to names pulled from the
screenplay - Ben, Barbara - not `unknown`. One logged action line, verbatim
from the database: "Ben lifts and positions a heavy wooden table top against
the window" - the barricading scene, and nobody typed that description.
Asked "which clips show Ben indoors?", the agent queried ClickHouse over MCP
and came back with 12 correctly-named clips.

## How we built it

Gemini for both stages of the pipeline - parsing the screenplay PDF into a
vocabulary, and logging each video clip against it - called through the
Gemini API with an AI Studio key (no cloud project, no billing). Google ADK
runs the agent, run locally with `adk web`. Retrieval at query time goes
through the official `mcp-clickhouse` MCP server, so the agent talks to
ClickHouse the same way any MCP client would, not through a bespoke wrapper.

## Challenges we ran into

**A fixed vocabulary can't describe every production.** A period drama has
oil lamps; a sci-fi has plasma rifles. Hardcoding a vocabulary means it's
wrong for the next screenplay. So the vocabulary isn't fixed - the screenplay
generates it. Gemini reads the script once and extracts that production's
cast, locations, and props, and that becomes the only vocabulary Gemini is
allowed to use when logging shots and the only one the agent is allowed to
filter on. One field table (`shot_schema.py`) generates the Gemini response
schema, the ClickHouse DDL, and the agent's prompt from the same source, and
a test fails if the DDL and response schema ever cover different fields.
That test checks field names, not the allowed values for each field - it
would not catch, for example, the agent's prompt describing values that a
different subset of rows actually carries.

**ClickHouse silently drops identical insert blocks.** ClickHouse hashes each
inserted block for deduplication, and a repeat of the same block is dropped
- by design, for retry safety. But re-logging a clip whose shots happened to
come out identical to a previous run hit that exact case: the insert wrote
nothing, and the client reported success. Nothing crashed; the data just
wasn't there. Fixed by giving every insert a fresh
`insert_deduplication_token`, so each logging run is treated as new rather
than as a retry of the last one.

**An empty query result looks exactly like an empty archive.** If the agent
searches for `'wide'` but the logger wrote `"wide shot"`, the query returns
zero rows - identical to what a genuinely empty archive would return - and
every component along the way reports success. So the agent follows an
explicit protocol before it will tell a user "no footage": check any literal
value against the vocabulary first, drop filters one at a time to see which
one is empty, and fall back to searching the free-text prose fields before
giving up.

**A worthwhile side effect of building the vocabulary this way:** we tested
the video logger against a deliberately mismatched vocabulary - the cast list
from *Night of the Living Dead* run against unrelated *Sintel* trailer
footage, which shares none of those characters. Rather than forcing a match,
Gemini returned `unknown` for nearly every character it logged. That's the
escape hatch the vocabulary provides working as intended, even under
adversarial input it was never designed for.

**A "just retry" fix that cost a full day's quota.** The Gemini free tier
caps out at 20 requests per model per day. Our first ingest batch over 20
clips left one unlogged after a transient 503, and the tool's own advice was
"re-run to retry" - correct about correctness, ruinous about cost. The
re-run re-sent all 20 clips, including the 19 already safely in ClickHouse,
and burned the entire day's allowance without ever reaching the one clip
that actually needed it. The fix: the batch now checks ClickHouse for what's
already logged before calling Gemini, and skips it. A retry now costs one
request instead of twenty. Verified live: 19 skipped, 1 attempted.

## Accomplishments that we're proud of

The write side (what Gemini may log) and the read side (what the agent may
filter on) are generated from the same source table, and a test fails the
build if the columns Gemini can write and the columns the agent's schema
describes ever differ - the field-name half of drift can't happen unnoticed.
It does not check that the *values* on both sides agree, which is a real gap:
a scene vocabulary can still describe values that only a subset of the
table's rows can have.

This isn't just theory anymore: all 20 clips cut from *Night of the Living
Dead* are logged in ClickHouse as **177 real shot rows**, resolved against a
vocabulary the same screenplay generated. Those 177 rows sit alongside a
**2,000,000-row synthetic archive** used purely to stress-test query
performance at scale - the two are never mixed together in a claim: 177 is
what Gemini actually watched and logged, 2,000,000 is a synthetic load test.

We also measured query performance against that 2-million-row synthetic
archive in ClickHouse. From `db.py demo` against the live database:

| Query | Latency |
|---|---|
| `count()` over all 2,000,000 rows | 49 ms |
| filtered: wide shots at golden hour, exactly 2 characters | 231 ms |
| filtered: clean takes of one scene, ordered, limited to 5 | 139 ms |
| filtered: every take where a named character handles a named prop | 79 ms |

None of these are vector search or an approximate index - they're `SELECT`
statements against structured columns, which is why an editor hunting one
specific take gets a complete answer, not an approximately-similar one.

## What we learned

Availability is not the same as listing. Four Gemini model ids showed up
when we called `models.list()` against our project, and none of them were
actually callable at the time: `gemini-2.5-flash` returned a 404 (not
available to new accounts), `gemini-3.7-flash` and `gemini-flash-latest`
both returned 503 (temporarily unavailable), and `gemini-3.1-pro-preview`
returned 429 (quota exceeded). The model that ended up doing all the work in
this project wasn't the first one we tried - it was whichever one actually
answered.

## What's next

Unscripted footage (interviews, documentary coverage) has no screenplay to
generate a vocabulary from, so that path needs a two-pass approach - a first
pass over the footage itself to propose a vocabulary, then logging against
it. Continuity checking - flagging when a prop or costume detail
contradicts an earlier shot of the same scene - is a straightforward reuse
of the same logging pipeline, since it's asking the same "does this match
the established facts" question the vocabulary already answers.

## Built with

`google-gemini`, `google-adk`, `clickhouse`, `mcp`, `python`

---

# Demo video script (2:00)

Record the terminal at a large, readable font size - judges are watching on
laptops, often at reduced window size.

**0:00–0:20 — the problem.** Show a folder of clips with identical
camera-roll names (`A004_C0834.mp4`, `A004_C0835.mp4`, ...). *"An assistant
editor watches all of this overnight and writes down what's in it. That's
called logging, and it's why nobody can find anything three weeks later."*

**0:20–0:40 — the screenplay.** Run `smoke.py` against the screenplay PDF.
Show the cast and locations appearing in the parsed vocabulary as it prints.
*"The script is the schema - every production names its own characters and
locations, so we generate the vocabulary from the screenplay instead of
hardcoding one."*

**0:40–1:10 — the logging.** Continue the `smoke.py` run into the clip-logging
step. Show shots streaming out for one clip: shot size, characters, action,
as Gemini logs them. *"Nobody typed any of this."*

**1:10–1:40 — the payoff.** Open the agent (`adk web`) and ask *"Which clips
show Ben inside the farmhouse?"* - get named clips and timecodes back. Then
ask for something that isn't in the footage, and show the agent saying so
honestly instead of guessing.

**1:40–2:00 — the scale.** Run `db.py demo` on camera. Point at the numbers
as they print - a `count()` in well under 100 ms, filtered queries in the
same range, against millions of rows. *"That's what filtered search over
this many shots looks like. 177 of these rows are real - 20 clips of *Night
of the Living Dead* we just logged. The other 2 million are synthetic, added
on top to prove the query pattern holds at scale."*
