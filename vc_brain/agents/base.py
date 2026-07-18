"""Base agent pattern: Observe -> Think -> Act with full traceability.

Every agent in the system inherits from this. Each step is logged so we can
trace exactly why a recommendation was made (Agentic Traceability stretch goal).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentStep(BaseModel):
    """One logged step in an agent's reasoning chain."""
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    phase: str  # observe | think | act
    input_summary: str = ""
    output_summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.5


class AgentTrace(BaseModel):
    """Full reasoning trace for an agent run. Enables traceability."""
    agent_name: str
    started_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    steps: list[AgentStep] = Field(default_factory=list)
    final_output: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    error: str = ""


class BaseAgent(ABC):
    """Base class for all VC Brain agents.

    Subclasses implement observe(), think(), act().
    The run() method orchestrates the loop and captures the full trace.
    """

    name: str = "base_agent"

    async def run(self, context: dict[str, Any]) -> AgentTrace:
        trace = AgentTrace(agent_name=self.name)

        try:
            # OBSERVE: gather relevant data
            observation = await self.observe(context)
            trace.steps.append(AgentStep(
                phase="observe",
                input_summary=str(list(context.keys())),
                output_summary=str(list(observation.keys())) if isinstance(observation, dict) else str(type(observation)),
                data=observation if isinstance(observation, dict) else {"raw": str(observation)[:500]},
            ))

            # THINK: reason over the data (usually LLM-assisted)
            reasoning = await self.think(observation)
            trace.steps.append(AgentStep(
                phase="think",
                output_summary=str(list(reasoning.keys())) if isinstance(reasoning, dict) else str(type(reasoning)),
                data=reasoning if isinstance(reasoning, dict) else {"raw": str(reasoning)[:500]},
                confidence=reasoning.get("confidence", 0.5) if isinstance(reasoning, dict) else 0.5,
            ))

            # ACT: take action based on reasoning
            result = await self.act(reasoning)
            trace.steps.append(AgentStep(
                phase="act",
                output_summary=str(list(result.keys())) if isinstance(result, dict) else str(type(result)),
                data=result if isinstance(result, dict) else {"raw": str(result)[:500]},
            ))

            trace.final_output = result if isinstance(result, dict) else {"result": str(result)}

        except Exception as e:
            trace.success = False
            trace.error = str(e)

        return trace

    @abstractmethod
    async def observe(self, context: dict[str, Any]) -> Any:
        """Gather data relevant to the agent's task."""
        ...

    @abstractmethod
    async def think(self, observation: Any) -> Any:
        """Reason over observed data. Typically calls the LLM."""
        ...

    @abstractmethod
    async def act(self, reasoning: Any) -> Any:
        """Execute an action based on reasoning. Write to memory, return result."""
        ...
