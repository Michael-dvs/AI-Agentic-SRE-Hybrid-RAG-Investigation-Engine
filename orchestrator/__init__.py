"""Orchestrator package providing Durable Deterministic Investigation Workflow, Dossier Serialization, and Human Review (C11, C12)."""

from orchestrator.checkpoint import CheckpointManager
from orchestrator.dossier import (
    DossierMarkdownRenderer,
    DossierSerializer,
    compute_canonical_dossier_hash,
)
from orchestrator.fallback import ManualFallbackGenerator
from orchestrator.handover import (
    HandoverExporter,
    sanitize_data_recursively,
    verify_ground_truth_isolation,
)
from orchestrator.investigator import (
    DEFAULT_COORDINATOR_TOKEN,
    DeterministicInvestigator,
)
from orchestrator.resilience import (
    BudgetExhaustedError,
    CircuitBreaker,
    CircuitOpenError,
    DeadlineExceededError,
    DeadLetterQueue,
    IncidentCancelledError,
    ResilienceController,
    ResilienceError,
)
from orchestrator.review import (
    ALLOWED_DECISIONS,
    ALLOWED_REVIEWER_ROLES,
    AuthorizedReviewManager,
    DossierHashMismatchError,
    HumanReviewManager,
    InvalidDossierError,
    InvalidReviewDecisionError,
    ReviewError,
    ReviewStateConflictError,
    StaleDossierVersionError,
    UnauthorizedReviewerError,
    build_human_correction_payload,
)
from orchestrator.ticketing import (
    DummyTicketManager,
    InvalidDossierStateError,
    TicketError,
)
from orchestrator.state_machine import (
    MANDATORY_STATES,
    InvalidStateTransitionError,
    InvestigationStateMachine,
    WorkflowStateStore,
    compute_sha256_hash,
    utc_now_z,
)

__all__ = [
    # State Machine & Persistence
    "MANDATORY_STATES",
    "InvalidStateTransitionError",
    "InvestigationStateMachine",
    "WorkflowStateStore",
    "compute_sha256_hash",
    "utc_now_z",
    # Resilience & Control
    "CircuitBreaker",
    "DeadLetterQueue",
    "ResilienceController",
    "ResilienceError",
    "DeadlineExceededError",
    "BudgetExhaustedError",
    "IncidentCancelledError",
    "CircuitOpenError",
    # Investigator & Checkpoint
    "CheckpointManager",
    "DeterministicInvestigator",
    "DEFAULT_COORDINATOR_TOKEN",
    # Dossier & Markdown
    "DossierSerializer",
    "DossierMarkdownRenderer",
    "compute_canonical_dossier_hash",
    # Human Review
    "AuthorizedReviewManager",
    "HumanReviewManager",
    "ReviewError",
    "UnauthorizedReviewerError",
    "StaleDossierVersionError",
    "InvalidReviewDecisionError",
    "DossierHashMismatchError",
    "InvalidDossierError",
    "ReviewStateConflictError",
    "build_human_correction_payload",
    "ALLOWED_REVIEWER_ROLES",
    "ALLOWED_DECISIONS",
    # Ticketing (C16)
    "DummyTicketManager",
    "InvalidDossierStateError",
    "TicketError",
    # Handover Export (C16)
    "HandoverExporter",
    "sanitize_data_recursively",
    "verify_ground_truth_isolation",
    # Fallback
    "ManualFallbackGenerator",
]
