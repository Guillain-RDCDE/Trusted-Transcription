"""Prevention — stop hallucinations before they exist.

The seven detectors catch confident lies *after* the model produced
them. This package attacks the cause: most of those lies come from the
way the audio is fed to the model, not from the model itself. See
ADR 0005.
"""
