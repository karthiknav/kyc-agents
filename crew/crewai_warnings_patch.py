from __future__ import annotations

import logging
import warnings
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def apply_crewai_warnings_patch() -> None:
    """
    Fix CrewAI's global `warnings.warn` monkey-patch (`_suppress_pydantic_deprecation_warnings`
    in crewai/__init__.py), which replaces `warnings.warn` with a wrapper accepting only
    `(message, category, stacklevel, source)`.

    Python 3.12+ added a keyword-only `skip_file_prefixes` parameter to `warnings.warn`.
    Libraries that pass it (numpy, scipy, the `deprecated` package used by opentelemetry's
    `InstrumentationInfo`, etc.) raise `TypeError: filtered_warn() got an unexpected keyword
    argument 'skip_file_prefixes'` as soon as anything in the process has imported `crewai` —
    this broke Langfuse's `get_client()` at import/init time. Re-wrap `warnings.warn` to
    swallow any extra args/kwargs the current implementation doesn't understand instead of
    raising.

    Importing crewai here (if not already imported) forces its patch to apply first, so we
    wrap whatever it left behind rather than being overwritten by it later.
    """
    if getattr(warnings, "__kyc_warnings_compat_patch_applied__", False):
        logger.info("✅ CrewAI warnings compatibility patch already applied (global)")
        return

    import crewai  # noqa: F401  (ensures crewai's own warnings.warn patch has already run)

    original_warn = warnings.warn

    def compat_warn(message: Any, category: Any = None, stacklevel: int = 1, source: Any = None, **kwargs: Any) -> Any:
        try:
            return original_warn(message, category, stacklevel, source, **kwargs)
        except TypeError:
            return original_warn(message, category, stacklevel, source)

    warnings.warn = compat_warn
    warnings.__kyc_warnings_compat_patch_applied__ = True
    logger.info("✅ Applied CrewAI warnings.warn compatibility patch")
