from __future__ import annotations

import time

import pytest

from easy_social import captcha
from easy_social.models import User

pytestmark = pytest.mark.integration


def _issue_captcha(client) -> str:
    response = client.get("/auth/captcha.png")
    assert response.status_code == 200
    with client.session_transaction() as sess:
        return sess[captcha.SESSION_KEY]["_test_plain"]


def test_captcha_endpoint_returns_png_with_no_store(client):
    response = client.get("/auth/captcha.png")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"
    assert response.data[:8] == captcha.PNG_SIGNATURE
    cache_control = response.headers.get("Cache-Control", "")
    assert "no-store" in cache_control
    assert "no-cache" in cache_control


def test_register_page_includes_captcha_field_and_image(client):
    response = client.get("/auth/register")

    assert response.status_code == 200
    assert b'name="captcha"' in response.data
    assert b"/auth/captcha.png" in response.data


def test_register_without_captcha_field_fails(client, app):
    response = client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password",
        },
        follow_redirects=True,
    )

    assert b"Captcha verification failed" in response.data
    with app.app_context():
        assert User.query.filter_by(username="alice").first() is None


def test_register_with_wrong_captcha_fails(client, app):
    _issue_captcha(client)
    response = client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password",
            "captcha": "ZZZZZ",
        },
        follow_redirects=True,
    )

    assert b"Captcha verification failed" in response.data
    with app.app_context():
        assert User.query.filter_by(username="alice").first() is None


def test_register_with_correct_captcha_succeeds(client, app):
    answer = _issue_captcha(client)
    response = client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password",
            "captcha": answer,
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Feed" in response.data
    with app.app_context():
        assert User.query.filter_by(username="alice").first() is not None


def test_register_captcha_is_case_insensitive(client, app):
    answer = _issue_captcha(client)
    response = client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password",
            "captcha": answer.lower(),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        assert User.query.filter_by(username="alice").first() is not None


def test_captcha_is_single_use_per_attempt(client, app):
    answer = _issue_captcha(client)
    client.post(
        "/auth/register",
        data={
            "username": "first",
            "email": "first@example.com",
            "password": "password",
            "captcha": answer,
        },
        follow_redirects=True,
    )
    # Log the new account out so the second register attempt is processed
    # rather than short-circuited by current_user.is_authenticated.
    client.post("/auth/logout", follow_redirects=True)

    # The captcha was popped from the session; re-using it must fail.
    response = client.post(
        "/auth/register",
        data={
            "username": "second",
            "email": "second@example.com",
            "password": "password",
            "captcha": answer,
        },
        follow_redirects=True,
    )

    assert b"Captcha verification failed" in response.data
    with app.app_context():
        assert User.query.filter_by(username="second").first() is None


def test_captcha_is_invalidated_after_failed_attempt(client, app):
    answer = _issue_captcha(client)
    # First attempt: correct captcha but missing fields → registration fails
    # but the captcha must STILL be consumed (anti-replay).
    client.post(
        "/auth/register",
        data={
            "username": "",
            "email": "alice@example.com",
            "password": "password",
            "captcha": answer,
        },
        follow_redirects=True,
    )

    # Same answer reused — must fail because the entry was already popped.
    response = client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password",
            "captcha": answer,
        },
        follow_redirects=True,
    )
    assert b"Captcha verification failed" in response.data


def test_register_with_expired_captcha_fails(client, app):
    _issue_captcha(client)
    with client.session_transaction() as sess:
        record = sess[captcha.SESSION_KEY]
        record["expires_at"] = time.time() - 1
        sess[captcha.SESSION_KEY] = record

    response = client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password",
            "captcha": "anything",
        },
        follow_redirects=True,
    )

    assert b"Captcha verification failed" in response.data
    with app.app_context():
        assert User.query.filter_by(username="alice").first() is None


def test_each_captcha_request_rotates_the_answer(client):
    first = _issue_captcha(client)
    second = _issue_captcha(client)
    # First answer is overwritten by the second issue call.
    with client.session_transaction() as sess:
        assert sess[captcha.SESSION_KEY]["_test_plain"] == second
    assert len(first) == captcha.LENGTH
    assert len(second) == captcha.LENGTH


def test_captcha_peek_returns_404_outside_testing(client, app):
    app.config["TESTING"] = False
    try:
        response = client.get("/auth/test/captcha-peek")
        assert response.status_code == 404
    finally:
        app.config["TESTING"] = True
