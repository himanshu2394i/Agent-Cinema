"""Parse a screenplay PDF into this production's vocabulary.

    python run_parse.py path/to/script.pdf

Auth comes from the environment, which google-genai reads on its own:

    GOOGLE_GENAI_USE_VERTEXAI=true
    GOOGLE_CLOUD_PROJECT=devpost-506321
    GOOGLE_CLOUD_LOCATION=us-central1

plus `gcloud auth application-default login` for the credentials themselves.
"""

import os
import sys

from google import genai

from parse_script import parse_screenplay


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        print("GOOGLE_CLOUD_PROJECT is not set - see the header of this file.")
        return 2

    with open(sys.argv[1], "rb") as handle:
        pdf = handle.read()

    vocabulary = parse_screenplay(pdf, genai.Client())

    for name in ("characters", "locations", "props", "scenes"):
        values = getattr(vocabulary, name)
        print(f"\n{name} ({len(values)})")
        for value in values:
            print(f"  {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
