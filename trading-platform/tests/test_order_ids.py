import pytest

from core.order_ids import (
    ALPACA_CLIENT_ORDER_ID_MAX_LENGTH,
    client_order_id_matches_prefix,
    make_client_order_id,
    submit_with_unique_client_order_id,
)


@pytest.mark.parametrize(
    ("environment", "expected_tag"),
    (("published", "pub"), ("dev", "dev"), (None, "unk")),
)
def test_environment_tag_is_present_and_bounded(monkeypatch, environment, expected_tag):
    if environment is None:
        monkeypatch.delenv("RUNNER_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("RUNNER_ENVIRONMENT", environment)

    generated = make_client_order_id("x" * 500)

    assert generated.startswith(f"{expected_tag}-")
    assert len(generated) <= ALPACA_CLIENT_ORDER_ID_MAX_LENGTH


def test_longest_environment_tagged_id_fits_alpaca_limit(monkeypatch):
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "published")

    generated = make_client_order_id("x" * 500)

    assert len(generated) == ALPACA_CLIENT_ORDER_ID_MAX_LENGTH


def test_tagged_and_legacy_prefixes_remain_matchable(monkeypatch):
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "dev")

    assert client_order_id_matches_prefix(
        make_client_order_id("etf-stop-oracle-SPY"),
        "etf-stop-oracle-SPY",
    )
    assert client_order_id_matches_prefix(
        "etf-stop-oracle-spy-1234567890abcdef",
        "etf-stop-oracle-SPY",
    )


def test_identical_prefixes_get_distinct_ids():
    first = make_client_order_id("same-prefix-symbol-date")
    second = make_client_order_id("same-prefix-symbol-date")

    assert first != second


def test_generated_ids_fit_alpaca_limit():
    generated = make_client_order_id("x" * 500)

    assert len(generated) <= ALPACA_CLIENT_ORDER_ID_MAX_LENGTH


def test_duplicate_id_retries_once_with_new_id():
    submitted_ids = []

    def submit(client_order_id):
        submitted_ids.append(client_order_id)
        if len(submitted_ids) == 1:
            raise RuntimeError("422 client_order_id must be unique")
        return {"status": "accepted"}

    result, client_order_id = submit_with_unique_client_order_id(
        submit,
        "retry-prefix",
    )

    assert result == {"status": "accepted"}
    assert len(submitted_ids) == 2
    assert submitted_ids[0] != submitted_ids[1]
    assert client_order_id == submitted_ids[1]


def test_non_duplicate_error_does_not_retry():
    attempts = []

    def submit(client_order_id):
        attempts.append(client_order_id)
        raise RuntimeError("insufficient buying power")

    with pytest.raises(RuntimeError, match="insufficient buying power"):
        submit_with_unique_client_order_id(submit, "no-retry")

    assert len(attempts) == 1