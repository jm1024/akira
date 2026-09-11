"""Per-lane sensor passages shared by early RFID and stopped-car fallback."""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import uuid


@dataclass
class Passage:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    previous_id: str | None = None
    clear_at_fast: bool = False
    pending_id: str | None = None
    authorized: bool = False
    authorized_tid: str | None = None
    uncertain: bool = False
    ended: bool = False
    release_at: datetime | None = None
    retry_at: datetime = field(default_factory=datetime.now)
    no_tag_shown: bool = False

    def read_metadata(self):
        return {"passageID": self.id, "previousPassageID": self.previous_id,
                "laneClearAtFast": self.clear_at_fast}


class LanePassages:
    """Fast edges create arrivals; slow edges encounter them in travel order.

    A missed RFID read still has a sensor passage. The slow antenna therefore
    shares that passage's identity instead of creating a second transaction.
    """

    def __init__(self):
        self.waiting = deque()
        self.records = {}
        self.fast = None
        self.slow = None
        self.last_arrival = None
        self.retired = []

    def _new(self, clear=False):
        passage = Passage(previous_id=self.last_arrival.id if self.last_arrival else None,
                          clear_at_fast=clear)
        self.records[passage.id] = passage
        self.last_arrival = passage
        return passage

    def fast_trigger(self, mid, slow):
        clear = mid == 0 and slow == 0 and self.slow is None
        if clear:
            # A newly observed clear approach supersedes any unpaired startup
            # occupancy or missed downstream edge from earlier cars.
            for previous in self.waiting:
                previous.ended = True
                self.records.pop(previous.id, None)
                self.retired.append(previous.id)
            self.waiting.clear()
            self.last_arrival = None
        self.fast = self._new(clear=clear)
        self.waiting.append(self.fast)
        return self.fast

    def initialize_occupied(self, mid, slow):
        # After a restart, occupied downstream zones may contain unobserved
        # cars. Do not let validating the front car validate one still in mid.
        if slow == 1:
            self.slow = self._new()
        if mid == 1:
            self.waiting.append(self._new())

    def slow_trigger(self):
        if self.slow is not None:
            self.slow.release_at = None
            return self.slow
        # Startup may occur with a vehicle already at the gate.
        self.slow = self.waiting.popleft() if self.waiting else self._new()
        return self.slow

    def pause_slow(self, release_at):
        if self.slow is not None:
            self.slow.release_at = release_at

    def release_due(self, now):
        return (self.slow is not None and self.slow.release_at is not None
                and now >= self.slow.release_at)

    def slow_clear(self):
        passage = self.slow
        if passage is not None:
            passage.ended = True
            self.records.pop(passage.id, None)
        self.slow = None
        return passage

    def response(self, result, retry_at):
        passage = self.records.get(result.get("passageID"))
        if passage is None or result.get("id") != passage.pending_id:
            return
        passage.pending_id = None
        passage.authorized = bool(result.get("gateAuthorized")) or result.get("code") == "ALREADY_AUTHORIZED"
        if passage.authorized:
            passage.authorized_tid = result.get("authorizedTid") or result.get("tid")
        passage.uncertain = bool(result.get("deliveryUncertain"))
        passage.retry_at = retry_at

    def clear(self):
        self.waiting.clear()
        self.records.clear()
        self.fast = self.slow = self.last_arrival = None
        self.retired.clear()
