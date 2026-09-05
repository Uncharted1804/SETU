"""
The agent interface.  OWNER: P1 (the interface), P2/P3/P4 (the implementations).

An agent is: a model + a role prompt + an output schema + a confidence signal +
a retry policy.  Nothing more.  That uniformity is why a fourth agent is cheap.

Agents DO NOT:
  * call each other (the orchestrator relays - blueprint 2.6)
  * decide what runs next
  * choose their own model tag (config.ModelRegistry does that)
  * dispatch tools

An agent RECEIVES an AgentInvocation (including `feedback` from the previous
attempt) and RETURNS an AgentResult carrying a confidence.  Retry, threshold and
escalation logic is in orchestration/policy.py, in one place, for all three.
"""

from __future__ import annotations

from typing import Protocol

from ..config import ModelRegistry, Settings
from ..contracts import AgentInvocation, AgentResult


class Agent(Protocol):
    """What the dispatcher requires of any agent, mock or real."""

    name: str

    async def run(self, inv: AgentInvocation) -> AgentResult: ...


class AgentContext:
    """Dependencies handed to an agent at construction.  No globals."""

    def __init__(self, settings: Settings, registry: ModelRegistry) -> None:
        self.settings = settings
        self.registry = registry

    def model_for(self, agent: str):
        return self.registry.resolve_for_agent(agent)

    def client(self):
        """Lazy: importing the transport must not require Ollama to be running."""
        from ..llm.ollama_client import get_client

        return get_client(self.settings)


def build_feedback(failure_reason: str, specifics: str = "") -> str:
    """The retry rule that decides whether any of this works (blueprint 2.5.4).

    A retry that re-asks the same question with the same prompt produces the
    same wrong answer.  Every retry carries what went wrong last time, and
    Attempt.feedback_injected records it so the UI can prove the retry was
    informed rather than blind.
    """
    text = "Your previous attempt was rejected: " + failure_reason
    if specifics:
        text += "\nSpecifically: " + specifics
    text += "\nAddress this directly; do not repeat the previous answer."
    return text
