import pytest
from pydantic import ValidationError

from app.llm import __main__ as cli
from app.llm import build_llm_client, providers_from_settings
from app.llm.client import LLMResponse, LLMStream, Usage
from app.llm.errors import LLMUnavailableError
from app.llm.providers import GEMINI_BASE_URL, GROQ_BASE_URL, OPENROUTER_BASE_URL
from tests.conftest import make_settings

KEYS = ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY")


@pytest.fixture(autouse=True)
def no_keys_from_the_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


# --- providers from settings ---


def test_only_providers_with_keys_are_used_in_fixed_order() -> None:
    settings = make_settings(openrouter_api_key="or-key", groq_api_key="gq-key")

    providers = providers_from_settings(settings)

    assert [(p.name, p.base_url, p.model) for p in providers] == [
        ("groq", GROQ_BASE_URL, "openai/gpt-oss-120b"),
        ("openrouter", OPENROUTER_BASE_URL, "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ]
    assert providers[0].api_key.get_secret_value() == "gq-key"


def test_all_three_providers() -> None:
    settings = make_settings(
        groq_api_key="a", gemini_api_key="b", openrouter_api_key="c"
    )

    assert [p.base_url for p in providers_from_settings(settings)] == [
        GROQ_BASE_URL,
        GEMINI_BASE_URL,
        OPENROUTER_BASE_URL,
    ]


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_keys_mean_no_provider(blank: str) -> None:
    settings = make_settings(groq_api_key=blank, gemini_api_key=None)

    assert providers_from_settings(settings) == []
    assert settings.groq_api_key is None


def test_keys_are_stripped_and_never_shown() -> None:
    settings = make_settings(groq_api_key="  gq-secret  ")
    (groq,) = providers_from_settings(settings)

    assert groq.api_key.get_secret_value() == "gq-secret"
    assert "gq-secret" not in repr(groq) and "gq-secret" not in repr(settings)


def test_models_can_be_configured() -> None:
    settings = make_settings(groq_api_key="k", llm_groq_model=" qwen/qwen3.8-27b ")

    assert providers_from_settings(settings)[0].model == "qwen/qwen3.8-27b"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("llm_groq_model", "", "model names"),
        ("llm_gemini_model", "two words", "model names"),
        ("llm_timeout_seconds", 0.5, "LLM_TIMEOUT_SECONDS"),
        ("llm_timeout_seconds", 121, "LLM_TIMEOUT_SECONDS"),
        ("llm_max_retries", -1, "LLM_MAX_RETRIES"),
        ("llm_max_retries", 4, "LLM_MAX_RETRIES"),
    ],
)
def test_invalid_llm_settings_fail_fast(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        make_settings(**{field: value})


def test_settings_errors_never_echo_a_key() -> None:
    with pytest.raises(ValidationError) as info:
        make_settings(groq_api_key="gq-secret", llm_max_retries=9)

    assert "gq-secret" not in str(info.value)


def test_build_llm_client_uses_the_settings() -> None:
    settings = make_settings(
        groq_api_key="a", gemini_api_key="b", llm_timeout_seconds=7, llm_max_retries=2
    )

    client = build_llm_client(settings)
    only = build_llm_client(settings, only="gemini")
    missing = build_llm_client(settings, only="openrouter")

    assert client.provider_names == ["groq", "gemini"]
    assert (client._timeout, client._max_retries) == (7, 2)
    assert only.provider_names == ["gemini"]
    assert missing.provider_names == []


# --- CLI ---


class FakeClient:
    provider_names = ["groq"]

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, list, dict]] = []

    def complete(self, messages, **kwargs):
        self.calls.append(("complete", messages, kwargs))
        if self.error:
            raise self.error
        return LLMResponse(
            content="James Hunt.",
            tool_calls=(),
            finish_reason="stop",
            provider="groq",
            model="openai/gpt-oss-120b",
            usage=Usage(87, 74),
            latency_ms=632,
        )

    def stream(self, messages, **kwargs):
        self.calls.append(("stream", messages, kwargs))
        return LLMStream("groq", "openai/gpt-oss-120b", iter(["James ", "Hunt."]))


@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch):
    state = {"client": FakeClient(), "only": []}

    def build(settings, *, only=None):
        state["only"].append(only)
        return state["client"]

    monkeypatch.setattr(cli, "get_settings", lambda: make_settings())
    monkeypatch.setattr(cli, "build_llm_client", build)
    return state


def test_cli_prints_the_provider_and_answer(
    fake_cli, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.run(["Who won in 1976?", "--max-tokens", "100"]) == 0

    out = capsys.readouterr().out
    assert "[groq · openai/gpt-oss-120b · 632 ms, 87+74 tokens]" in out
    assert "James Hunt." in out
    _, messages, kwargs = fake_cli["client"].calls[0]
    assert messages == [{"role": "user", "content": "Who won in 1976?"}]
    assert kwargs == {"max_tokens": 100}
    assert fake_cli["only"] == [None]


def test_cli_streams(fake_cli, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.run(["Who won?", "--stream", "--provider", "groq"]) == 0

    out = capsys.readouterr().out
    assert "[groq · openai/gpt-oss-120b]" in out and "James Hunt." in out
    assert fake_cli["only"] == ["groq"]


def test_cli_without_a_configured_provider_exits_2(
    fake_cli, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_cli["client"].provider_names = []

    assert cli.run(["hi", "--provider", "gemini"]) == 2
    assert "no API key configured for gemini" in capsys.readouterr().err


def test_cli_llm_errors_exit_1_with_the_safe_message(
    fake_cli, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_cli["client"] = FakeClient(
        LLMUnavailableError("The language model is unavailable right now")
    )

    assert cli.run(["hi"]) == 1
    assert (
        "error: The language model is unavailable right now" in capsys.readouterr().err
    )


def test_cli_bad_input_exits_2(fake_cli, capsys: pytest.CaptureFixture[str]) -> None:
    fake_cli["client"] = FakeClient(ValueError("max_tokens must be between 1 and 8192"))

    assert cli.run(["hi", "--max-tokens", "0"]) == 2
    assert "max_tokens" in capsys.readouterr().err


def test_cli_rejects_unknown_providers(fake_cli) -> None:
    with pytest.raises(SystemExit) as info:
        cli.run(["hi", "--provider", "openai"])
    assert info.value.code == 2


def test_rate_limit_wait_setting() -> None:
    assert make_settings().llm_rate_limit_wait_seconds == 20
    client = build_llm_client(
        make_settings(groq_api_key="k", llm_rate_limit_wait_seconds=0)
    )
    assert client._rate_limit_wait == 0
    with pytest.raises(ValidationError, match="LLM_RATE_LIMIT_WAIT_SECONDS"):
        make_settings(llm_rate_limit_wait_seconds=61)


def test_base_urls_are_settings_for_a_stand_in() -> None:
    """F6.4: the load test points the backend at a stub LLM."""
    settings = make_settings(
        groq_api_key="k", llm_groq_base_url=" http://host.docker.internal:9100/v1 "
    )
    [groq] = providers_from_settings(settings)
    assert groq.base_url == "http://host.docker.internal:9100/v1"


@pytest.mark.parametrize("url", ["", "ftp://x/v1", "not a url", "file:///etc/passwd"])
def test_bad_base_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(llm_gemini_base_url=url)
