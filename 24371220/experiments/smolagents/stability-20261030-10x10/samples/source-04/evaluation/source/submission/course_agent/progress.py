"""Immutable course state shared by tool gates, model context and final checks.

This module describes requirements. It does not execute steps, select evidence,
call models or infer completion from the model's prose.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskProgress:
    plan: tuple[tuple[str, str], ...]
    evidence_missing: tuple[str, ...]
    baseline_missing: tuple[tuple[str, ...], ...]
    changes_missing: tuple[str, ...]
    require_change: bool
    verification_missing: tuple[tuple[str, ...], ...]
    changed_files: tuple[str, ...]
    baseline_done: int
    verified_current: int
    required_checks: int
    requests_left: int
    completion_missing: tuple[str, ...] = ()

    @property
    def plan_items(self):
        return [{'title':title, 'status':status} for title, status in self.plan]

    @property
    def plan_complete(self):
        return bool(self.plan) and all(status == 'done' for _, status in self.plan)

    @property
    def work_requirements(self):
        missing = list(self.evidence_missing)
        missing += ['baseline: ' + ' '.join(cmd) for cmd in self.baseline_missing]
        if self.changes_missing:
            missing.append('remaining source changes: ' + ', '.join(self.changes_missing))
        elif self.require_change:
            missing.append('make the requested change')
        missing += ['verify current files: ' + ' '.join(cmd) for cmd in self.verification_missing]
        missing += list(self.completion_missing)
        return missing

    @property
    def work_complete(self):
        return not self.work_requirements

    @property
    def remaining(self):
        missing = self.work_requirements
        if not self.plan_complete:
            missing.append('finish all plan items after their work and checks')
        return missing

    @property
    def ready_for_final(self):
        return self.work_complete and self.plan_complete

    @property
    def phase(self):
        if self.evidence_missing:
            return 'read'
        if self.baseline_missing:
            return 'baseline'
        if self.changes_missing or self.require_change:
            return 'edit'
        if self.verification_missing:
            return 'verify'
        if self.completion_missing:
            return 'finish_requirements'
        return 'done' if self.plan_complete else 'finish_plan'

    @property
    def next_requirement(self):
        if self.ready_for_final:
            return 'final_answer when ready'
        if self.work_complete:
            return 'Changes and current-file tests are complete. Mark the existing plan done, then final_answer.'
        return self.work_requirements[0]

    def prompt_state(self):
        return {'phase':self.phase, 'next_requirement':self.next_requirement,
                'remaining_count':len(self.remaining), 'requests_left':self.requests_left,
                'baseline_done':self.baseline_done, 'changed_files':list(self.changed_files),
                'verified_current':self.verified_current, 'required_checks':self.required_checks}

    def status(self):
        return {**self.prompt_state(), 'plan':self.plan_items,
                'remaining':self.remaining, 'ready_for_final':self.ready_for_final}
