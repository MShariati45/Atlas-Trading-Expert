from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import secrets


class LeadStatus(str, Enum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    FOLLOW_UP = "FOLLOW_UP"
    QUALIFIED = "QUALIFIED"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class Lead:
    lead_id: str
    created_at_utc: str
    name: str
    email: str
    phone: str = ""
    country: str = ""
    inquiry_type: str = "REQUEST_INFORMATION"
    message: str = ""
    status: LeadStatus = LeadStatus.NEW
    risk_disclosure_accepted: bool = False
    risk_disclosure_version: str = ""
    privacy_consent_accepted: bool = False
    privacy_policy_version: str = ""
    consent_accepted_at_utc: str = ""
    request_source: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class LeadStore:
    """Append-only JSONL lead store for staging.

    Public lead submission never creates an Atlas user and never grants app access.
    Owner/Admin workflows can read leads; only Owner policy should create users.
    """

    def __init__(self, path: str | Path = "runtime/leads.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def submit(
        self,
        *,
        name: str,
        email: str,
        phone: str = "",
        country: str = "",
        inquiry_type: str = "REQUEST_INFORMATION",
        message: str = "",
        risk_disclosure_accepted: bool = False,
        risk_disclosure_version: str = "",
        privacy_consent_accepted: bool = False,
        privacy_policy_version: str = "",
        request_source: str = "",
    ) -> Lead:
        name = name.strip()
        email = email.strip().lower()
        if not name:
            raise ValueError("name required")
        if "@" not in email or "." not in email.split("@", 1)[-1]:
            raise ValueError("valid email required")
        if len(message) > 4000:
            raise ValueError("message too long")
        lead = Lead(
            lead_id=f"LEAD-{secrets.token_hex(6).upper()}",
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            name=name,
            email=email,
            phone=phone.strip(),
            country=country.strip(),
            inquiry_type=(inquiry_type.strip() or "REQUEST_INFORMATION").upper(),
            message=message.strip(),
            risk_disclosure_accepted=bool(risk_disclosure_accepted),
            risk_disclosure_version=risk_disclosure_version.strip(),
            privacy_consent_accepted=bool(privacy_consent_accepted),
            privacy_policy_version=privacy_policy_version.strip(),
            consent_accepted_at_utc=(
                datetime.now(timezone.utc).isoformat()
                if risk_disclosure_accepted and privacy_consent_accepted
                else ""
            ),
            request_source=request_source.strip(),
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(lead.to_dict(), ensure_ascii=False) + "\n")
        return lead

    def list_all(self) -> list[Lead]:
        if not self.path.exists():
            return []
        out: list[Lead] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            raw["status"] = LeadStatus(raw.get("status", "NEW"))
            out.append(Lead(**raw))
        return out
