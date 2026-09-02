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


def test_refuses_zero_or_negative_count():
    with pytest.raises(ValueError, match="count must be positive"):
        cut_plan(duration_s=6000.0, clip_s=60.0, count=0)
    with pytest.raises(ValueError, match="count must be positive"):
        cut_plan(duration_s=6000.0, clip_s=60.0, count=-3)


def test_cover_plan_tiles_usable_duration_without_gaps():
    from clips import cover_plan

    plan = cover_plan(duration_s=600.0, clip_s=60.0)
    assert plan == [
        (0.0, 60.0),
        (60.0, 120.0),
        (120.0, 180.0),
        (180.0, 240.0),
        (240.0, 300.0),
        (300.0, 360.0),
        (360.0, 420.0),
        (420.0, 480.0),
        (480.0, 540.0),
        (540.0, 600.0),
    ]


def test_cover_plan_keeps_a_short_final_clip():
    from clips import cover_plan

    plan = cover_plan(duration_s=650.0, clip_s=60.0)
    assert plan[-1] == (600.0, 650.0)
    assert len(plan) == 11
    for (_, prev_end), (next_start, _) in zip(plan, plan[1:]):
        assert next_start == prev_end


def test_cover_plan_skips_credits_then_covers_the_rest():
    from clips import cover_plan

    plan = cover_plan(duration_s=6000.0, clip_s=60.0, trim_s=120.0)
    assert plan[0][0] == 120.0
    assert plan[-1][1] == 5880.0
    assert plan[0][1] - plan[0][0] == 60.0


def test_cover_plan_refuses_nonpositive_clip_length():
    from clips import cover_plan

    with pytest.raises(ValueError, match="clip"):
        cover_plan(duration_s=6000.0, clip_s=0)
    with pytest.raises(ValueError, match="clip"):
        cover_plan(duration_s=6000.0, clip_s=-45)
