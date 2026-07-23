"""Tests for the smoke runner and report (jarvis/smoke/).

The pty-driven CLIAdapter is exercised end to end by `python -m jarvis.smoke`;
here the platform is faked at the SmokeAdapter seam so the runner's logic —
expectation matching, adapter-error capture, platform filtering, report
rendering — is tested without spawning a process or touching a terminal.
"""

from jarvis.smoke.adapter import SmokeAdapter
from jarvis.smoke.report import render_report
from jarvis.smoke.runner import run_scenario, run_suite


class _FakeAdapter:
    """A scripted stand-in for a real platform driver (cli/web/mobile).

    ``replies`` maps an action to the output it should return; an action with no
    entry returns "". If ``fail_on_open`` is set, ``open`` raises — the way a real
    interface that never came up would.
    """

    platform = "cli"

    def __init__(self, replies=None, fail_on_open=False):
        self._replies = replies or {}
        self._fail = fail_on_open
        self.closed = False

    def open(self):
        if self._fail:
            raise RuntimeError("interface did not start")

    def send(self, action):
        return self._replies.get(action, "")

    def close(self):
        self.closed = True


def test_fake_adapter_satisfies_the_protocol():
    assert isinstance(_FakeAdapter(), SmokeAdapter)


def test_all_steps_meet_expectations_is_a_pass():
    scn = {"name": "s", "platform": "cli", "steps": [
        {"action": "config show", "expect": "temperature"},
    ]}
    r = run_scenario(_FakeAdapter({"config show": "temperature = 0.7"}), scn)
    assert r.passed
    assert r.steps[0].capture == "temperature = 0.7"


def test_a_missing_expectation_fails_the_scenario():
    scn = {"name": "s", "platform": "cli", "steps": [
        {"action": "config show", "expect": "top_k"},
    ]}
    r = run_scenario(_FakeAdapter({"config show": "temperature = 0.7"}), scn)
    assert not r.passed
    assert "not found" in r.steps[0].note


def test_a_step_without_an_expectation_passes_and_records_its_capture():
    scn = {"name": "s", "platform": "cli", "steps": [{"action": "help"}]}
    r = run_scenario(_FakeAdapter({"help": "Commands"}), scn)
    assert r.passed
    assert r.steps[0].expect is None


def test_an_adapter_that_fails_to_open_is_a_scenario_error_not_a_crash():
    scn = {"name": "s", "platform": "cli", "steps": [{"action": "help"}]}
    r = run_scenario(_FakeAdapter(fail_on_open=True), scn)
    assert not r.passed
    assert r.error is not None and "did not start" in r.error


def test_close_is_always_called():
    fake = _FakeAdapter({"help": "Commands"})
    run_scenario(fake, {"name": "s", "steps": [{"action": "help"}]})
    assert fake.closed


def test_run_suite_only_runs_scenarios_for_the_requested_platform():
    scenarios = [
        {"name": "cli-one", "platform": "cli", "steps": []},
        {"name": "web-one", "platform": "web", "steps": []},
    ]
    results = run_suite(lambda: _FakeAdapter(), scenarios, "cli")
    assert [r.name for r in results] == ["cli-one"]


def test_report_shows_pass_fail_and_the_captured_output():
    scn = {"name": "roundtrip", "platform": "cli", "steps": [
        {"action": "config show", "expect": "temperature"},
    ]}
    r = run_scenario(_FakeAdapter({"config show": "temperature = 0.7"}), scn)
    text = render_report([r])
    assert "1/1 passed" in text
    assert "[PASS] roundtrip" in text
    assert "temperature = 0.7" in text  # the capture is in the report


def test_report_diagnoses_where_a_failure_happened():
    scn = {"name": "broken", "platform": "cli", "steps": [
        {"action": "config show", "expect": "nope"},
    ]}
    r = run_scenario(_FakeAdapter({"config show": "temperature = 0.7"}), scn)
    text = render_report([r])
    assert "WHERE IT BROKE" in text
    assert "broken" in text
