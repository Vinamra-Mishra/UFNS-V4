"""M11 — Hydraulic data-gap / readiness contract (Section 12).

A formal, explicit contract describing hydraulic readiness for real drainage
data. It records, per required hydraulic attribute, whether the attribute is:

    PRESENT    — present in the source AND unambiguous for UFNS use
    MISSING    — confirmed absent from the source
    DERIVED    — derived from an unambiguous source column by a documented rule
    ASSUMED    — supplied from an explicitly labelled synthetic/assumed fixture
    UNRESOLVED — present in the source but units/semantics unverifiable

For the Bagjola/Kolkata WB AMRUT pilot, the five UFNS-required hydraulic
attributes MUST remain MISSING:

    diameter_m
    invert_upstream_m
    invert_downstream_m
    manning_n
    capacity_m3s

No automatic derivation is allowed. The contract is the single place that
decides HYDRAULIC_NETWORK_READY. If any required attribute is MISSING or
UNRESOLVED and no governed ASSUMED fixture covers it for the active mode, the
hydraulic network is NOT ready and the system must not claim a real hydraulic
drainage simulation.

The contract is deeply immutable (frozen dataclass of immutable members).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any


class HydraulicAvailability(str, Enum):
    """Per-attribute hydraulic availability classification."""

    PRESENT = "PRESENT"
    MISSING = "MISSING"
    DERIVED = "DERIVED"
    ASSUMED = "ASSUMED"
    UNRESOLVED = "UNRESOLVED"


# The five UFNS-required hydraulic attributes (Section 5). These are the
# attributes that, together, parameterize a hydraulic drainage network.
REQUIRED_HYDRAULIC_ATTRIBUTES: tuple[str, ...] = (
    "diameter_m",
    "invert_upstream_m",
    "invert_downstream_m",
    "manning_n",
    "capacity_m3s",
)


@dataclass(frozen=True)
class AttributeReadiness:
    """Hydraulic readiness for one required attribute."""

    name: str
    availability: HydraulicAvailability
    source: str = ""            # "real_source" | "synthetic_fixture" | "absent"
    basis: str = ""             # documented reason / derivation rule

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "availability": self.availability.value,
            "source": self.source,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class HydraulicReadinessContract:
    """Formal hydraulic readiness contract (Section 12).

    Deeply immutable. ``attributes`` is exposed as a read-only mapping.

    ``hydraulic_network_ready`` is True ONLY when every required attribute is
    PRESENT or DERIVED from the real source (governed derivation), OR — for a
    mode that explicitly permits it — ASSUMED from a labelled synthetic
    fixture AND ``synthetic_fixture_labelled`` is True. In the latter case the
    contract still reports ``real_hydraulic_network_ready = False``.
    """

    dataset: str
    attributes: Mapping[str, AttributeReadiness]
    real_hydraulic_network_ready: bool
    synthetic_fixture_labelled: bool = False
    missing_attributes: tuple[str, ...] = ()
    assumed_attributes: tuple[str, ...] = ()
    unresolved_attributes: tuple[str, ...] = ()
    derived_attributes: tuple[str, ...] = ()
    present_attributes: tuple[str, ...] = ()
    notes: str = ""

    @property
    def hydraulic_network_ready(self) -> bool:
        """A hydraulic network is "ready" only when the REAL source fully
        parameterizes it. An ASSUMED-fixture path is reported separately and
        never sets this True (Section 6)."""
        return self.real_hydraulic_network_ready

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "required_attributes": list(REQUIRED_HYDRAULIC_ATTRIBUTES),
            "attributes": {k: v.to_dict() for k, v in self.attributes.items()},
            "present_attributes": list(self.present_attributes),
            "missing_attributes": list(self.missing_attributes),
            "derived_attributes": list(self.derived_attributes),
            "assumed_attributes": list(self.assumed_attributes),
            "unresolved_attributes": list(self.unresolved_attributes),
            "real_hydraulic_network_ready": self.real_hydraulic_network_ready,
            "synthetic_fixture_labelled": self.synthetic_fixture_labelled,
            "hydraulic_network_ready": self.hydraulic_network_ready,
            "notes": self.notes,
        }


def _freeze_attributes(
    attributes: Mapping[str, AttributeReadiness],
) -> Mapping[str, AttributeReadiness]:
    """Independent read-only view of the caller's mapping."""
    return MappingProxyType(dict(attributes))


def build_real_drainage_contract(
    dataset: str,
    *,
    missing: tuple[str, ...] | None = None,
    unresolved: tuple[str, ...] = (),
    derived: tuple[str, ...] = (),
    present: tuple[str, ...] = (),
    notes: str = "",
) -> HydraulicReadinessContract:
    """Build the hydraulic readiness contract for REAL drainage data.

    For the WB AMRUT pilot the five required attributes are MISSING by default
    (no automatic derivation). Any UNRESOLVED source columns (e.g. Width,
    Depth, Dr_Slope, DPS_CAP) must be passed explicitly as ``unresolved``;
    they are NEVER auto-converted to hydraulic parameters.
    """
    if missing is None:
        missing = tuple(
            a for a in REQUIRED_HYDRAULIC_ATTRIBUTES
            if a not in unresolved and a not in derived and a not in present
        )

    req_set = set(REQUIRED_HYDRAULIC_ATTRIBUTES)
    all_supplied = present + derived + unresolved + missing
    for attr in all_supplied:
        if attr not in req_set:
            raise ValueError(f"unknown hydraulic attribute {attr!r}")

    seen: dict[str, str] = {}
    for bucket_name, bucket in (
        ("present", present),
        ("derived", derived),
        ("unresolved", unresolved),
        ("missing", missing),
    ):
        for attr in bucket:
            if attr in seen:
                raise ValueError(
                    f"attribute {attr!r} classified in multiple buckets: {seen[attr]!r} and {bucket_name!r}"
                )
            seen[attr] = bucket_name

    if set(seen.keys()) != req_set:
        unassigned = req_set - set(seen.keys())
        raise ValueError(
            f"incomplete hydraulic attribute partition; unassigned attributes: {sorted(unassigned)}"
        )

    status: dict[str, AttributeReadiness] = {}
    for name in REQUIRED_HYDRAULIC_ATTRIBUTES:
        bucket = seen[name]
        if bucket == "present":
            status[name] = AttributeReadiness(
                name, HydraulicAvailability.PRESENT, source="real_source",
                basis="present and unambiguous in real source",
            )
        elif bucket == "derived":
            status[name] = AttributeReadiness(
                name, HydraulicAvailability.DERIVED, source="real_source",
                basis="derived from an unambiguous real source column by a governed rule",
            )
        elif bucket == "unresolved":
            status[name] = AttributeReadiness(
                name, HydraulicAvailability.UNRESOLVED, source="real_source",
                basis="candidate column present but units/semantics unverifiable; not converted",
            )
        else:
            status[name] = AttributeReadiness(
                name, HydraulicAvailability.MISSING, source="absent",
                basis="confirmed absent from real source; not invented",
            )

    ready = len(missing) == 0 and len(unresolved) == 0 and len(present) + len(derived) == len(
        REQUIRED_HYDRAULIC_ATTRIBUTES
    )
    contract = HydraulicReadinessContract(
        dataset=dataset,
        attributes=_freeze_attributes(status),
        real_hydraulic_network_ready=ready,
        synthetic_fixture_labelled=False,
        missing_attributes=tuple(missing),
        assumed_attributes=(),
        unresolved_attributes=tuple(unresolved),
        derived_attributes=tuple(derived),
        present_attributes=tuple(present),
        notes=notes or (
            "Real WB AMRUT geometry integrated; required hydraulic attributes "
            "are MISSING — a real hydraulic drainage network is NOT ready."
        ),
    )
    return contract


def build_synthetic_fixture_contract(
    dataset: str,
    *,
    assumed: tuple[str, ...] = REQUIRED_HYDRAULIC_ATTRIBUTES,
    notes: str = "",
) -> HydraulicReadinessContract:
    """Build the hydraulic contract for a SYNTHETIC/ASSUMED hydraulic fixture.

    Every supplied value is ASSUMED and explicitly labelled synthetic. The
    real hydraulic network is still NOT ready; the synthetic fixture is a
    separately-labelled reference path (MODE B), never stored as REAL_DATA.
    """
    status = {
        name: AttributeReadiness(
            name, HydraulicAvailability.ASSUMED, source="synthetic_fixture",
            basis="explicitly labelled SYNTHETIC/ASSUMED fixture value; not real",
        )
        for name in assumed
    }
    return HydraulicReadinessContract(
        dataset=dataset,
        attributes=_freeze_attributes(status),
        real_hydraulic_network_ready=False,
        synthetic_fixture_labelled=True,
        missing_attributes=(),
        assumed_attributes=tuple(assumed),
        unresolved_attributes=(),
        derived_attributes=(),
        present_attributes=(),
        notes=notes or (
            "Synthetic/assumed hydraulic fixture explicitly labelled; the real "
            "hydraulic network remains NOT ready. Values are NEVER REAL_DATA."
        ),
    )
