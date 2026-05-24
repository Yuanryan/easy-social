from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from easy_social.extensions import db
from easy_social.models import Poll, PollOption, PollVote, Post, User

from conftest import login, logout, register

pytestmark = pytest.mark.integration


def _create_poll_via_form(client, body: str, options: list[str]):
    return client.post(
        "/posts",
        data={
            "body": body,
            "has_poll": "1",
            "poll_option": options,
        },
        follow_redirects=True,
    )


def test_create_poll_post_persists_options_in_order(client, app):
    register(client, "alice")
    response = _create_poll_via_form(
        client, "Pick a color", ["Red", "Blue", "Green", "Yellow"]
    )

    assert response.status_code == 200
    with app.app_context():
        poll = Poll.query.one()
        assert poll.post.body == "Pick a color"
        assert [opt.text for opt in poll.options] == ["Red", "Blue", "Green", "Yellow"]
        assert [opt.display_order for opt in poll.options] == [0, 1, 2, 3]


def test_create_poll_with_fewer_than_two_options_is_rejected(client, app):
    register(client, "alice")
    response = _create_poll_via_form(client, "Question?", ["Only one"])

    assert b"at least 2 options" in response.data
    with app.app_context():
        assert Poll.query.count() == 0


def test_create_poll_with_more_than_four_options_is_rejected(client, app):
    register(client, "alice")
    response = _create_poll_via_form(
        client, "Q?", ["A", "B", "C", "D", "E"]
    )

    assert b"at most 4 options" in response.data
    with app.app_context():
        assert Poll.query.count() == 0


def test_create_poll_requires_body_as_question(client, app):
    register(client, "alice")
    response = _create_poll_via_form(client, "", ["A", "B"])

    assert b"need a question" in response.data
    with app.app_context():
        assert Poll.query.count() == 0


def test_create_poll_strips_blank_options(client, app):
    register(client, "alice")
    _create_poll_via_form(client, "Q?", ["A", "  ", "B", ""])

    with app.app_context():
        poll = Poll.query.one()
        assert [opt.text for opt in poll.options] == ["A", "B"]


def test_vote_records_user_choice_and_returns_results(client, app):
    register(client, "alice")
    _create_poll_via_form(client, "Pick", ["A", "B"])
    with app.app_context():
        poll = Poll.query.one()
        first_option_id = poll.options[0].id
        poll_id = poll.id

    logout(client)
    register(client, "bob")
    response = client.post(f"/polls/{poll_id}/vote", data={"option_id": first_option_id})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 1
    assert payload["viewer_option_id"] == first_option_id

    with app.app_context():
        vote = PollVote.query.one()
        assert vote.option_id == first_option_id


def test_changing_vote_overrides_previous_choice(client, app):
    register(client, "alice")
    _create_poll_via_form(client, "Pick", ["A", "B"])
    with app.app_context():
        poll = Poll.query.one()
        first, second = poll.options[0].id, poll.options[1].id
        poll_id = poll.id

    logout(client)
    register(client, "bob")
    client.post(f"/polls/{poll_id}/vote", data={"option_id": first})
    response = client.post(f"/polls/{poll_id}/vote", data={"option_id": second})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 1
    assert payload["viewer_option_id"] == second

    with app.app_context():
        votes = PollVote.query.all()
        assert len(votes) == 1
        assert votes[0].option_id == second


def test_anonymous_vote_redirects_to_login(client, app):
    register(client, "alice")
    _create_poll_via_form(client, "Pick", ["A", "B"])
    with app.app_context():
        poll = Poll.query.one()
        option_id = poll.options[0].id
        poll_id = poll.id

    logout(client)
    response = client.post(
        f"/polls/{poll_id}/vote",
        data={"option_id": option_id},
        follow_redirects=False,
    )

    assert response.status_code in (302, 401)
    if response.status_code == 302:
        assert "/auth/login" in response.headers.get("Location", "")

    with app.app_context():
        assert PollVote.query.count() == 0


def test_vote_on_closed_poll_returns_409(client, app):
    register(client, "alice")
    _create_poll_via_form(client, "Pick", ["A", "B"])
    with app.app_context():
        poll = Poll.query.one()
        poll.closes_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()
        poll_id = poll.id
        option_id = poll.options[0].id

    logout(client)
    register(client, "bob")
    response = client.post(f"/polls/{poll_id}/vote", data={"option_id": option_id})

    assert response.status_code == 409
    with app.app_context():
        assert PollVote.query.count() == 0


def test_vote_with_foreign_option_id_is_rejected(client, app):
    register(client, "alice")
    _create_poll_via_form(client, "Poll A", ["A", "B"])
    _create_poll_via_form(client, "Poll B", ["C", "D"])
    with app.app_context():
        polls = Poll.query.order_by(Poll.id).all()
        target_poll = polls[0]
        other_option_id = polls[1].options[0].id
        poll_id = target_poll.id

    response = client.post(f"/polls/{poll_id}/vote", data={"option_id": other_option_id})

    assert response.status_code == 400
    with app.app_context():
        assert PollVote.query.count() == 0


def test_results_endpoint_returns_current_counts(client, app):
    register(client, "alice")
    _create_poll_via_form(client, "Pick", ["A", "B"])
    with app.app_context():
        poll = Poll.query.one()
        first = poll.options[0].id
        poll_id = poll.id

    client.post(f"/polls/{poll_id}/vote", data={"option_id": first})
    response = client.get(f"/polls/{poll_id}/results")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 1
    assert payload["options"][0]["votes"] == 1
    assert payload["options"][1]["votes"] == 0


def test_feed_renders_poll_options(client, app):
    register(client, "alice")
    _create_poll_via_form(client, "Pick a color", ["Red", "Blue"])

    response = client.get("/")
    assert b"Pick a color" in response.data
    assert b"Red" in response.data
    assert b"Blue" in response.data
    assert b"data-poll" in response.data
