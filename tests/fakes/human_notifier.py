"""FakeHumanNotifier — programmable decision injection (SPEC.md §19.4)."""

from typing import Optional

from moirai.types import HumanDecision


class FakeHumanNotifier:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self._decisions: dict[str, Optional[HumanDecision]] = {}

    def request_intervention(
        self,
        workflow_id: str,
        task_id: Optional[str],
        reason: str,
        logs: Optional[str] = None,
    ) -> str:
        request_id = f"req-{len(self.requests)}"
        self.requests.append(
            {
                "request_id": request_id,
                "workflow_id": workflow_id,
                "task_id": task_id,
                "reason": reason,
                "logs": logs,
            }
        )
        self._decisions[request_id] = None
        return request_id

    def poll_decision(
        self, request_id: str, timeout_seconds: float = 86400.0
    ) -> Optional[HumanDecision]:
        return self._decisions.get(request_id)

    def cancel_request(self, request_id: str) -> None:
        self._decisions.pop(request_id, None)

    # ─── Test control surface ───────────────────────────────────────

    def set_decision(self, request_id: str, decision: HumanDecision) -> None:
        self._decisions[request_id] = decision
