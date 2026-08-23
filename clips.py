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
