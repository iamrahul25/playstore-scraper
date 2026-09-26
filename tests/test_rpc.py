import json

import pytest

from playstore_scraper.rpc import (
    RPC_ID,
    RpcDecodeError,
    SORT,
    build_reviews_payload,
    decode_reviews_response,
)


def test_payload_contains_rpc_and_app():
    body = build_reviews_payload("com.oakever.meowdoku", "newest", 100)
    assert "f.req=" in body
    assert RPC_ID in body
    assert "com.oakever.meowdoku" in body
    assert str(SORT["newest"]) in body


def test_payload_with_token_and_score():
    body = build_reviews_payload(
        "com.foo.bar", "relevant", 50, token="TOKEN123", score=5
    )
    assert "TOKEN123" in body
    # score 5 should appear in the inner JSON
    assert "%2C5%2C" in body or ",5," in body


def _wrap_inner(inner) -> str:
    inner_json = json.dumps(inner)
    outer = [["wrb.fr", RPC_ID, inner_json, None, None, None, "generic"]]
    return ")]}'\n\n" + json.dumps(outer)


def test_decode_page_with_reviews_and_token():
    review = ["gp:1", ["User", [None, None, None, ["", "", "http://img"]]], 5, None, "Great", [1700000000], 3]
    inner = [[review], None, [None, "NEXT_TOKEN"]]
    body = _wrap_inner(inner)
    reviews, token = decode_reviews_response(body)
    assert len(reviews) == 1
    assert reviews[0][0] == "gp:1"
    assert token == "NEXT_TOKEN"


def test_decode_last_page():
    review = ["gp:2", ["U"], 4, None, "ok", [1700000001], 0]
    inner = [[review], None, [None, None]]
    body = _wrap_inner(inner)
    reviews, token = decode_reviews_response(body)
    assert len(reviews) == 1
    assert token is None


def test_decode_empty():
    body = _wrap_inner([])
    reviews, token = decode_reviews_response(body)
    assert reviews == []
    assert token is None


def test_decode_garbage():
    with pytest.raises(RpcDecodeError):
        decode_reviews_response("not-json-at-all")
