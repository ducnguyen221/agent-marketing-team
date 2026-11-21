"""Production authority boundary for V2 packages."""


def require_production_authority() -> None:
    """Block outbound writes until a source-backed production grant is wired."""
    raise ValueError("production_approval_generation_unavailable")
