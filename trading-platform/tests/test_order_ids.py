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


class _Broker:
    """Holds orders by client ID; a send can be accepted and its reply lost."""

    def __init__(self, lose_reply_with=None, refuse_with=None, status="new"):
        self.orders, self.sent, self.lookups = {}, [], []
        self.lose_reply_with, self.refuse_with, self.status = lose_reply_with, refuse_with, status

    def submit(self, client_order_id):
        self.sent.append(client_order_id)
        if self.refuse_with:
            raise RuntimeError(self.refuse_with)
        self.orders[client_order_id] = {"id": f"ord-{len(self.orders) + 1}", "status": self.status}
        if self.lose_reply_with:
            raise RuntimeError(self.lose_reply_with)
        return self.orders[client_order_id]

    def lookup(self, client_order_id):
        self.lookups.append(client_order_id)
        if client_order_id not in self.orders:
            raise RuntimeError("404 order not found")
        return self.orders[client_order_id]


def test_duplicate_id_after_a_timed_out_send_adopts_the_order_and_never_resends():
    """F1 (16 Nov 2026): the Alpaca library resends after HTTP 504; the resend is
    refused as a duplicate because the first try was accepted. One order only."""
    broker = _Broker(lose_reply_with="422 client_order_id must be unique")

    order, client_order_id = submit_with_unique_client_order_id(
        broker.submit, "etf-buy-SPY", lookup=broker.lookup)

    assert len(broker.sent) == 1 and len(broker.orders) == 1
    assert order == broker.orders[client_order_id] and broker.lookups == [client_order_id]


def test_lost_reply_is_adopted_too():
    broker = _Broker(lose_reply_with="HTTPSConnectionPool: Read timed out.")
    order, client_order_id = submit_with_unique_client_order_id(
        broker.submit, "etf-exit-SPY", lookup=broker.lookup)
    assert len(broker.sent) == 1 and order["id"] == "ord-1"


def test_refused_order_raises_the_broker_error_and_is_not_resent():
    broker = _Broker(refuse_with="insufficient buying power")
    with pytest.raises(RuntimeError, match="insufficient buying power"):
        submit_with_unique_client_order_id(broker.submit, "no-retry", lookup=broker.lookup)
    assert len(broker.sent) == 1 and len(broker.lookups) == 1


def test_an_order_the_broker_rejected_is_not_adopted():
    broker = _Broker(lose_reply_with="HTTP 504", status="rejected")
    with pytest.raises(RuntimeError, match="HTTP 504"):
        submit_with_unique_client_order_id(broker.submit, "etf-buy-SPY", lookup=broker.lookup)
    assert len(broker.sent) == 1


def test_duplicate_that_cannot_be_read_back_fails_without_a_second_send():
    broker = _Broker(lose_reply_with="client_order_id must be unique")

    def broken_lookup(_client_order_id):
        raise RuntimeError("504 Gateway Time-out")

    with pytest.raises(RuntimeError, match="could not be read back"):
        submit_with_unique_client_order_id(broker.submit, "etf-stop-SPY", lookup=broken_lookup)
    assert len(broker.sent) == 1


def test_lookup_is_required():
    with pytest.raises(TypeError):
        submit_with_unique_client_order_id(lambda _cid: None, "x")  # noqa: the point of the test
