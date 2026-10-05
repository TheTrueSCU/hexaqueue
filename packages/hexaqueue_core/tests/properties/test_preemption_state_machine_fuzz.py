"""Stateful property-based fuzz testing for Job preemption and recovery lifecycle invariants.

Notes/Architectural Intent:
    Verifies that jobs transitioning across SUBMITTED, PENDING, RUNNING, and DONE
    under arbitrary preemption signals and requeue/recovery attempts strictly satisfy
    lifecycle transition validity (`can_transition_job`), deterministic RunState
    roll-up (`compute_run_state`), and RunOutcome projection (`compute_run_outcome`).
"""

from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    rule,
)

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import (
    JobState,
    JobStatus,
    RunState,
    TerminalOutcome,
    can_transition_job,
    compute_run_outcome,
    compute_run_state,
)
from hexaqueue_core.domain.run import RunSpec


class JobPreemptionStateMachine(RuleBasedStateMachine):
    """Hypothesis state machine verifying preemption and checkpoint recovery invariants.

    Notes/Architectural Intent:
        Models concurrency and scheduling churn where jobs:
        1. Are submitted and progress toward execution.
        2. Are preempted mid-flight (simulating spot termination or priority displacement).
        3. Persist checkpoint markers upon preemption.
        4. Are requeued / recovered with preserved checkpoint progress.
        5. Terminate cleanly, verifying pure mathematical roll-up to RunState / RunOutcome.
    """

    def __init__(self) -> None:
        """Initialize the state machine with empty tracking collections."""
        super().__init__()
        self.jobs: dict[str, JobSpec] = {}
        self.history: list[tuple[str, JobState, JobState]] = []
        self.checkpoints: dict[str, int] = {}
        self.requeued_from: dict[str, str] = {}
        self.counter: int = 0

    @rule(
        command=st.sampled_from(["train.py", "eval.sh", "etl_step", "compute_barrier"])
    )
    def submit_job(self, command: str) -> None:
        """Submit a new job in SUBMITTED state."""
        self.counter += 1
        job_id = f"job-{self.counter}"
        spec = JobSpec(
            id=job_id,
            run_id="run-fuzz-1",
            name=f"task-{self.counter}",
            command=command,
            status=JobStatus(state=JobState.SUBMITTED),
        )
        self.jobs[job_id] = spec
        self.checkpoints[job_id] = 0

    @rule(data=st.data())
    def schedule_to_pending(self, data: st.DataObject) -> None:
        """Transition an eligible submitted job to PENDING."""
        candidates = [
            j
            for j in self.jobs.values()
            if can_transition_job(j.state, JobState.PENDING)
            and j.state != JobState.PENDING
        ]
        if not candidates:
            return

        target = data.draw(st.sampled_from(candidates))
        old_state = target.state
        new_status = JobStatus(state=JobState.PENDING)
        updated = target.model_copy(update={"status": new_status})
        self.jobs[target.id] = updated
        self.history.append((target.id, old_state, JobState.PENDING))

    @rule(data=st.data())
    def start_running(self, data: st.DataObject) -> None:
        """Dispatch a PENDING job to RUNNING state."""
        candidates = [
            j
            for j in self.jobs.values()
            if can_transition_job(j.state, JobState.RUNNING)
            and j.state != JobState.RUNNING
        ]
        if not candidates:
            return

        target = data.draw(st.sampled_from(candidates))
        old_state = target.state
        new_status = JobStatus(state=JobState.RUNNING)
        updated = target.model_copy(update={"status": new_status})
        self.jobs[target.id] = updated
        self.history.append((target.id, old_state, JobState.RUNNING))

    @rule(data=st.data(), progress_inc=st.integers(min_value=1, max_value=10))
    def progress_checkpoint(self, data: st.DataObject, progress_inc: int) -> None:
        """Advance checkpoint progress for a RUNNING job."""
        candidates = [j for j in self.jobs.values() if j.state == JobState.RUNNING]
        if not candidates:
            return

        target = data.draw(st.sampled_from(candidates))
        self.checkpoints[target.id] = self.checkpoints.get(target.id, 0) + progress_inc

    @rule(data=st.data())
    def preempt_job(self, data: st.DataObject) -> None:
        """Preempt an active in-flight job, moving it to DONE with PREEMPTED outcome."""
        candidates = [
            j
            for j in self.jobs.values()
            if j.state in (JobState.PENDING, JobState.RUNNING)
            and can_transition_job(j.state, JobState.DONE)
        ]
        if not candidates:
            return

        target = data.draw(st.sampled_from(candidates))
        old_state = target.state
        new_status = JobStatus(
            state=JobState.DONE,
            outcome=TerminalOutcome.PREEMPTED,
            reason="Preemption signal received from cluster resource manager",
        )
        updated = target.model_copy(update={"status": new_status})
        self.jobs[target.id] = updated
        self.history.append((target.id, old_state, JobState.DONE))

    @rule(data=st.data())
    def recover_and_requeue_preempted(self, data: st.DataObject) -> None:
        """Recover a preempted job by requeueing a new job attempt with checkpoint state."""
        preempted = [
            j
            for j in self.jobs.values()
            if j.state == JobState.DONE and j.outcome == TerminalOutcome.PREEMPTED
        ]
        if not preempted:
            return

        target = data.draw(st.sampled_from(preempted))
        self.counter += 1
        new_id = f"{target.id}-recovered-{self.counter}"
        saved_checkpoint = self.checkpoints.get(target.id, 0)

        recovered_spec = JobSpec(
            id=new_id,
            run_id=target.run_id,
            name=f"{target.name}-retry",
            command=target.command,
            status=JobStatus(state=JobState.PENDING),
        )
        self.jobs[new_id] = recovered_spec
        self.checkpoints[new_id] = saved_checkpoint
        self.requeued_from[new_id] = target.id

    @rule(data=st.data())
    def complete_job_successfully(self, data: st.DataObject) -> None:
        """Complete a RUNNING job with COMPLETED outcome."""
        candidates = [
            j
            for j in self.jobs.values()
            if j.state == JobState.RUNNING
            and can_transition_job(j.state, JobState.DONE)
        ]
        if not candidates:
            return

        target = data.draw(st.sampled_from(candidates))
        old_state = target.state
        new_status = JobStatus(
            state=JobState.DONE,
            outcome=TerminalOutcome.COMPLETED,
        )
        updated = target.model_copy(update={"status": new_status})
        self.jobs[target.id] = updated
        self.history.append((target.id, old_state, JobState.DONE))

    @rule(data=st.data())
    def fail_job(self, data: st.DataObject) -> None:
        """Terminate an active job with FAILED outcome."""
        candidates = [
            j
            for j in self.jobs.values()
            if j.state in (JobState.PENDING, JobState.RUNNING)
            and can_transition_job(j.state, JobState.DONE)
        ]
        if not candidates:
            return

        target = data.draw(st.sampled_from(candidates))
        old_state = target.state
        new_status = JobStatus(
            state=JobState.DONE,
            outcome=TerminalOutcome.FAILED,
            reason="Uncaught execution failure",
        )
        updated = target.model_copy(update={"status": new_status})
        self.jobs[target.id] = updated
        self.history.append((target.id, old_state, JobState.DONE))

    @invariant()
    def check_all_recorded_transitions_valid(self) -> None:
        """Verify that every lifecycle transition executed obeyed state machine rules."""
        for _job_id, from_state, to_state in self.history:
            is_valid = can_transition_job(from_state, to_state)
            assert is_valid is True

    @invariant()
    def check_job_status_and_outcome_invariants(self) -> None:
        """Verify JobStatus invariants across all registered jobs."""
        for job in self.jobs.values():
            if job.state == JobState.DONE:
                has_outcome = job.outcome is not None
                assert has_outcome is True
                is_valid_outcome = job.outcome in TerminalOutcome
                assert is_valid_outcome is True
            else:
                has_no_outcome = job.outcome is None
                assert has_no_outcome is True

    @invariant()
    def check_requeue_checkpoint_preservation(self) -> None:
        """Verify checkpoint continuity when jobs are recovered after preemption."""
        for recovered_id, origin_id in self.requeued_from.items():
            recovered_cp = self.checkpoints.get(recovered_id, 0)
            origin_cp = self.checkpoints.get(origin_id, 0)
            is_preserved = recovered_cp >= origin_cp
            assert is_preserved is True

    @invariant()
    def check_run_state_projection_consistency(self) -> None:
        """Verify RunSpec projection strictly aligns with compute_run_state."""
        if not self.jobs:
            return

        job_list = list(self.jobs.values())
        run = RunSpec(id="fuzz-run-test", name="Fuzz Run", jobs=job_list)
        states = [j.state for j in job_list]

        expected_run_state = compute_run_state(states)
        actual_run_state = run.state
        assert actual_run_state == expected_run_state

        if all(s == JobState.DONE for s in states):
            assert actual_run_state == RunState.DONE
            outcomes = [j.outcome for j in job_list if j.outcome is not None]
            expected_outcome = compute_run_outcome(outcomes)
            actual_outcome = run.outcome
            assert actual_outcome == expected_outcome
        else:
            actual_outcome = run.outcome
            assert actual_outcome is None

        if any(
            s
            in (
                JobState.PENDING,
                JobState.PROVISIONING,
                JobState.RUNNING,
                JobState.CLEANUP,
            )
            for s in states
        ):
            assert actual_run_state == RunState.RUNNING


TestJobPreemptionStateMachine = JobPreemptionStateMachine.TestCase
