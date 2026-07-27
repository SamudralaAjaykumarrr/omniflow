import time

import pytest

from app import runner
from app.models import STATUS_ERROR, STATUS_PASSED, ScenarioRun
from app.scenarios import registry
from app.scenarios.base import ScenarioContext, ScenarioOutcome


def _wait_for_terminal(db_session, run_id, timeout_seconds: float = 5.0) -> ScenarioRun:
    """Polls until the background thread (app.runner._execute) has
    committed a terminal status — never a fixed guess-and-sleep, so the
    next test's `_clean_tables` truncation can never race a still-running
    thread from this one (that race produced a real, if harmless,
    StaleDataError warning before this helper existed)."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        db_session.expire_all()
        fresh = db_session.get(ScenarioRun, run_id)
        if fresh.status != "RUNNING":
            return fresh
        assert time.monotonic() < deadline, "background scenario execution did not finish in time"
        time.sleep(0.05)


def _fast_pass_entry():
    def _run(ctx: ScenarioContext) -> ScenarioOutcome:
        return ScenarioOutcome(status=STATUS_PASSED, summary="ok", diagnostics={"seen": True})

    def _reset(ctx: ScenarioContext) -> str:
        return "reset ok"

    return registry.ScenarioEntry(
        id="test-scenario",
        name="Test scenario",
        description="d",
        category="c",
        mechanism_reference="m",
        expected_failure_behavior="f",
        expected_recovery_behavior="r",
        run=_run,
        reset=_reset,
    )


def _crashing_entry():
    def _run(ctx: ScenarioContext) -> ScenarioOutcome:
        raise RuntimeError("boom")

    def _reset(ctx: ScenarioContext) -> str:
        return "reset ok"

    return registry.ScenarioEntry(
        id="test-crash-scenario",
        name="Test crash scenario",
        description="d",
        category="c",
        mechanism_reference="m",
        expected_failure_behavior="f",
        expected_recovery_behavior="r",
        run=_run,
        reset=_reset,
    )


def test_trigger_runs_in_the_background_and_persists_the_outcome(
    db_session, session_factory, monkeypatch
):
    monkeypatch.setitem(registry.REGISTRY, "test-scenario", _fast_pass_entry())

    run = runner.trigger(db_session, session_factory, "test-scenario")
    assert run.status == "RUNNING"

    fresh = _wait_for_terminal(db_session, run.id)

    assert fresh.status == STATUS_PASSED
    assert fresh.summary == "ok"
    assert fresh.diagnostics == {"seen": True}
    assert fresh.completed_at is not None


def test_trigger_unknown_scenario_raises_before_creating_a_row(db_session, session_factory):
    with pytest.raises(runner.UnknownScenarioError):
        runner.trigger(db_session, session_factory, "does-not-exist")
    assert runner.run_count(db_session, "does-not-exist") == 0


def test_a_crashing_scenario_is_recorded_as_error_not_left_running(
    db_session, session_factory, monkeypatch
):
    monkeypatch.setitem(registry.REGISTRY, "test-crash-scenario", _crashing_entry())

    run = runner.trigger(db_session, session_factory, "test-crash-scenario")
    fresh = _wait_for_terminal(db_session, run.id)

    assert fresh.status == STATUS_ERROR
    assert "boom" in fresh.error_message


def test_run_numbers_increment_per_scenario(db_session, session_factory, monkeypatch):
    monkeypatch.setitem(registry.REGISTRY, "test-scenario", _fast_pass_entry())

    first = runner.trigger(db_session, session_factory, "test-scenario")
    _wait_for_terminal(db_session, first.id)
    second = runner.trigger(db_session, session_factory, "test-scenario")
    _wait_for_terminal(db_session, second.id)

    assert first.run_number == 1
    assert second.run_number == 2


def test_reset_persists_a_scenario_reset_row(db_session, monkeypatch):
    monkeypatch.setitem(registry.REGISTRY, "test-scenario", _fast_pass_entry())

    row = runner.reset(db_session, "test-scenario")

    assert row.summary == "reset ok"
    latest = runner.latest_reset(db_session, "test-scenario")
    assert latest.id == row.id


def test_latest_run_and_history_order_most_recent_first(db_session, session_factory, monkeypatch):
    monkeypatch.setitem(registry.REGISTRY, "test-scenario", _fast_pass_entry())

    first = runner.trigger(db_session, session_factory, "test-scenario")
    _wait_for_terminal(db_session, first.id)
    second = runner.trigger(db_session, session_factory, "test-scenario")
    _wait_for_terminal(db_session, second.id)

    latest = runner.latest_run(db_session, "test-scenario")
    assert latest.id == second.id
    history = runner.run_history(db_session, "test-scenario")
    assert [h.run_number for h in history] == [2, 1]
