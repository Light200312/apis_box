"""Errors that describe whether a browser prompt might have been submitted."""


class SafeToFallbackError(RuntimeError):
    """The primary provider failed before it could receive the prompt."""


class ResponseUncertainError(RuntimeError):
    """The prompt may have reached the provider, so another submission is unsafe."""
