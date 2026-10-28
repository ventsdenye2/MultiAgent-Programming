"""Small integration hooks; execution, parsing and recovery remain upstream."""
from smolagents import CodeAgent
from smolagents.memory import ActionStep, FinalAnswerStep

from .audit import BudgetExceeded


class CourseCodeAgent(CodeAgent):
    def __init__(self, *args, context=None, **kwargs):
        self.course_context = context
        super().__init__(*args, **kwargs)

    def write_memory_to_messages(self, summary_mode=False):
        if self.course_context is None:
            return super().write_memory_to_messages(summary_mode)
        return self.course_context.build(self.memory, self.model)

    def provide_final_answer(self, task):
        # Upstream's max-step fallback normally makes an extra model request.
        # A course run must stop at its stated budget instead.
        raise BudgetExceeded("MAX_STEPS_NO_EXTRA_REQUEST")


def make_agent(model, session, context=None):
    def record_step(step, agent):
        if isinstance(step, ActionStep):
            session.log("agent_step", step=step.dict())
            if step.error:
                session.log("agent_error", error_type=type(step.error).__name__, error=str(step.error))
        elif isinstance(step, FinalAnswerStep):
            session.log("finish", summary=str(step.output))

    agent = CourseCodeAgent(tools=session.tools(), model=model, context=context,
                            max_steps=session.contract.max_calls, planning_interval=None,
                            final_answer_checks=[session.check_final],
                            step_callbacks=[record_step], add_base_tools=False,
                            stream_outputs=False, max_print_outputs_length=1000000,
                            verbosity_level=0)
    session.agent = agent
    return agent
