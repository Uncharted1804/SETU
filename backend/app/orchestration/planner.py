"""
The planner interface and the deterministic development planner.  OWNER: P1.

THE SEAM THAT MATTERS.  `execute_plan()` contains no knowledge of the flagship.
It asks a Planner three questions:

    propose(task, decision)             -> Plan
    next_step(plan, observations)       -> PlanStep | None
    is_satisfied(plan, observations)    -> bool

A real, model-driven planner implements the same three methods by prompting the
REASONING MODEL - the `planning` capability from config/models.yaml, reached
through llm/ollama_client.py - with the accumulated observations and the tool
schemas.  Not `agents/reasoning.py`: an agent's job is to draft the content of
one step, and agents/base.py states that agents do not decide what runs next,
which is precisely this class's job.  See docs/DECISIONS.md D-019.  That is
`ModelPlanner` below, and the EXECUTOR does not change now that it has landed.

Why `next_step` takes observations: a plan that is a fixed list executed in order
is a pipeline wearing a loop's clothes.  The signature is what makes revision
possible; MockPlanner exercises it via Scenario.revise, and
`test_orchestrator.py::test_observation_changes_the_next_step` proves a
different observation yields a different step.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Protocol

from ..config import MAX_ITERATIONS, Settings
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


class PlannerError(RuntimeError):
    """The planning model did not return a usable plan or decision.

    Raised rather than returning an empty Plan or a silent None.  The executor
    turns this into a failed task carrying a visible INTERNAL error, which is
    what CONTRIBUTING rule 4.4 requires: a real component that cannot do its job
    fails loudly instead of emitting plausible-looking empty output that a demo
    could mistake for success.
    """


def _step_schema() -> dict:
    """Wire schema for one proposed step.

    `target` is deliberately a bare string with no enum.  Constraining it here
    would quietly move the allowlist decision into the request; PlanStep is the
    validation boundary that actually matters - see `ModelPlanner._to_step`.
    The legal names are given to the model in the system prompt instead.
    """
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["agent", "tool"]},
            "target": {"type": "string"},
            "args": {"type": "object"},
            "why": {"type": "string"},
        },
        "required": ["kind", "target", "why"],
    }


def _plan_schema(max_steps: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": max_steps,
                "items": _step_schema(),
            }
        },
        "required": ["steps"],
    }


def _decision_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["continue", "revise", "done"]},
            "step": _step_schema(),
        },
        "required": ["action"],
    }


class ModelPlanner:
    """Real, model-driven planner.  OWNER: P1.

    Talks to the reasoning MODEL directly through llm/ollama_client.py, using
    the `planning` capability resolved from the frozen config/models.yaml.  It
    does NOT call agents/reasoning.py: an agent drafts the content of a single
    step, and agents/base.py says agents do not decide what runs next, which is
    exactly this class's job.  docs/DECISIONS.md D-019 records why.

    Contract, as implemented:
      * `propose` prompts the model with the task text, the router decision and
        the seven tool schemas, and parses a Plan.  Every proposed step is
        validated by PlanStep, so a hallucinated tool or agent name fails
        validation before anything runs.
      * `next_step` re-prompts with the accumulated Observations and returns the
        next action, or None when done.  It may return a step NOT in the
        original plan - the executor then requests a fresh approval if the step
        is outside the approved scope (approvals.in_scope).  This class does no
        scope logic of its own.
      * `is_satisfied` cannot consult the model: the Protocol declares it sync
        while the transport is async.  It answers from state instead - see the
        method for why that is not merely a shortcut.

    D-016 holds throughout: every PlanStep returned is the object that LIVES IN
    `plan.steps`, never a copy, because the executor mutates `step.status` in
    place and the UI renders `plan.steps`.

    Acceptance (P1): with SETU_MOCK_MODE=0, a text-only task produces a plan of
    1-5 validated steps, and the second call to next_step reflects the first
    step's observation.
    """

    simulated = False

    #: A plan may not be longer than the executor will run.  MAX_ITERATIONS is
    #: the number of loop turns available, so proposing more steps than that
    #: guarantees an iteration-cap escalation on a task that was otherwise fine.
    MAX_STEPS = MAX_ITERATIONS

    def __init__(self, settings: Settings, agents, registry) -> None:
        self.settings = settings
        self.agents = agents
        self.registry = registry  # the MODEL registry - see D-019
        self._tool_schemas: Optional[list[dict]] = None
        self._no_further_action = False

    # -- dependencies --------------------------------------------------------

    def _tool_schema_list(self) -> list[dict]:
        """The seven tool schemas.

        Built here rather than read off `self.registry`.  The contract this
        class inherited said `registry.schemas()`, but `build_planner` is wired
        by service.py with the MODEL registry, which has no `schemas()` - the
        tool registry is a different object and is not passed in.  Building one
        locally keeps the resolution inside this file; D-019 records the
        alternative and why it was not taken.
        """
        if self._tool_schemas is None:
            from ..tools.registry import build_registry

            self._tool_schemas = build_registry(self.settings).schemas()
        return self._tool_schemas

    def _agent_names(self) -> list[str]:
        if self.agents is not None:
            return list(self.agents.names())
        from ..contracts import AGENT_NAMES

        return list(AGENT_NAMES)

    def _model_entry(self):
        """The one place a capability becomes a model tag.  No tag lives here."""
        return self.registry.resolve("planning")

    # -- prompting -----------------------------------------------------------

    def _system_prompt(self) -> str:
        from ..security.injection import SYSTEM_DATA_RULE

        lines = [
            "You are the PLANNER for SETU, an on-premise agentic workbench.",
            "You do NOT answer the request yourself. You decide which actions",
            "run and in what order. Other components perform them.",
            "",
            'Agents you may target (kind="agent"):',
        ]
        lines += ["  - %s" % name for name in self._agent_names()]
        lines += ["", 'Tools you may target (kind="tool"):']
        for spec in self._tool_schema_list():
            params = (spec.get("parameters") or {}).get("properties") or {}
            lines.append("  - %s: %s" % (spec.get("name"), spec.get("description", "")))
            lines.append("      args: %s" % json.dumps(params, sort_keys=True))
        lines += [
            "",
            "Rules:",
            "  * `target` MUST be exactly one of the agent or tool names above.",
            "    Any other name is rejected before the step runs.",
            "  * For agents ('vision', 'reasoning', 'coding'), `kind` MUST be 'agent'.",
            "  * For tools ('kb_search', 'read_file', etc.), `kind` MUST be 'tool'.",
            "  * Propose between 1 and %d steps. Fewer is better." % self.MAX_STEPS,
            "  * `args` must match that tool's argument schema.",
            "  * If write_file or docgen content depends on a prior agent step, leave `content`",
            "    empty or use '<content>'; it will automatically be populated from that agent's output.",
            "  * When an image/document contains or requests code or a programming solution:",
            "    1. Use 'vision' to extract the problem statement from the image.",
            "    2. Use 'coding' to write and sandbox-verify the Python solution.",
            "    3. Use 'write_file' with args={'path': 'solution.py', 'content': '<generated_code>'} to save the code deliverable.",
            "  * `why` is one short sentence shown to a human in an approval",
            "    checklist. Write it for them, not for yourself.",
            "  * Reply with JSON only. No prose, no code fences.",
            "",
            SYSTEM_DATA_RULE,
        ]
        return "\n".join(lines)

    def _task_block(self, task: TaskEnvelope, decision: RouterDecision) -> str:
        lines = [
            "TASK: %s" % (task.text or ""),
            "",
            "The entry router chose the %r agent (rule %s): %s"
            % (decision.agent, decision.rule_id, decision.reason),
        ]
        if task.file_paths:
            lines.append("Attached files: %s" % ", ".join(task.file_paths))
        lines += ["", "Propose the plan."]
        return "\n".join(lines)

    def _progress_block(self, plan: Plan, observations: list[Observation]) -> str:
        from ..security.injection import wrap_untrusted

        lines = ["PLAN SO FAR:"]
        for step in plan.steps:
            lines.append(
                "  %d. [%s] %s:%s - %s"
                % (step.n, step.status, step.kind, step.target, step.why)
            )
        lines += ["", "OBSERVATIONS (oldest first):"]
        for obs in observations:
            head = "  step %d %s:%s -> %s" % (
                obs.step_n,
                obs.kind,
                obs.target,
                "ok" if obs.ok else "FAILED",
            )
            if obs.error is not None:
                head += " (%s: %s)" % (obs.error.code, obs.error.message)
            lines.append(head)
            # An observation summary can carry text lifted out of a retrieved
            # document, so it goes in the DATA region, never the instruction
            # region. Otherwise a sentence inside a PDF could rewrite the plan -
            # the exact attack security/injection.py exists to blunt.
            obs_text = obs.summary or ""
            if obs.target == "vision" and obs.payload:
                raw = obs.payload.get("raw_text")
                if raw and isinstance(raw, str) and raw.strip():
                    obs_text += "\nExtracted content:\n" + raw.strip()[:1200]
                elif obs.payload.get("findings"):
                    f_texts = [
                        f.get("text", "")
                        for f in obs.payload["findings"]
                        if isinstance(f, dict) and f.get("text")
                    ]
                    if f_texts:
                        obs_text += "\nExtracted content:\n" + "\n".join(f_texts)[:1200]
            lines.append(
                wrap_untrusted("observation-step-%d" % obs.step_n, obs_text)
            )
        lines += [
            "",
            "Given those observations, decide what happens next:",
            '  "continue" - run the next pending step as already planned',
            '  "revise"   - the observations changed things; supply the step to',
            "               run instead, in `step`",
            '  "done"     - the task is satisfied; no further action is needed',
        ]
        return "\n".join(lines)

    async def _ask(self, user: str, schema: dict, what: str) -> dict:
        """One structured-output turn against the planning model."""
        from ..llm.ollama_client import get_client

        entry = self._model_entry()
        client = get_client(self.settings)
        # Report a missing tag rather than pulling one mid-task (transport
        # property 1 / CONTRIBUTING rule 7).
        await client.ensure_model(entry.model)

        response = await client.chat(
            entry.model,
            [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": user},
            ],
            # The full budget on purpose. With `think=False` below the answer
            # is short (~500 chars), but a tight num_predict on this model
            # returns done_reason="length" with EMPTY content rather than a
            # truncated plan, so there is no reason to economise here.
            options={
                "temperature": entry.temperature,
                "num_predict": entry.max_output_tokens,
            },
            keep_alive=entry.keep_alive,
            format_schema=schema,
            # Planning is a structured-output call, not a chain-of-thought one.
            # The planning model is a Qwen3 thinking model and Ollama leaves
            # thinking ON when no `think` key is sent, so the reasoning trace
            # was being generated, charged against the budget above, and then
            # thrown away - nothing reads `message.thinking`. Measured through
            # this code path: 15.4s median with it on, 3.4s with it off, same
            # plans. See D-020 for why this is hardcoded here rather than read
            # from config/models.yaml's `thinking: false`.
            think=False,
        )

        message = response.get("message") or {}
        content = (message.get("content") or "").strip()
        if not content:
            raise PlannerError(
                "the planning model returned no content for %s "
                "(done_reason=%r, num_predict=%d). It is a thinking model: if the "
                "reasoning trace consumed the budget, raise max_output_tokens for "
                "%s in config/models.yaml."
                % (what, response.get("done_reason"), entry.max_output_tokens, entry.id)
            )
        try:
            parsed: Any = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PlannerError(
                "the planning model returned unparseable JSON for %s: %s -- got %r"
                % (what, exc, content[:300])
            ) from exc
        if not isinstance(parsed, dict):
            raise PlannerError(
                "expected a JSON object for %s, got %s" % (what, type(parsed).__name__)
            )
        return parsed

    # -- validation ----------------------------------------------------------

    @staticmethod
    def _to_step(raw: Any, n: int) -> PlanStep:
        """PlanStep IS the validation boundary.

        A hallucinated agent or tool name fails PlanStep's own allowlist
        validator here, before the executor dispatches anything, and the
        resulting ValidationError is deliberately allowed to propagate. There is
        no separate manual name check to drift out of step with contracts.py.
        """
        if not isinstance(raw, dict):
            raise PlannerError(
                "a proposed step was %s, not a JSON object" % type(raw).__name__
            )
        from ..contracts import AGENT_NAMES, TOOL_NAMES

        kind = raw.get("kind")
        target = raw.get("target")

        # Auto-correct kind if the LLM mixed up agent vs tool classification
        if target in AGENT_NAMES and kind != "agent":
            kind = "agent"
        elif target in TOOL_NAMES and kind != "tool":
            kind = "tool"

        return PlanStep(
            n=n,
            kind=kind,
            target=target,
            args=raw.get("args") or {},
            why=raw.get("why") or "",
        )

    @staticmethod
    def _first_pending(plan: Plan) -> Optional[PlanStep]:
        """The plan's own next unrun step object.  D-016: never a copy."""
        for step in plan.steps:
            if step.status == "pending":
                return step
        return None

    # -- the three questions -------------------------------------------------

    async def propose(self, task: TaskEnvelope, decision: RouterDecision) -> Plan:
        parsed = await self._ask(
            self._task_block(task, decision),
            _plan_schema(self.MAX_STEPS),
            "the initial plan",
        )
        raw_steps = parsed.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise PlannerError("the planning model proposed no steps: %r" % (parsed,))
        if len(raw_steps) > self.MAX_STEPS:
            raise PlannerError(
                "the planning model proposed %d steps but the executor runs at "
                "most %d (config.MAX_ITERATIONS); a longer plan would escalate on "
                "the iteration cap." % (len(raw_steps), self.MAX_STEPS)
            )
        steps = [self._to_step(raw, n) for n, raw in enumerate(raw_steps, start=1)]
        plan = Plan(steps=steps, approved=False, revisions=0)
        _renumber(plan)
        return plan

    async def next_step(
        self, plan: Plan, observations: list[Observation]
    ) -> Optional[PlanStep]:
        # D-016: every PlanStep returned below is an object that LIVES IN
        # plan.steps. The executor mutates step.status in place and the UI
        # renders plan.steps; hand back a copy and the checklist never ticks.
        _renumber(plan)

        if not observations:
            # Nothing has run, so there is no observation to reflect and no
            # reason to spend a model call: take the plan's first step.
            return self._first_pending(plan)

        parsed = await self._ask(
            self._progress_block(plan, observations),
            _decision_schema(),
            "the next action",
        )
        action = str(parsed.get("action") or "").strip().lower()

        if action == "done":
            self._no_further_action = True
            return None

        if action == "revise":
            raw = parsed.get("step")
            if not isinstance(raw, dict):
                raise PlannerError(
                    "the planning model chose 'revise' without supplying a step: %r"
                    % (parsed,)
                )
            inserted = self._to_step(raw, len(observations) + 1)
            plan.revisions += 1
            # Insert after what has already run, then renumber so the checklist
            # stays 1..n. `inserted` is now the object held by plan.steps.
            plan.steps.insert(len(observations), inserted)
            _renumber(plan)
            return inserted

        # "continue", or any unexpected value: run the next unstarted step.
        step = self._first_pending(plan)
        if step is None:
            self._no_further_action = True
        return step

    def is_satisfied(self, plan: Plan, observations: list[Observation]) -> bool:
        """Answered from state, because the Protocol declares this sync.

        True when `next_step` has already reported no further action, or when no
        step is still pending.

        The second condition is not a shortcut. MAX_ITERATIONS is 5 and a plan
        may legitimately hold that many steps, so a planner that insisted on one
        extra confirming model call would drive every full-length plan into the
        iteration cap and escalate a task that had in fact finished. Revision
        still works, because `next_step` inserts a pending step into the plan
        before this is next consulted.
        """
        if self._no_further_action:
            return True
        return bool(plan.steps) and all(step.status != "pending" for step in plan.steps)


def build_planner(settings: Settings, scenario_key: str, agents=None, registry=None) -> Planner:
    """The one place mock and real diverge for planning.

    A mock scenario can NEVER activate in real mode: this raises rather than
    quietly substituting fixtures for model output.
    """
    if settings.mock_mode:
        return MockPlanner(scenario_key)
    return ModelPlanner(settings, agents, registry)
