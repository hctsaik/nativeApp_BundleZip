"""Scheduled digest delivery — Round 111.

The business summary (analysis/summary) was pull-only. This adds the delivery
half of "email me a weekly digest": a schedule config, digest building, and a
*pluggable transport*. The transport is the only piece that touches the outside
world, so it's an interface — the default FileOutboxTransport drops a Markdown
file an external cron+SMTP job can pick up, and InMemoryTransport is for tests.
Swapping in a real SMTPTransport later is a one-class change; the schedule,
build, and record logic here are complete and tested.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ai4bi.analysis.summary import generate_summary
from ai4bi.blocks.contracts import DataBlockContract

_FREQUENCIES = {"daily", "weekly", "monthly"}


@dataclass
class DigestSchedule:
    recipients: list[str] = field(default_factory=list)
    frequency: str = "weekly"     # daily | weekly | monthly
    period: str = "week"          # summary window passed to generate_summary
    enabled: bool = True

    def validate(self) -> None:
        if self.frequency not in _FREQUENCIES:
            raise ValueError(f"frequency must be one of {_FREQUENCIES}")


class Transport(Protocol):
    def send(self, subject: str, body: str, recipients: list[str]) -> str:
        """Deliver the digest; return a reference (path / message-id)."""
        ...


@dataclass
class InMemoryTransport:
    """Test/double transport — records what would have been sent."""
    sent: list[dict] = field(default_factory=list)

    def send(self, subject: str, body: str, recipients: list[str]) -> str:
        self.sent.append({"subject": subject, "body": body, "recipients": list(recipients)})
        return f"mem-{len(self.sent)}"


@dataclass
class FileOutboxTransport:
    """Default transport — writes the digest as a Markdown file to an outbox dir
    that an external cron + SMTP job can pick up and send."""
    outbox_dir: Path

    def send(self, subject: str, body: str, recipients: list[str]) -> str:
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.outbox_dir / f"digest-{stamp}.md"
        header = f"To: {', '.join(recipients)}\nSubject: {subject}\n\n"
        path.write_text(header + body, encoding="utf-8")
        return str(path)


def build_digest(executor, contracts: dict[str, DataBlockContract], period: str = "week") -> tuple[str, str]:
    """Return (subject, markdown_body) for the digest."""
    rep = generate_summary(executor, contracts, period=period)
    return rep.title, rep.to_markdown()


def run_digest(
    executor,
    contracts: dict[str, DataBlockContract],
    schedule: DigestSchedule,
    transport: Transport,
) -> dict:
    """Build the digest and hand it to the transport. Returns a delivery record."""
    schedule.validate()
    if not schedule.enabled:
        return {"sent": False, "reason": "schedule disabled"}
    if not schedule.recipients:
        return {"sent": False, "reason": "no recipients"}
    subject, body = build_digest(executor, contracts, schedule.period)
    ref = transport.send(subject, body, schedule.recipients)
    return {
        "sent": True,
        "subject": subject,
        "recipients": list(schedule.recipients),
        "ref": ref,
        "at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
