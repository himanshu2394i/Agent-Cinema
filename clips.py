"""Cut a feature into clips that stand in for dailies.

A finished film is not dailies - it has no takes and no slate - but its
shots are real photography with real coverage, which is what the logger
needs to be tested against.

Sample N windows across the film (gaps between clips):

    python clips.py assets/notld_full.mp4 assets/clips 20 45

Tile the usable duration with no gaps (last clip may be shorter):

    python clips.py assets/notld_full.mp4 assets/clips cover 45
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
    if count <= 0:
        raise ValueError(f"count must be positive, got {count}")
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


def cover_plan(
    duration_s: float, clip_s: float, trim_s: float = 0.0
) -> list[tuple[float, float]]:
    """Back-to-back (start, end) pairs covering usable film, no sampling gaps.

    `trim_s` still drops credits at each end. The last clip is shorter when
    usable duration is not an exact multiple of `clip_s`.
    """
    if clip_s <= 0:
        raise ValueError(f"clip length must be positive, got {clip_s}")
    start = trim_s
    end_limit = duration_s - trim_s
    usable = end_limit - start
    if usable <= 0:
        raise ValueError(f"no usable film after trim_s={trim_s} on {duration_s}s")
    plan: list[tuple[float, float]] = []
    t = start
    while t + clip_s <= end_limit + 1e-9:
        plan.append((round(t, 1), round(t + clip_s, 1)))
        t += clip_s
    if end_limit - t >= 1.0:
        plan.append((round(t, 1), round(end_limit, 1)))
    return plan


def duration_of(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def cut(video: Path, out_dir: Path, clip_s: float, count: int,
        trim_s: float, cover: bool = False) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = duration_of(video)
    plan = (
        cover_plan(duration, clip_s, trim_s)
        if cover
        else cut_plan(duration, clip_s, count, trim_s)
    )
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
    cover = len(sys.argv) > 3 and sys.argv[3] == "cover"
    if cover:
        clip_s = float(sys.argv[4]) if len(sys.argv) > 4 else 45.0
        cut(Path(sys.argv[1]), Path(sys.argv[2]), clip_s, count=0,
            trim_s=120.0, cover=True)
    else:
        count = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        clip_s = float(sys.argv[4]) if len(sys.argv) > 4 else 45.0
        cut(Path(sys.argv[1]), Path(sys.argv[2]), clip_s, count, trim_s=120.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
