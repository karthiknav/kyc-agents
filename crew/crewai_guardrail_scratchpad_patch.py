"""
Patch: reset CrewAgentExecutor.messages at the start of every invoke() call.

Problem: CrewAgentExecutor.__init__ initialises self.messages = [] once, but
invoke() only ever appends to it (lines 194-195 in crew_agent_executor.py).
When the guardrail rejects an output and Task._invoke_guardrail_function calls
agent.execute_task() again for the retry, the same executor object is reused
and invoke() appends fresh system+user prompts on top of the previous run's full
conversation — including the rejected Final Answer.  The model sees its own prior
Final Answer at the tail of the scratchpad and re-emits it instantly, burning a
retry without making any LLM call.

Fix: prepend a self.messages = [] reset inside invoke() so each call always
starts from a clean slate.  System/user prompts are re-added by the existing
append logic immediately after the reset, so no context is lost.
"""

import logging

logger = logging.getLogger(__name__)

_PATCHED_ATTR = "_guardrail_scratchpad_reset_patched"


def apply_guardrail_scratchpad_patch() -> None:
    from crewai.agents.crew_agent_executor import CrewAgentExecutor

    if getattr(CrewAgentExecutor, _PATCHED_ATTR, False):
        return

    original_invoke = CrewAgentExecutor.invoke

    def _invoke_with_reset(self, inputs):
        if self.messages:
            logger.debug(
                "guardrail_scratchpad_patch: clearing %d stale messages before invoke",
                len(self.messages),
            )
        self.messages = []
        return original_invoke(self, inputs)

    CrewAgentExecutor.invoke = _invoke_with_reset
    setattr(CrewAgentExecutor, _PATCHED_ATTR, True)
    logger.info("guardrail_scratchpad_patch applied: CrewAgentExecutor.invoke will reset messages on each call")
