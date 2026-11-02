"""Language pair contract: registry, directed capabilities, usage modes and requirements.

See ``docs/products/lianiq/capabilities/language-pair-contract/contract.md`` §3.1.1-§3.1.4
and §3.1.8 in ``boris-heuer/app-shared``.
"""

from lianiq.languages.capabilities import (
    CapabilityCatalog,
    DirectedEdge,
    ReadinessProbe,
    ReadinessStatus,
    RecognitionCapability,
    TranslationCapability,
    VoiceCapability,
)
from lianiq.languages.errors import (
    CapabilityMissingError,
    LanguageContractError,
    ModeUnavailableError,
    PairLockedError,
    PlannedLanguageError,
    SameLanguagePairError,
    SettingsMigrationError,
    UnknownLanguageError,
    UnsupportedModeError,
)
from lianiq.languages.modes import (
    CALL_BRIDGE_MODE,
    InputKind,
    OutputKind,
    RoutingKind,
    SessionPair,
    UsageMode,
)
from lianiq.languages.registry import (
    BUILTIN_LANGUAGES,
    BUILTIN_REGISTRY,
    Availability,
    LanguageDefinition,
    LanguageId,
    LanguagePair,
    LanguageRegistry,
    normalize_language_id,
)
from lianiq.languages.requirements import (
    DeviceReadiness,
    ModeAvailability,
    Requirement,
    RequirementKind,
    check,
    describe,
    requirements,
)

__all__ = [
    "BUILTIN_LANGUAGES",
    "BUILTIN_REGISTRY",
    "CALL_BRIDGE_MODE",
    "Availability",
    "CapabilityCatalog",
    "CapabilityMissingError",
    "DeviceReadiness",
    "DirectedEdge",
    "InputKind",
    "LanguageContractError",
    "LanguageDefinition",
    "LanguageId",
    "LanguagePair",
    "LanguageRegistry",
    "ModeAvailability",
    "ModeUnavailableError",
    "OutputKind",
    "PairLockedError",
    "PlannedLanguageError",
    "ReadinessProbe",
    "ReadinessStatus",
    "RecognitionCapability",
    "Requirement",
    "RequirementKind",
    "RoutingKind",
    "SameLanguagePairError",
    "SessionPair",
    "SettingsMigrationError",
    "TranslationCapability",
    "UnknownLanguageError",
    "UnsupportedModeError",
    "UsageMode",
    "VoiceCapability",
    "check",
    "describe",
    "normalize_language_id",
    "requirements",
]
