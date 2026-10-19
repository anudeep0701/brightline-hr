"""Operator-facing presentation of stored evidence. Never evaluates or mutates health."""

import re

from app.ai.incident_assistance import CHECKS
from app.schemas.assistant import AssistantPriority

METHODOLOGY = [
    "Health follows the stored integration policy, including minimum traffic, freshness and recovery requirements.",
    "Rolling evaluation windows may overlap; consecutive windows demonstrate persistence, not independent samples.",
    "Priority uses recorded severity and active incidents, then telemetry gaps. Customer impact is not measured.",
]


def pct(value):
    return (
        "unavailable"
        if value is None
        else f"{value * 100:.2f}".rstrip("0").rstrip(".") + "%"
    )


def latency(value):
    if value is None:
        return "unavailable"
    return (
        f"{value / 1000:.2f}".rstrip("0").rstrip(".") + " s"
        if value >= 1000
        else f"{value:.0f} ms"
    )


def intent(question):
    text = question.question.lower()
    if re.search(
        r"full evidence|more evidence|all evidence|detail|methodolog|calculat", text
    ):
        return "detail"
    if "escalat" in text or "summar" in text:
        return "escalation"
    if "investigat" in text or "check first" in text:
        return "investigate"
    if "chang" in text or "last hour" in text or "trend" in text:
        return "changes"
    if "recover" in text or "resolved" in text:
        return "recovery"
    if "stale" in text or "missing telemetry" in text or "fresh" in text:
        return "freshness"
    if question.scope == "workspace" and re.search(
        r"attention|risk|priorit|active incidents", text
    ):
        return "attention"
    return "why"


def driver(snapshot, fresh):
    if fresh["current_evidence_status"] == "UNKNOWN":
        if fresh["status"] == "NO_TELEMETRY":
            return "Unknown: no telemetry has arrived. Verify the exporter connection."
        if fresh["status"] == "STALE_TELEMETRY":
            return "Unknown: telemetry is stale. Restore recent evidence before judging health."
        if fresh["evaluation_overdue"]:
            return "Unknown: evaluation is overdue. Evaluate the latest telemetry."
        if snapshot and snapshot.reason_code == "INSUFFICIENT_REQUESTS":
            m, p = (
                snapshot.evidence.get("metrics", {}),
                snapshot.evidence.get("thresholds", {}),
            )
            return f"Unknown: only {m.get('request_count', 0)} requests; {p.get('min_requests', 'more')} are required."
        return "Unknown: there is not enough recent evidence to classify health."
    if snapshot is None:
        return "Unknown: no health evaluation is available."
    m, p = snapshot.evidence.get("metrics", {}), snapshot.evidence.get("thresholds", {})
    state, code = snapshot.status.title(), snapshot.reason_code
    streak, required = (
        snapshot.healthy_window_streak,
        p.get("healthy_recovery_windows", "required"),
    )
    if code in {
        "RECOVERY_PENDING",
        "RECOVERY_MARGIN_NOT_MET",
        "UNHEALTHY_RECOVERY_REQUIRED",
    }:
        progress = f"{streak} of {required} required healthy windows confirmed"
        if streak:
            return f"{state}: recovery is progressing; {progress}."
        if (
            m.get("error_rate") is not None
            and p.get("error_recovery") is not None
            and m["error_rate"] > p["error_recovery"]
        ):
            return f"{state}: recovery is not confirmed. Errors are {pct(m['error_rate'])}; recovery requires ≤ {pct(p['error_recovery'])}. {progress}."
        limit = p.get("latency_target_ms", 0) * p.get("latency_recovery_multiplier", 1)
        if m.get("p95_ms") is not None and limit and m["p95_ms"] > limit:
            return f"{state}: P95 latency {latency(m['p95_ms'])} is above the {latency(limit)} recovery margin; {progress}."
        baseline = (m.get("baseline") or {}).get("p95_ms")
        if (
            snapshot.evidence.get("baseline_used")
            and baseline
            and m.get("p95_ms") is not None
            and p.get("latency_recovery_multiplier") is not None
            and p.get("baseline_min_delta_ms") is not None
            and m["p95_ms"] - baseline >= p["baseline_min_delta_ms"]
            and m["p95_ms"] > baseline * p["latency_recovery_multiplier"]
        ):
            return f"{state}: P95 latency {latency(m['p95_ms'])} is above the {latency(baseline * p['latency_recovery_multiplier'])} baseline recovery margin; {progress}."
        if (
            m.get("timeout_rate") is not None
            and p.get("timeout_recovery") is not None
            and m["timeout_rate"] > p["timeout_recovery"]
        ):
            return f"{state}: timeouts remain above the recovery limit; {progress}."
        return f"{state}: recent failures have not yet met recovery requirements; {progress}. Check the stored recovery margins."
    primary = primary_signal(snapshot)
    if primary.startswith("LATENCY"):
        baseline = (m.get("baseline") or {}).get("p95_ms")
        reference = baseline if "BASELINE" in primary else p.get("latency_target_ms")
        ratio = (
            f" ({m['p95_ms'] / reference:.1f}× {'baseline' if 'BASELINE' in primary else 'target'})"
            if reference and m.get("p95_ms") is not None
            else ""
        )
        why = f"P95 latency is {latency(m.get('p95_ms'))}{ratio}"
    elif primary.startswith("TIMEOUT"):
        why = f"timeouts affect {pct(m.get('timeout_rate'))} of requests"
    elif primary.startswith("ERROR") or code == "SUSTAINED_DEGRADATION":
        why = f"errors affect {pct(m.get('error_rate'))} of requests"
    elif state == "Healthy":
        return "Healthy: recent traffic meets the error, latency and recovery policy."
    else:
        why = "the stored policy confirms sustained degradation"
    if code == "SUSTAINED_DEGRADATION":
        return f"{state}: degradation persisted for {snapshot.degraded_window_streak} windows; {why}."
    if code == "UNHEALTHY_CONFIRMATION_PENDING":
        return f"{state}: {why}; awaiting {p.get('unhealthy_bad_windows', 'the configured number of')} bad windows to confirm an incident."
    return f"{state}: {why}, sustained across {snapshot.bad_window_streak} evaluation windows."


def primary_signal(snapshot):
    code = snapshot.reason_code
    signals = snapshot.evidence.get("signal_reason_codes", [])
    return (
        code
        if code.startswith(("LATENCY", "ERROR", "TIMEOUT"))
        else next(
            (value for value in signals if value.endswith("CRITICAL")),
            next(iter(signals), ""),
        )
    )


def first_check(snapshot, fresh):
    if fresh["current_evidence_status"] == "UNKNOWN":
        return CHECKS["freshness"]
    if snapshot:
        if snapshot.reason_code == "RECOVERY_PENDING" or (
            snapshot.reason_code
            in {"RECOVERY_MARGIN_NOT_MET", "UNHEALTHY_RECOVERY_REQUIRED"}
            and not snapshot.evidence.get("signal_reason_codes")
        ):
            return CHECKS["recovery"]
        if primary_signal(snapshot).startswith("LATENCY"):
            return CHECKS["latency"]
        cats = snapshot.evidence.get("metrics", {}).get("top_error_categories", [])
        if cats and cats[0].get("category") == "auth":
            return CHECKS["auth"]
    return CHECKS["upstream"]


def compose(question, refs, groups, chosen, checks):
    """Keep model selections grounded; enforce concise, driver-aware product defaults."""
    purpose = intent(question)
    drivers = [r for r in refs if r.label == "Health decision"]
    if question.scope == "workspace" and purpose in {"why", "escalation", "recovery"}:
        text = question.question.lower()
        matched = [
            r
            for r in drivers
            if r.integration_name and r.integration_name.lower() in text
        ]
        if matched:
            drivers = matched
    status_order = {"UNHEALTHY": 0, "DEGRADED": 1, "UNKNOWN": 2, "HEALTHY": 3}
    drivers.sort(
        key=lambda r: (
            0 if r.active_incident else 1,
            status_order.get(r.health_status, 3),
            status_order.get(r.observed_status, 3)
            if r.health_status != "UNKNOWN"
            else 0,
            not r.stale_evidence,
            -(r.error_rate if r.error_rate is not None else -1),
            r.integration_name or "",
        )
    )
    selected_drivers = drivers
    if (
        purpose in {"attention", "investigate", "escalation"}
        and question.scope == "workspace"
    ):
        selected_drivers = [r for r in drivers if r.health_status != "HEALTHY"]
    selected_drivers = selected_drivers[:3]
    owned_ids = {r.integration_id for r in selected_drivers}
    relevant = [
        r for r in refs if not r.integration_id or r.integration_id in owned_ids
    ]
    facts = {r.id: r for r in relevant}
    priorities = [
        AssistantPriority(
            integration_id=r.integration_id,
            name=r.integration_name or "Integration",
            status=r.health_status or "UNKNOWN",
            reason=r.value.removeprefix(f"{r.integration_name}: "),
            next_check=r.next_check or CHECKS["upstream"],
        )
        for r in selected_drivers
        if r.integration_id
    ]
    if purpose == "attention":
        primary = [r for r in refs if groups[r.id] == "priority"] + selected_drivers
    elif purpose == "changes":
        changes = [r for r in refs if groups[r.id] == "changes"]
        primary = [r for r in changes if r.material_change][:3] or changes[:1]
    elif purpose == "freshness":
        gaps = [r for r in drivers if r.health_status == "UNKNOWN"]
        primary = gaps[:3] or [r for r in refs if groups[r.id] == "priority"]
    elif purpose == "recovery":
        primary = [r for r in relevant if r.label == "Incident and recovery"][
            :2
        ] + selected_drivers[:1]
    elif purpose == "escalation":
        if question.scope == "workspace":
            primary = [r for r in refs if groups[r.id] == "priority"] + selected_drivers
        else:
            primary = (
                selected_drivers[:1]
                + [
                    r
                    for r in relevant
                    if r.label in {"Incident and recovery", "Normalized errors"}
                ][:2]
                + [r for r in refs if r.label == "Authorized scope"]
            )
    elif purpose == "detail":
        primary = selected_drivers[:1] or refs[:1]
    else:
        primary = selected_drivers[:1]
    primary = primary or refs[:1]
    primary = list({r.id: r for r in primary}.values())[:4]
    if purpose in {"changes", "freshness", "recovery", "escalation"}:
        primary_ids = {r.integration_id for r in primary if r.integration_id}
        if primary_ids:
            owned_ids = primary_ids
            relevant = [
                r for r in refs if not r.integration_id or r.integration_id in owned_ids
            ]
            facts = {r.id: r for r in relevant}
    if purpose == "attention" and not selected_drivers:
        checks = []
    # Metrics and confirmation evidence, rather than repeating the full answer.
    evidence = [
        facts[k]
        for k in chosen
        if k in facts and facts[k] not in primary and facts[k].integration_id
    ][:4]
    for r in relevant:
        if (
            r.label
            in {
                "Error rate and volume",
                "Latency and baseline",
                "Policy confirmation",
                "Telemetry freshness",
            }
            and r not in primary
            and r not in evidence
            and len(evidence) < 4
        ):
            evidence.append(r)
    if purpose == "attention":
        strongest = []
        for item in selected_drivers:
            label = (
                "Telemetry freshness"
                if item.health_status == "UNKNOWN"
                else "Policy confirmation"
                if item.next_check == CHECKS["recovery"]
                else "Latency and baseline"
                if item.next_check == CHECKS["latency"]
                else "Error rate and volume"
            )
            fact = next(
                (
                    r
                    for r in refs
                    if r.integration_id == item.integration_id and r.label == label
                ),
                None,
            )
            if fact:
                strongest.append(fact)
        evidence = (
            strongest
            + [item for item in evidence if item not in strongest][
                : max(0, 4 - len(strongest))
            ]
        )
    if not evidence:
        evidence = primary[:4]
    extra = [
        r
        for r in refs
        if r not in evidence
        and r.label not in {"Authorized scope", "Current operational priorities"}
    ]
    if purpose != "detail":
        # Default responses never enumerate unrelated healthy integrations.
        extra = [
            r for r in extra if not r.integration_id or r.integration_id in owned_ids
        ]
    if purpose == "investigate":
        checks = list(
            dict.fromkeys(
                f"{r.integration_name}: {r.next_check}"
                for r in selected_drivers
                if r.next_check
            )
        )[:3]
    elif not checks and selected_drivers:
        checks = (
            [selected_drivers[0].next_check] if selected_drivers[0].next_check else []
        )
    return dict(
        answer="\n\n".join(r.value for r in primary),
        summary=primary[0].value,
        evidence=evidence,
        answer_evidence=primary,
        additional_evidence=extra,
        intent=purpose,
        priorities=priorities if purpose == "attention" else [],
        recommended_checks=checks[:3],
        methodology=METHODOLOGY,
    )
