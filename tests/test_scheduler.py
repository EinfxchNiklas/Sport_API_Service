from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import app.schedulers.scheduler as scheduler_module
from app.schedulers.scheduler import (
    get_job_history,
    get_scheduler,
    list_jobs,
    pause_job,
    resume_job,
    run_job_now,
    schedule_match_monitor,
    scheduler_status,
    shutdown_scheduler,
)

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture(autouse=True)
def reset_scheduler():
    """Ensure a clean scheduler singleton before and after each test."""
    # Reset singleton before test
    scheduler_module._scheduler = None
    yield
    # Tear down after test
    s = scheduler_module._scheduler
    if s is not None and s.running:
        s.shutdown(wait=False)
    scheduler_module._scheduler = None


def test_get_scheduler_returns_singleton():
    s1 = get_scheduler()
    s2 = get_scheduler()
    assert s1 is s2


def test_scheduler_timezone_berlin():
    s = get_scheduler()
    tz = s.timezone
    # APScheduler stores timezone as a tzinfo-like object; check its zone key
    tz_key = getattr(tz, "key", None) or getattr(tz, "zone", None) or str(tz)
    assert "Europe/Berlin" in tz_key


def test_schedule_match_monitor_adds_job():
    kickoff = datetime(2026, 8, 1, 18, 0, 0, tzinfo=BERLIN)
    job_id = schedule_match_monitor(match_id=1, kickoff_time=kickoff)

    assert job_id == "match-1"
    job = get_scheduler().get_job("match-1")
    assert job is not None
    assert job.id == "match-1"


def test_schedule_match_monitor_replaces_existing_job():
    s = get_scheduler()
    s.start()
    try:
        kickoff = datetime(2026, 8, 1, 18, 0, 0, tzinfo=BERLIN)
        schedule_match_monitor(match_id=1, kickoff_time=kickoff)
        schedule_match_monitor(match_id=1, kickoff_time=kickoff, duration_minutes=120)

        jobs = [j for j in s.get_jobs() if j.id == "match-1"]
        assert len(jobs) == 1
    finally:
        s.shutdown(wait=False)


def test_list_jobs_reflects_registered_jobs():
    s = get_scheduler()
    s.start()
    try:
        kickoff = datetime(2026, 8, 1, 18, 0, 0, tzinfo=BERLIN)
        schedule_match_monitor(match_id=42, kickoff_time=kickoff)
        jobs = list_jobs()
        job_ids = {j["id"] for j in jobs}
        assert "match-42" in job_ids
        entry = next(j for j in jobs if j["id"] == "match-42")
        assert entry["paused"] is False
        assert "trigger" in entry
    finally:
        s.shutdown(wait=False)


def test_pause_and_resume_job():
    s = get_scheduler()
    s.start()
    try:
        kickoff = datetime(2026, 8, 1, 18, 0, 0, tzinfo=BERLIN)
        schedule_match_monitor(match_id=7, kickoff_time=kickoff)

        pause_job("match-7")
        paused = next(j for j in list_jobs() if j["id"] == "match-7")
        assert paused["paused"] is True

        resume_job("match-7")
        resumed = next(j for j in list_jobs() if j["id"] == "match-7")
        assert resumed["paused"] is False
    finally:
        s.shutdown(wait=False)


def test_pause_job_unknown_raises_value_error():
    s = get_scheduler()
    s.start()
    try:
        with pytest.raises(ValueError):
            pause_job("does-not-exist")
    finally:
        s.shutdown(wait=False)


def test_run_job_now_unknown_raises_value_error():
    s = get_scheduler()
    s.start()
    try:
        with pytest.raises(ValueError):
            run_job_now("does-not-exist")
    finally:
        s.shutdown(wait=False)


def test_scheduler_status_shape():
    status = scheduler_status()
    assert set(status.keys()) == {"running", "enabled", "timezone", "job_count"}


def test_job_history_starts_empty_and_is_a_list():
    scheduler_module._job_history.clear()
    assert get_job_history() == []
