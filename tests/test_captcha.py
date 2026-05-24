from __future__ import annotations

import io
import time

import pytest

from easy_social import captcha

pytestmark = pytest.mark.unit


def test_generate_answer_length_and_alphabet():
    seen = set()
    for _ in range(200):
        answer = captcha.generate_answer()
        assert len(answer) == captcha.LENGTH
        assert all(ch in captcha.ALPHABET for ch in answer)
        seen.add(answer)
    assert len(seen) > 1


def test_hash_answer_is_one_way_and_case_insensitive():
    hashed = captcha.hash_answer("ABCDE")
    assert hashed != "ABCDE"
    assert captcha.verify_answer("ABCDE", hashed)
    assert captcha.verify_answer("abcde", hashed)
    assert captcha.verify_answer(" AbCdE ", hashed)


def test_verify_rejects_blank_or_wrong_answers():
    hashed = captcha.hash_answer("ABCDE")
    assert not captcha.verify_answer("", hashed)
    assert not captcha.verify_answer(None, hashed)
    assert not captcha.verify_answer("ZZZZZ", hashed)
    assert not captcha.verify_answer("ABCDE", "")
    assert not captcha.verify_answer("ABCDE", None)


def test_verify_requires_correct_length():
    hashed = captcha.hash_answer("ABCDE")
    assert not captcha.verify_answer("ABCD", hashed)
    assert not captcha.verify_answer("ABCDEF", hashed)


def test_render_image_returns_valid_png():
    png = captcha.render_image("ABCDE")
    assert isinstance(png, bytes)
    assert png[:8] == captcha.PNG_SIGNATURE

    pillow = pytest.importorskip("PIL")
    image = pillow.Image.open(io.BytesIO(png))
    assert image.format == "PNG"
    assert image.size == (captcha.WIDTH, captcha.HEIGHT)


def test_render_image_supports_varied_inputs():
    for answer in ("AAAAA", "12345", "A1B2C", "ZZZZZ"):
        png = captcha.render_image(answer)
        assert png[:8] == captcha.PNG_SIGNATURE


def test_issue_to_session_stores_hash_and_expiry(app):
    with app.test_request_context():
        from flask import session

        before = time.time()
        answer = captcha.issue_to_session(session)
        after = time.time()

        record = session[captcha.SESSION_KEY]
        assert record["hash"] != answer
        assert captcha.verify_answer(answer, record["hash"])
        assert before + captcha.TTL_SECONDS - 1 <= record["expires_at"] <= after + captcha.TTL_SECONDS + 1


def test_issue_to_session_exposes_plain_answer_only_under_testing(app):
    with app.test_request_context():
        from flask import session

        captcha.issue_to_session(session)
        assert "_test_plain" in session[captcha.SESSION_KEY]

    app.config["TESTING"] = False
    try:
        with app.test_request_context():
            from flask import session

            captcha.issue_to_session(session)
            assert "_test_plain" not in session[captcha.SESSION_KEY]
    finally:
        app.config["TESTING"] = True


def test_consume_from_session_is_single_use(app):
    with app.test_request_context():
        from flask import session

        answer = captcha.issue_to_session(session)
        assert captcha.consume_from_session(session, answer)
        assert not captcha.consume_from_session(session, answer)


def test_consume_from_session_fails_when_expired(app):
    with app.test_request_context():
        from flask import session

        answer = captcha.issue_to_session(session)
        record = session[captcha.SESSION_KEY]
        record["expires_at"] = time.time() - 1
        session[captcha.SESSION_KEY] = record

        assert not captcha.consume_from_session(session, answer)


def test_consume_from_session_returns_false_when_missing(app):
    with app.test_request_context():
        from flask import session

        assert not captcha.consume_from_session(session, "anything")


def test_consume_from_session_handles_corrupted_record(app):
    with app.test_request_context():
        from flask import session

        session[captcha.SESSION_KEY] = "not-a-dict"
        assert not captcha.consume_from_session(session, "anything")
