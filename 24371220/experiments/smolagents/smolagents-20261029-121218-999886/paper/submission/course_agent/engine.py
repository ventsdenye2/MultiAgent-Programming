"""Small integration hooks; execution, parsing and recovery remain upstream."""
from smolagents import CodeAgent
from smolagents.agents import CODEAGENT_RESPONSE_FORMAT
from smolagents.memory import ActionStep, FinalAnswerStep

from .audit import BudgetExceeded
from .prompts import course_prompt_templates


class ProgressMonitor:
    """Observe official completed steps; never drive or replace the agent loop."""
    def __init__(self, session):
        self.session = session
        self.token = session.progress_token()
        self.last_call = 0
        self.stalled_steps = 0
        self.actions = []

    def observe(self, step):
        calls = self.session.audit.calls if self.session.audit else 0
        if calls <= self.last_call:
            return  # Synthetic final/max-step callbacks are not new attempts.
        self.last_call = calls
        token = self.session.progress_token()
        if token != self.token:
            self.stalled_steps, self.actions = 0, []
        else:
            self.stalled_steps += 1
            self.actions.append((str(step.code_action or step.model_output or ''), str(step.error or '')))
            self.actions = self.actions[-6:]
        self.token = token
        # Distinct actions may legitimately build executor variables or notes.
        # Stop an actual repeated cycle, not merely six context constructions.
        if self.stalled_steps >= 6 and len(set(self.actions)) <= 2:
            self.session.log('run_stalled', consecutive_steps=self.stalled_steps,
                             distinct_actions=len(set(self.actions)))
            raise BudgetExceeded('NO_PROGRESS: repeated action cycle without new reading, notes, changes or verification')


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


def make_agent(model, session, context=None, code_block_tags='markdown', use_structured_outputs_internally=True):
    session.progress_monitor = ProgressMonitor(session)

    def record_step(step, agent):
        if isinstance(step, ActionStep):
            session.log("agent_step", step=step.dict())
            if step.error:
                session.log("agent_error", error_type=type(step.error).__name__, error=str(step.error))
            session.progress_monitor.observe(step)
        elif isinstance(step, FinalAnswerStep):
            session.log("finish", summary=str(step.output))

    agent = CourseCodeAgent(tools=session.tools(), model=model, context=context,
                            prompt_templates=course_prompt_templates()
                            if use_structured_outputs_internally and session.contract.profile in {'source', 'paper'}
                            else None,
                            max_steps=session.contract.max_calls, planning_interval=None,
                            final_answer_checks=[session.check_final],
                            step_callbacks=[record_step], add_base_tools=False,
                            additional_authorized_imports=['json'],
                            executor_kwargs={'timeout_seconds': session.workspace.command_timeout + 5},
                            code_block_tags=code_block_tags,
                            use_structured_outputs_internally=use_structured_outputs_internally,
                            stream_outputs=False, max_print_outputs_length=1000000,
                            verbosity_level=0)
    session.agent = agent
    # Match the official CodeAgent generation arguments when estimating the
    # actual wire body. Markdown's closing tag is contained in its opening tag,
    # so upstream deliberately does not use it as a stop sequence.
    model.action_stop_sequences = ['Observation:', 'Calling tools:']
    if agent.code_block_tags[1] not in agent.code_block_tags[0]:
        model.action_stop_sequences.append(agent.code_block_tags[1])
    model.action_response_format = CODEAGENT_RESPONSE_FORMAT if use_structured_outputs_internally else None
    return agent
