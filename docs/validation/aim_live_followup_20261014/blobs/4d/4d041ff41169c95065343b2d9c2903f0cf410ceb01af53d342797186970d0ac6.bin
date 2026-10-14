"""Fixed transport delay for an ordinary boolean fire level, with immediate safety.

Only this level is delayed. The caller owns gimbal control, safety assessment,
the 20 Hz feeder, physical launch pose, ammunition, bullet UID, and scoring.
See SEMANTICS.md before integrating. All event clocks are integer physics steps
and integer nanoseconds; no wall clock or floating-point clock is used.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
import json

_MAX_NS = (1 << 63) - 1


class FireDelayProtocolError(ValueError):
    """The delay line has already been cleared and inhibited when raised."""

    def __init__(self, message: str, snapshot: dict):
        super().__init__(message)
        self.snapshot = snapshot


@dataclass(frozen=True)
class _Event:
    sequence: int
    generation: int
    level: bool
    decision_step: int
    enqueue_step: int
    due_step: int
    decision_ns: int
    enqueue_ns: int
    due_ns: int
    payload: dict
    release_step: int | None = None
    release_ns: int | None = None


class FireLevelDelay:
    """advance(step, decision=None, *, safe, reasons=(), payload=None) -> dict.

    `decision` is supplied only at source control ticks. Both True and False
    traverse the same fixed delay. None means no new decision, not False.
    Call on every physics step, including steps without a control decision.

    Nondecreasing repeated steps are permitted; sequence determines FIFO ties.
    A pending event may never be released after its due step. Invalid input or
    a late release clears pending/active state before raising a protocol error.
    """

    def __init__(self, delay_steps: int = 80, *, step_ns: int = 500_000):
        if type(delay_steps) is not int or delay_steps < 0:
            raise ValueError("delay_steps must be a nonnegative integer, not bool")
        if type(step_ns) is not int or step_ns <= 0:
            raise ValueError("step_ns must be a positive integer, not bool")
        if step_ns > _MAX_NS or delay_steps > _MAX_NS // step_ns:
            raise ValueError("configured delay cannot be represented in signed 64-bit nanoseconds")
        self._delay_steps = delay_steps
        self._step_ns = step_ns
        self._pending: deque[_Event] = deque()
        self._sequence = 0
        self._generation = 0
        self._last_step: int | None = None
        self._safe: bool | None = None
        self._requested_level = False
        self._last_decision_step: int | None = None
        self._delayed_level = False
        self._active: _Event | None = None
        self._reasons: tuple[str, ...] = ("not_started",)
        self._fault: str | None = None

    @property
    def delay_steps(self) -> int:
        return self._delay_steps

    @property
    def step_ns(self) -> int:
        return self._step_ns

    def _clear(self) -> int:
        discarded = len(self._pending)
        self._pending.clear()
        self._active = None
        self._delayed_level = False
        self._generation += 1
        return discarded

    def snapshot(self) -> dict:
        """Detached, JSON-serializable state. Returned objects cannot mutate us."""
        return {
            "schema": "fire-level-delay-v1",
            "step": self._last_step,
            "time_ns": None if self._last_step is None else self._last_step * self._step_ns,
            "delay_steps": self._delay_steps,
            "delay_ns": self._delay_steps * self._step_ns,
            "generation": self._generation,
            "next_sequence": self._sequence,
            "safe": self._safe is True,
            "safety_reasons": list(self._reasons),
            "fault": self._fault,
            "requested_level": self._requested_level,
            "last_decision_step": self._last_decision_step,
            "delayed_level": self._delayed_level,
            "applied_level": self._safe is True and self._delayed_level,
            "pending_count": len(self._pending),
            "next_due_step": self._pending[0].due_step if self._pending else None,
            "active_event": None if self._active is None else asdict(self._active),
        }

    def reset(self, *, reason: str = "reset") -> dict:
        """Begin a new clock epoch, retaining monotonic event sequence/generation.

        This is explicit reset, not normal safety recovery. Old queued commands
        are discarded. No old requested or applied level survives a reset.
        """
        self._clear()
        self._safe = False
        self._requested_level = False
        self._last_decision_step = None
        self._last_step = None
        self._fault = None
        if type(reason) is not str or not reason:
            self._reasons = ("invalid_reset_reason",)
            self._fault = "reset reason must be a nonempty string"
            raise FireDelayProtocolError(self._fault, self.snapshot())
        self._reasons = (reason,)
        return self.snapshot()

    def _validate(self, step, decision, safe, reasons, payload) -> tuple[tuple[str, ...], dict]:
        if type(step) is not int or step < 0:
            raise ValueError("step must be a nonnegative integer, not bool")
        if self._last_step is not None and step < self._last_step:
            raise ValueError("step moved backwards")
        if step + self._delay_steps > _MAX_NS // self._step_ns:
            raise ValueError("decision/due time cannot be represented in signed 64-bit nanoseconds")
        if decision is not None and type(decision) is not bool:
            raise ValueError("decision must be bool or None")
        if type(safe) is not bool:
            raise ValueError("safe must be bool")
        if reasons is None:
            reasons = ()
        if isinstance(reasons, (str, bytes)) or not isinstance(reasons, Sequence):
            raise ValueError("reasons must be a sequence of nonempty strings")
        if any(type(r) is not str or not r for r in reasons):
            raise ValueError("reasons must contain only nonempty strings")
        if safe and reasons:
            raise ValueError("safe=True contradicts nonempty safety reasons")
        validated_reasons = tuple(reasons) if reasons else (() if safe else ("safety_inhibit",))
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping) or any(type(k) is not str for k in payload):
            raise ValueError("payload must be a mapping with string keys")
        if decision is None and payload:
            raise ValueError("payload requires an accompanying decision")
        # Restrict metadata to finite JSON and detach all caller-owned objects.
        copied = json.loads(json.dumps(dict(payload), allow_nan=False))
        for key in ("control_ns", "exposure_ns", "source_exposure_ns", "source_frame_id"):
            value = copied.get(key)
            if key in copied and value is not None and (
                    type(value) is not int or value < 0 or value > _MAX_NS):
                raise ValueError(f"payload {key} must be a nonnegative signed-64-bit integer or None")
        if "control_ns" in copied and copied["control_ns"] != step * self._step_ns:
            raise ValueError("payload control_ns disagrees with decision step")
        return validated_reasons, copied

    def advance(self, step: int, decision: bool | None = None, *, safe: bool,
                reasons: Sequence[str] | None = (), payload: Mapping | None = None) -> dict:
        """Advance only fire timing; caller must perform safety checks each step.

        A safe=False call discards due events before they can release. A decision
        on such a call is visible as requested telemetry but is never enqueued.
        Safety recovery alone does not replay requested telemetry or old events.
        """
        try:
            checked_reasons, copied_payload = self._validate(step, decision, safe, reasons, payload)
            self._last_step = step
            if decision is not None:
                self._requested_level = decision
                self._last_decision_step = step

            enqueued = None
            released = []
            discarded = 0
            if not safe:
                # Continuous inhibition need not allocate new generations every
                # 0.5 ms. Every transition/fault/reset does invalidate old events.
                if self._safe is not False or self._pending or self._active is not None:
                    discarded = self._clear()
                self._safe = False
                self._reasons = checked_reasons
                self._fault = None
            else:
                # Never silently release an overdue event or backdate a bullet.
                if self._pending and self._pending[0].due_step < step:
                    raise ValueError("missed due step: advance must run on every physics step")
                self._safe = True
                self._reasons = ()
                self._fault = None
                if decision is not None:
                    event = _Event(
                        sequence=self._sequence,
                        generation=self._generation,
                        level=decision,
                        decision_step=step,
                        enqueue_step=step,
                        due_step=step + self._delay_steps,
                        decision_ns=step * self._step_ns,
                        enqueue_ns=step * self._step_ns,
                        due_ns=(step + self._delay_steps) * self._step_ns,
                        payload=copied_payload,
                    )
                    self._sequence += 1
                    self._pending.append(event)
                    enqueued = asdict(event)
                while self._pending and self._pending[0].due_step == step:
                    event = self._pending.popleft()
                    if event.generation != self._generation:
                        raise ValueError("stale generation in pending fire event")
                    event = replace(event, release_step=step, release_ns=step * self._step_ns)
                    self._active = event
                    self._delayed_level = event.level
                    released.append(asdict(event))

            out = self.snapshot()
            out.update(
                decision_level=decision,
                decision_accepted=bool(safe and decision is not None),
                decision_dropped_for_safety=bool(not safe and decision is not None),
                discarded_pending_count=discarded,
                enqueued_event=enqueued,
                released_events=released,
            )
            return out
        except Exception as exc:
            # Preserve a valid observed time watermark even if another input
            # failed validation; malformed past input must not reopen an epoch.
            if type(step) is int and 0 <= step <= _MAX_NS // self._step_ns:
                self._last_step = step if self._last_step is None else max(step, self._last_step)
            self._clear()
            self._safe = False
            self._reasons = ("invalid_timing_input",)
            self._fault = f"{type(exc).__name__}: {exc}"
            raise FireDelayProtocolError(self._fault, self.snapshot()) from exc
