"""Original beat-sheet screenplay based on the public-domain Layla and Majnun legend.

Written for Dailies Triage vocabulary extraction — not a transcription of any
copyrighted 2018 (or other) film. Long enough to read like a real breakdown
source (numbered scenes, locations, cast, props), not a one-page summary.
"""

import json
import sys
from pathlib import Path

# vocab.py lives in the repo root, one level up from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCREENPLAY = r"""
LAILA AND QAIS
An original beat-sheet screenplay after the classical legend
(public-domain folk tale; not the 2018 feature)

FADE IN:

1  EXT. DESERT CAMP - DAY
QAYS and LAILA, children of rival clans, watch camel drivers water their herds.

2  INT. TRIBAL SCHOOL TENT - DAY
QAYS writes LAILA's name on a slate. The TEACHER raps a stick. Children laugh.

3  EXT. PALM GROVE - DUSK
QAYS recites verse beneath the palms. Villagers whisper the name MAJNUN.

4  INT. FATHER'S TENT - NIGHT
QAYS'S FATHER asks for LAILA's hand. LAILA'S FATHER refuses; a contract for IBN SALAM waits.

5  EXT. WEDDING ROUTE - DAY
Drummers and a wedding litter pass the camp. LAILA watches from behind a veil.

6  INT. IBN SALAM'S HOUSE - NIGHT
LAILA sits apart from IBN SALAM. A brass lamp, a letter she never sends.

7  EXT. OPEN DESERT - NIGHT
QAYS, now MAJNUN, wanders with a torn cloak and a waterskin. Wild gazelles follow.

8  EXT. MADMAN'S ROCK - DAWN
MAJNUN carves LAILA's name into stone with a stick. Wind scours the letters.

9  EXT. OASIS SPRING - DAY
Villagers drive MAJNUN away from the water. Children throw stones.

10  INT. MOTHER'S TENT - NIGHT
QAYS'S MOTHER pleads with him to return. He answers only in verse.

11  EXT. TOWN GATE - DAY
Town elders mock MAJNUN. A rival poet challenges his rhyme and loses.

12  EXT. CARAVAN ROAD - DUSK
NAWFAL, a prince and friend, finds MAJNUN starving. He offers bread; MAJNUN refuses.

13  INT. NAWFAL'S PAVILION - NIGHT
NAWFAL listens to MAJNUN's lament. He vows to plead with LAILA's tribe.

14  EXT. DESERT CAMP - DAY
NAWFAL negotiates with LAILA'S FATHER. Guards turn him away at the tent flap.

15  INT. LAILA'S CHAMBER - NIGHT
LAILA hears MAJNUN's verses carried on the wind. She presses a letter to her chest.

16  EXT. MARKET SQUARE - DAY
A messenger sells gossip: the mad poet still lives. LAILA buys a shrine cloth.

17  EXT. OPEN DESERT - NIGHT
MAJNUN sleeps among gazelles. A wedding singer's voice echoes from far away.

18  EXT. KAABA - DAY
MAJNUN clings to the shrine cloth. Pilgrims stare. He prays only that love endure.

19  EXT. MECCA COURTYARD - DAY
Pilgrims circle the Kaaba. MAJNUN is dragged aside by guards, still reciting.

20  EXT. OPEN DESERT - DUSK
MAJNUN returns barefoot, thinner. He drinks from a cracked waterskin.

21  INT. IBN SALAM'S HOUSE - NIGHT
IBN SALAM hears rumors of LAILA's silence. He locks the brass lamp away.

22  EXT. PALM GROVE - DAWN
LAILA walks alone where she once met QAYS. Fallen dates litter the path.

23  EXT. DESERT CAMP - DAY
LAILA'S FATHER forbids her name spoken in camp. Wedding guests depart early.

24  INT. LAILA'S CHAMBER - NIGHT
LAILA burns a letter unread. Smoke rises through the tent roof.

25  EXT. OPEN DESERT - DAY
A messenger finds MAJNUN and calls LAILA's name. He collapses, laughing.

26  INT. MOTHER'S TENT - NIGHT
QAYS'S MOTHER tells MAJNUN that LAILA still lives. He does not believe her.

27  EXT. MADMAN'S ROCK - DUSK
MAJNUN re-carves LAILA's name. Blood on his palms mixes with dust.

28  EXT. IBN SALAM'S HOUSE - DAY
Servants carry a shuttered litter away. Town elders lower their eyes.

29  INT. LAILA'S CHAMBER - NIGHT
LAILA whispers verses. Ibn Salam listens outside the curtain, unmoved.

30  EXT. GRAVEYARD - DAWN
A fresh grave. Mourners scatter rose petals. No one speaks MAJNUN's name.

31  EXT. OPEN DESERT - DAY
The messenger reaches MAJNUN with news of LAILA's death. He goes still.

32  EXT. CARAVAN ROAD - DUSK
MAJNUN walks toward the graveyard, cloak trailing. Gazelles keep their distance.

33  EXT. GRAVEYARD - NIGHT
MAJNUN finds LAILA's grave by moonlight. He lays the shrine cloth across it.

34  EXT. GRAVEYARD - DAWN
MAJNUN recites three last verses beside the grave. He falls across the mound.

35  EXT. GRAVEYARD - DAY
Villagers find two graves side by side. Nawfal places a rock between them.

36  EXT. DESERT CAMP - DUSK
Children sing an old song. Camels pass. The camp forgets, then remembers.

FADE OUT.
"""

# Written out by hand rather than parsed, because parsing a screenplay is
# Gemini's job (`parse_screenplay`) and that costs quota. Keep SCREENPLAY and
# VOCABULARY in sync — every named element in the script should appear here.
VOCABULARY = {
    "characters": [
        "Qays",
        "Majnun",
        "Laila",
        "Laila's Father",
        "Qays's Father",
        "Qays's Mother",
        "Ibn Salam",
        "Nawfal",
        "Teacher",
        "Messenger",
        "Wedding Singer",
        "Rival Poet",
        "Town Elders",
        "Pilgrims",
        "Villagers",
        "Children",
        "Servants",
        "Mourners",
        "Camel Drivers",
    ],
    "locations": [
        "Desert Camp",
        "Tribal School Tent",
        "Palm Grove",
        "Father's Tent",
        "Wedding Route",
        "Ibn Salam's House",
        "Laila's Chamber",
        "Open Desert",
        "Madman's Rock",
        "Oasis Spring",
        "Mother's Tent",
        "Town Gate",
        "Market Square",
        "Caravan Road",
        "Nawfal's Pavilion",
        "Kaaba",
        "Mecca Courtyard",
        "Graveyard",
    ],
    "props": [
        "Waterskin",
        "Camels",
        "Slate",
        "Stick",
        "Marriage Contract",
        "Torn Cloak",
        "Gazelles",
        "Rock",
        "Brass Lamp",
        "Letter",
        "Shrine Cloth",
        "Wedding Litter",
        "Veil",
        "Drums",
        "Bread",
        "Rose Petals",
        "Curtain",
        "Fallen Dates",
    ],
    "scenes": [str(n) for n in range(1, 37)],
}


def write_vocabulary(path: Path) -> None:
    """Normalise through the same path parse_screenplay would, then cache it."""
    from vocab import ProjectVocabulary

    vocabulary = ProjectVocabulary.from_raw(**VOCABULARY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "characters": vocabulary.characters,
                "locations": vocabulary.locations,
                "props": vocabulary.props,
                "scenes": vocabulary.scenes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def write_pdf(path: Path, text: str) -> None:
    """Minimal multi-page PDF so long beat sheets are not truncated."""
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        chunk = raw[:90] if raw else " "
        safe = chunk.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines.append(safe)

    page_streams: list[bytes] = []
    y = 780
    content = ["BT", "/F1 10 Tf"]
    for line in lines:
        if y < 40:
            content.append("ET")
            page_streams.append("\n".join(content).encode("latin-1", "replace"))
            content = ["BT", "/F1 10 Tf"]
            y = 780
        content.append(f"1 0 0 1 50 {y} Tm ({line}) Tj")
        y -= 12
    content.append("ET")
    page_streams.append("\n".join(content).encode("latin-1", "replace"))

    # Object layout: 1 catalog, 2 pages, 3..(2+N) page objs, font, content streams
    n_pages = len(page_streams)
    font_obj = 3 + n_pages * 2
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
    ]
    kid_refs = " ".join(f"{3 + i * 2} 0 R" for i in range(n_pages))
    objects.append(
        f"<< /Type /Pages /Kids [{kid_refs}] /Count {n_pages} >>".encode()
    )
    for i, stream in enumerate(page_streams):
        page_num = 3 + i * 2
        content_num = page_num + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {content_num} 0 R "
                f"/Resources << /Font << /F1 {font_obj} 0 R >> >> >>"
            ).encode()
        )
        objects.append(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    out = bytearray(b"%PDF-1.1\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(bytes(out))


if __name__ == "__main__":
    root = Path("docs")
    root.mkdir(exist_ok=True)
    (root / "laila-majnun-legend-screenplay.txt").write_text(
        SCREENPLAY.strip() + "\n", encoding="utf-8"
    )
    dest = Path("assets/projects/lailamajnu")
    dest.mkdir(parents=True, exist_ok=True)
    write_pdf(dest / "screenplay.pdf", SCREENPLAY)
    write_vocabulary(dest / "vocabulary.json")
    print(
        f"wrote {dest / 'screenplay.pdf'} ({len(VOCABULARY['scenes'])} scenes) "
        f"and {dest / 'vocabulary.json'}"
    )
