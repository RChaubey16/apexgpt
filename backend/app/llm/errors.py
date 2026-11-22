"""Errors raised by the LLM client. Messages are safe to show to users."""


class LLMError(RuntimeError):
    """The LLM could not produce an answer. Never carries prompts or keys."""


class LLMUnavailableError(LLMError):
    """No provider is configured, or every configured provider failed."""


class LLMStreamInterruptedError(LLMError):
    """A streamed answer stopped part-way; what was already sent is incomplete."""
