"""
StageAgent — the per-stage agent contract.

The mentor's definition of an agent: a class for a specific task, with an input
contract, an output contract, a system prompt, and (later) registered tools.
Each FSM stage is owned by one StageAgent subclass; they are composed from the
shared abstractions (LLMEngine, prompt builder, storages) rather than talking to
a provider directly.

Stage completion is signalled with explicit control markers that the model emits
and that we parse deterministically in code — the same "LLM signals, code decides"
pattern as the invariant checker's "OK". Markers are added to the prompt only on
orchestrator-driven runs and are stripped from the displayed reply.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

# Control markers a stage agent may emit. The model signals; code decides.
MARKER_READY = "[[READY]]"          # stage's work is complete -> advance / present approval gate
MARKER_NEEDS_USER = "[[NEEDS_USER]]"  # stage needs a free-text answer from the user (question gate)
MARKER_STEP_DONE = "[[STEP_DONE]]"  # execution: this plan step is done, more remain (stay in stage)

ALL_MARKERS = (MARKER_READY, MARKER_NEEDS_USER, MARKER_STEP_DONE)

# Gate kinds — how the driver must pause.
GATE_QUESTION = "question"   # agent asked something; read a free-text answer and continue
GATE_APPROVAL = "approval"   # present a Confirm / Reject choice at a critical decision point


def parse_markers(text: str) -> tuple[str, set[str]]:
    """Strip any control markers from text. Returns (clean_text, markers_found)."""
    found: set[str] = set()
    clean = text
    for marker in ALL_MARKERS:
        if marker in clean:
            found.add(marker)
            clean = clean.replace(marker, "")
    clean = "\n".join(line.rstrip() for line in clean.splitlines()).strip()
    return clean, found


@dataclass
class StageVerdict:
    """The interpreted outcome of running a stage once."""
    clean_text: str = ""
    ready: bool = False           # output contract satisfied -> auto-advance on the forward edge
    continue_stage: bool = False  # made progress, more work remains -> re-run this same stage
    gate: str | None = None       # GATE_QUESTION / GATE_APPROVAL -> the driver must pause
    next_target: str | None = None     # forward target when ready (None = default forward edge)
    confirm_target: str | None = None  # approval gate: where Confirm advances to
    reject_target: str | None = None   # approval gate: where Reject reworks (may be current stage)
    expected_action: str = ""     # machine-readable next action (see below)


# Machine-readable expected_action vocabulary (stored on the task).
EXPECTED_AWAIT_USER = "await_user"
EXPECTED_READY_TO_PLAN = "ready_to_plan"
EXPECTED_AWAIT_PLAN_APPROVAL = "await_plan_approval"
EXPECTED_READY_TO_VALIDATE = "ready_to_validate"
EXPECTED_AWAIT_DONE_APPROVAL = "await_done_approval"
EXPECTED_IN_PROGRESS = "in_progress"
EXPECTED_STEP_DONE = "step_done"
EXPECTED_DONE = "done"


class StageAgent(ABC):
    """Base class for the agent that owns one FSM stage."""

    stage: str = ""

    @abstractmethod
    def system_fragment(self, task: dict) -> str:
        """The stage's role, added to the system prompt (single source for chat + autorun)."""

    @abstractmethod
    def entry_message(self, task: dict) -> str:
        """The opening user message when the orchestrator runs this stage."""

    @abstractmethod
    def marker_protocol(self) -> str:
        """Instruction (added only on orchestrator runs) telling the model which markers to emit."""

    @abstractmethod
    def interpret(self, markers: set[str]) -> StageVerdict:
        """Turn the parsed markers into a verdict (readiness / gate / branch target)."""

    def input_ready(self, task: dict) -> tuple[bool, str]:
        """Input contract / precondition. Returns (ok, reason_if_not). Default: always ready."""
        return True, ""

    def record(self, task: dict, clean_text: str, verdict: StageVerdict) -> None:
        """Persist this stage's durable output. Subclasses extend (plan, current_step, …)."""
        task.setdefault("stage_outputs", {})[self.stage] = clean_text

    def process(self, task: dict, raw_text: str) -> StageVerdict:
        """Parse markers, interpret, persist outputs, and stamp expected_action on the task."""
        clean, markers = parse_markers(raw_text)
        verdict = self.interpret(markers)
        verdict.clean_text = clean
        self.record(task, clean, verdict)
        task["expected_action"] = verdict.expected_action
        return verdict
