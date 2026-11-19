import pytest

import app.schedulers.scheduler as scheduler_module
from app.schedulers.scheduler import (
    get_job_history,
    get_scheduler,
    list_jobs,
    pause_job,
    resume_job,
    run_job_now,
    scheduler_status,
    shutdown_scheduler,
)


def _dummy_job() -> None:
    return None


def _add_dummy(job_id: str) -> None:
    get_scheduler().add_job(_dummy_job, trigger="interval", hours=1, id=job_id, replace_existing=True)


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


def test_list_jobs_reflects_registered_jobs():
    s = get_scheduler()
    s.start()
    try:
        _add_dummy("dummy-42")
        jobs = list_jobs()
        job_ids = {j["id"] for j in jobs}
        assert "dummy-42" in job_ids
        entry = next(j for j in jobs if j["id"] == "dummy-42")
        assert entry["paused"] is False
        assert "trigger" in entry
    finally:
        s.shutdown(wait=False)


def test_pause_and_resume_job():
    s = get_scheduler()
    s.start()
    try:
        _add_dummy("dummy-7")

        pause_job("dummy-7")
        paused = next(j for j in list_jobs() if j["id"] == "dummy-7")
        assert paused["paused"] is True

        resume_job("dummy-7")
        resumed = next(j for j in list_jobs() if j["id"] == "dummy-7")
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
