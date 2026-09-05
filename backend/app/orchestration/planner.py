"""
The planner interface and the deterministic development planner.  OWNER: P1.

THE SEAM THAT MATTERS.  `execute_plan()` contains no knowledge of the flagship.
It asks a Planner three questions:

    propose(task, decision)             -> Plan
    next_step(plan, observations)       -> PlanStep | None
    is_satisfied(plan, observations)    -> bool

A real, model-driven planner implements the same three methods by prompting the
reasoning agent with the accumulated observations and the tool schemas.  That is
`ModelPlanner` below - the seam is declared and left to P1's real-mode work, but
the EXECUTOR does not change when it lands.

Why `next_step` takes observations: a plan that is a fixed list executed in order
is a pipeline wearing a loop's clothes.  The signature is what makes revision
possible; MockPlanner exercises it via Scenario.revise, and
`test_orchestrator.py::test_observation_changes_next_step` proves a different
observation yields a different step.
"""

from __future__ import annotations

from typing import Optional, Protocol

from ..config import Settings
from ..contracts import Observation, Plan, PlanStep, RouterDecision, TaskEnvelope


class Planner(Protocol):
    async def propose(self, task: TaskEnvelope, decision: RouterDecision) -> Plan: ...

    async def next_step(
        self, plan: Plan, observations: list[Observation]
    ) -> Optional[PlanStep]: ...

    def is_satisfied(self, plan: Plan, observations: list[Observation]) -> bool: ...


def _renumber(plan: Plan) -> None:
    """Keep PlanStep.n equal to position, so the checklist numbering is stable
    after a revision inserts a step."""
    for idx, step in enumerate(plan.steps, start=1):
        step.n = idx


class MockPlanner:
    """Deterministic planner driven by a Scenario fixture.

    It is NOT a model.  What it demonstrates is that the executor asks for the
    next action each time round and that the answer can depend on what came
    back.  It demonstrates nothing about model reasoning quality.
    """

    simulated = True

    def __init__(self, scenario_key: str) -> None:
        from ..mocks.scenarios import get_scenario

        self.scenario = get_scenario(scenario_key)

    async def propose(self, task: TaskEnvelope, decision: RouterDecision) -> Plan:
        steps = [s.model_copy(deep=True) for s in self.scenario.initial_steps]
        return Plan(steps=steps, approved=False, revisions=0)

    async def next_step(
        self, plan: Plan, observations: list[Observation]
    ) -> Optional[PlanStep]:
        # IMPORTANT: return the OBJECT THAT LIVES IN plan.steps, never a copy.
        # The executor mutates step.status as the step runs, and the UI renders
        # plan.steps - hand back a copy and the checklist never ticks.
        pending = [s for s in plan.steps if s.status == "pending"]

        # 1. Ask the scenario whether the observations change the plan.
        if self.scenario.revise is not None:
            revised = self.scenario.revise(observations, pending)
            if revised is not None:
                plan.revisions += 1
                inserted = revised.model_copy(update={"status": "pending"})
                plan.steps.insert(len(observations), inserted)
                _renumber(plan)
                return inserted

        # 2. Otherwise take the next step that has not run.
        _renumber(plan)
        for step in plan.steps:
            if step.status == "pending":
                return step
        return None

    def is_satisfied(self, plan: Plan, observations: list[Observation]) -> bool:
        """Satisfied when no step is still pending."""
        return all(step.status != "pending" for step in plan.steps)


class ModelPlanner:
    """Real planner seam.  OWNER: P1, real-mode work.

    Contract to preserve when implementing:
      * `propose` prompts the reasoning agent with the task text, the router
        decision and registry.schemas() (the seven tool schemas), and parses a
        Plan.  Every proposed step is validated by PlanStep, so a hallucinated
        tool name fails validation before anything runs.
      * `next_step` re-prompts with the accumulated Observations and returns the
        next action, or None when done.  It may return a step NOT in the
        original plan - the executor will then request a fresh approval if the
        step is outside the approved scope (approvals.in_scope).
      * `is_satisfied` may consult the model, but must also return True when the
        model returns no further action.

    Acceptance (P1): with SETU_MOCK_MODE=0, a text-only task produces a plan of
    1-5 validated steps, and the second call to next_step reflects the first
    step's observation.
    """

    simulated = False

    def __init__(self, settings: Settings, agents, registry) -> None:
        self.settings = settings
        self.agents = agents
        self.registry = registry

    async def propose(self, task: TaskEnvelope, decision: RouterDecision) -> Plan:
        raise NotImplementedError(
            "ModelPlanner is the real-mode planner seam (owner: P1). "
            "Run with SETU_MOCK_MODE=1 to use the deterministic planner."
        )

    async def next_step(
        self, plan: Plan, observations: list[Observation]
    ) -> Optional[PlanStep]:
        raise NotImplementedError("ModelPlanner.next_step (owner: P1)")

    def is_satisfied(self, plan: Plan, observations: list[Observation]) -> bool:
        raise NotImplementedError("ModelPlanner.is_satisfied (owner: P1)")


def build_planner(settings: Settings, scenario_key: str, agents=None, registry=None) -> Planner:
    """The one place mock and real diverge for planning.

    A mock scenario can NEVER activate in real mode: this raises rather than
    quietly substituting fixtures for model output.
    """
    if settings.mock_mode:
        return MockPlanner(scenario_key)
    return ModelPlanner(settings, agents, registry)
