"""
Dependency wiring.  OWNER: P1.

One container, built once at startup, holding the objects every request needs.
Nothing here is a module-level global that runs at import time - importing
`app.service` must not open Chroma, contact Ollama, or touch Docker, or a
teammate with none of those installed cannot even collect the test suite.

This is also the file that answers "where do mock and real diverge?".  Exactly
three places, all reached from `SetuService.build()`:

    agents.build_agents(settings, models)      -> MockAgent   | real agents
    tools.registry.build_registry(settings)    -> mock tools  | real tools
    orchestration.planner.build_planner(...)   -> MockPlanner | ModelPlanner

Everything else - dispatcher, executor, policy, approvals, audit, events, API -
is the same code in both modes.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from .agents import AgentRegistry, build_agents
from .config import MAX_ITERATIONS, ModelRegistry, Settings, get_registry, get_settings
from .contracts import RouterDecision, TaskCreateRequest, TaskEnvelope, TaskResult
from .history import HistoryStore
from .orchestration.dispatcher import Dispatcher
from .orchestration.events import EventBus
from .orchestration.executor import Executor
from .orchestration.planner import Planner, build_planner
from .orchestration.state import TaskRecord, TaskStore, new_session_id, new_task_id
from .router import route_task
from .security.audit import AuditLog
from .security.netwatch import NetworkMonitor
from .security.paths import ensure_workspace
from .tools.registry import ToolRegistry, build_registry


class SetuService:
    """The application's composition root."""

    def __init__(
        self,
        settings: Settings,
        models: ModelRegistry,
        agents: AgentRegistry,
        tools: ToolRegistry,
        audit: AuditLog,
        history: HistoryStore,
    ) -> None:
        self.settings = settings
        self.models = models
        self.agents = agents
        self.tools = tools
        self.audit = audit
        self.history = history
        self.bus = EventBus()
        self.store = TaskStore()
        self.monitor = NetworkMonitor(settings)
        self.dispatcher = Dispatcher(settings, models, agents, tools)
        self.executor = Executor(settings, models, self.dispatcher, self.bus, audit)

    @classmethod
    def build(cls, settings: Optional[Settings] = None) -> "SetuService":
        settings = settings or get_settings()
        models = get_registry()
        ensure_workspace(settings.workspace)
        return cls(
            settings=settings,
            models=models,
            agents=build_agents(settings, models),
            tools=build_registry(settings),
            audit=AuditLog(settings.audit_path),
            history=HistoryStore(settings.history_path),
        )

    # -- task lifecycle ------------------------------------------------------

    def create_task(
        self, req: TaskCreateRequest, session_id: Optional[str] = None
    ) -> tuple[TaskRecord, RouterDecision, Planner]:
        """Route and plan-select synchronously so the caller gets a decision
        immediately; execution is started separately by `start`."""
        resolved_session_id = session_id or req.session_id or new_session_id()
        envelope = TaskEnvelope(
            session_id=resolved_session_id,
            task_id=new_task_id(),
            text=req.text,
            file_paths=list(req.file_paths),
            conversation_context=self.history.context(resolved_session_id),
        )
        record = self.store.create(envelope, mock_mode=self.settings.mock_mode)
        self.history.add_turn(record)
        decision = route_task(envelope, self.models)
        record.router_decision = decision

        scenario_key = ""
        if self.settings.mock_mode:
            from .mocks.scenarios import select_scenario

            scenario_key = req.scenario or select_scenario(
                envelope.text, decision.agent, envelope.file_paths
            )
            record.scenario = scenario_key
        elif req.scenario:
            # A scenario name in real mode is ignored, loudly.  Fixtures must
            # never silently activate against real components.
            record.scenario = None

        planner = build_planner(self.settings, scenario_key, self.agents, self.models)
        return record, decision, planner

    async def start(self, record: TaskRecord, decision: RouterDecision, planner: Planner) -> None:
        """Emit `route` BEFORE spawning the run, so it is in the replay history
        even when the browser subscribes late."""
        await self.bus.emit(record.task_id, "route", decision.model_dump())
        await self.audit.append(
            task_id=record.task_id,
            session=record.envelope.session_id,
            action="router.decision",
            result="%s via %s" % (decision.agent, decision.rule_id),
            model=decision.model,
            args={"text": record.envelope.text, "files": record.envelope.file_paths},
        )
        if self.settings.mock_mode and record.scenario:
            from .mocks.adapters import set_scenario

            await self.bus.emit(
                record.task_id, "state",
                {"state": "created", "task_id": record.task_id,
                 "mock_scenario": record.scenario, "mock_mode": True},
            )

        async def _run() -> None:
            result: Optional[TaskResult] = None
            if self.settings.mock_mode and record.scenario:
                from .mocks.adapters import set_scenario as _set

                _set(record.scenario)  # ContextVar is set inside the task's context
            try:
                result = await self.executor.execute_plan(record, decision, planner)
            finally:
                if record.is_terminal:
                    self.history.finalise_turn(record, result)

        record.runner = asyncio.create_task(_run(), name="setu-task-" + record.task_id)

    async def cancel(self, record: TaskRecord) -> bool:
        """Cancel in-flight work and release anything the task was holding."""
        if record.is_terminal:
            return False
        future = record.approval_future
        if future is not None and not future.done():
            future.cancel()
        if record.runner is not None and not record.runner.done():
            record.runner.cancel()
            try:
                await record.runner
            except (asyncio.CancelledError, Exception):
                pass
        record.set_state("cancelled")
        return True

    @property
    def max_iterations(self) -> int:
        return MAX_ITERATIONS

    async def aclose(self) -> None:
        from .llm.ollama_client import close_client

        await close_client()
