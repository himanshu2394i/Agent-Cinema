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
