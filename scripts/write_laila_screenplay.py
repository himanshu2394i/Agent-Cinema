"""Original short screenplay based on the public-domain Layla and Majnun legend.

Written for Dailies Triage vocabulary extraction — not a transcription of any
copyrighted 2018 (or other) film.
"""

import json
import sys
from pathlib import Path

# vocab.py lives in the repo root, one level up from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCREENPLAY = r"""
LAILA AND QAIS
An original vocabulary screenplay after the classical legend
(public-domain folk tale; not the 2018 feature)

FADE IN:

1  EXT. DESERT CAMP - DAY
QAYS, a young poet, watches LAILA among the tents of Banu Amir.
Children race past a water skin and a string of camels.

2  INT. TRIBAL SCHOOL TENT - DAY
QAYS and LAILA sit with other children. He writes her name on a slate.
The TEACHER raps a stick. Qays cannot look away.

3  EXT. PALM GROVE - DUSK
QAYS recites verse. Villagers mutter "MAJNUN" -- the mad one.
LAILA's FATHER listens, unsmiling.

4  INT. FATHER'S TENT - NIGHT
QAYS'S FATHER asks for LAILA's hand. LAILA'S FATHER refuses.
A marriage contract for IBN SALAM, a wealthy merchant, is already prepared.

5  EXT. OPEN DESERT - NIGHT
QAYS, now called MAJNUN, wanders with a torn cloak and a waterskin.
Wild gazelles keep him company. He carves LAILA's name on a rock.

6  INT. IBN SALAM'S HOUSE - NIGHT
LAILA sits apart from IBN SALAM. She will not speak of love.
A brass lamp, a letter she never sends.

7  EXT. KAABA - DAY
MAJNUN clings to the cloth of the shrine. He prays only that his love grow.

8  EXT. GRAVEYARD - DAWN
LAILA has died. MAJNUN finds her grave, recites three last verses, and falls.

FADE OUT.
"""

# Written out by hand rather than parsed, because parsing a screenplay is
# Gemini's job (`parse_screenplay`) and that costs one of twenty free-tier
# calls a day. These are the terms in SCREENPLAY above; keep the two in step.
VOCABULARY = {
    "characters": [
        "Qays", "Majnun", "Laila", "Laila's Father", "Qays's Father",
        "Ibn Salam", "Teacher", "Villagers", "Children",
    ],
    "locations": [
        "Desert Camp", "Tribal School Tent", "Palm Grove", "Father's Tent",
        "Open Desert", "Ibn Salam's House", "Kaaba", "Graveyard",
    ],
    "props": [
        "Waterskin", "Camels", "Slate", "Stick", "Marriage Contract",
        "Torn Cloak", "Gazelles", "Rock", "Brass Lamp", "Letter",
        "Shrine Cloth",
    ],
    # The legend screenplay is numbered, unlike the NOTLD draft, so real
    # logged rows can carry a scene instead of falling back to 'unknown'.
    "scenes": [str(n) for n in range(1, 9)],
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
    """Minimal one-font PDF so the onboard wizard can parse a real file."""
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        chunk = raw[:90] if raw else " "
        safe = chunk.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines.append(safe)
    y = 780
    content = ["BT", "/F1 11 Tf"]
    for line in lines:
        content.append(f"1 0 0 1 50 {y} Tm ({line}) Tj")
        y -= 14
        if y < 40:
            break
    content.append("ET")
    stream = "\n".join(content).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
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
    (root / "laila-majnun-legend-screenplay.txt").write_text(SCREENPLAY.strip() + "\n", encoding="utf-8")
    dest = Path("assets/projects/lailamajnu")
    dest.mkdir(parents=True, exist_ok=True)
    write_pdf(dest / "screenplay.pdf", SCREENPLAY)
    write_vocabulary(dest / "vocabulary.json")
    print("wrote", dest / "screenplay.pdf", "and", dest / "vocabulary.json")
