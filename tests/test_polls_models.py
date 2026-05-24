from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from easy_social.extensions import db
from easy_social.models import Poll, PollOption, PollVote, Post, User

pytestmark = pytest.mark.unit


def _make_user(username: str) -> User:
    user = User(username=username, email=f"{username}@example.com")
    user.set_password("password")
    return user


def _make_poll(author: User, *option_texts: str) -> Poll:
    post = Post(author=author, body="What is your favorite color?")
    poll = Poll(post=post)
    for index, text in enumerate(option_texts):
        poll.options.append(PollOption(display_order=index, text=text))
    db.session.add_all([post, poll])
    db.session.flush()
    return poll


def test_poll_attaches_to_post_and_options_ordered(app):
    with app.app_context():
        alice = _make_user("alice")
        db.session.add(alice)
        db.session.commit()

        poll = _make_poll(alice, "Red", "Blue", "Green")
        db.session.commit()

        loaded = Poll.query.one()
        assert loaded.post.author_id == alice.id
        assert [opt.text for opt in loaded.options] == ["Red", "Blue", "Green"]
        assert [opt.display_order for opt in loaded.options] == [0, 1, 2]


def test_poll_option_unique_per_position(app):
    with app.app_context():
        alice = _make_user("alice")
        db.session.add(alice)
        db.session.commit()
        poll = _make_poll(alice, "A", "B")

        db.session.add(PollOption(poll=poll, display_order=0, text="dup"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_poll_vote_unique_per_user(app):
    with app.app_context():
        alice = _make_user("alice")
        bob = _make_user("bob")
        db.session.add_all([alice, bob])
        db.session.commit()

        poll = _make_poll(alice, "Yes", "No")
        first_option, second_option = poll.options
        db.session.add(PollVote(poll=poll, option=first_option, user_id=bob.id))
        db.session.commit()

        db.session.add(PollVote(poll=poll, option=second_option, user_id=bob.id))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_poll_results_ratio_sums_to_one(app):
    with app.app_context():
        alice = _make_user("alice")
        bob = _make_user("bob")
        carol = _make_user("carol")
        db.session.add_all([alice, bob, carol])
        db.session.commit()

        poll = _make_poll(alice, "X", "Y")
        x, y = poll.options
        db.session.add_all(
            [
                PollVote(poll=poll, option=x, user_id=alice.id),
                PollVote(poll=poll, option=x, user_id=bob.id),
                PollVote(poll=poll, option=y, user_id=carol.id),
            ]
        )
        db.session.commit()

        results = poll.results()
        assert results["total"] == 3
        assert sum(o["ratio"] for o in results["options"]) == pytest.approx(1.0)
        ratios = {o["id"]: o["ratio"] for o in results["options"]}
        assert ratios[x.id] == pytest.approx(2 / 3)
        assert ratios[y.id] == pytest.approx(1 / 3)


def test_poll_results_with_no_votes_returns_zero_ratios(app):
    with app.app_context():
        alice = _make_user("alice")
        db.session.add(alice)
        db.session.commit()
        poll = _make_poll(alice, "A", "B")
        db.session.commit()

        results = poll.results()
        assert results["total"] == 0
        assert all(o["ratio"] == 0.0 for o in results["options"])


def test_poll_viewer_option_id_reflects_user_vote(app):
    with app.app_context():
        alice = _make_user("alice")
        bob = _make_user("bob")
        db.session.add_all([alice, bob])
        db.session.commit()
        poll = _make_poll(alice, "A", "B")
        a, _ = poll.options
        db.session.add(PollVote(poll=poll, option=a, user_id=bob.id))
        db.session.commit()

        assert poll.results(viewer_id=bob.id)["viewer_option_id"] == a.id
        assert poll.results(viewer_id=alice.id)["viewer_option_id"] is None
        assert poll.results()["viewer_option_id"] is None


def test_poll_is_closed_respects_closes_at(app):
    with app.app_context():
        alice = _make_user("alice")
        db.session.add(alice)
        db.session.commit()
        poll = _make_poll(alice, "A", "B")
        poll.closes_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()

        assert poll.is_closed() is True
        assert poll.results()["closed"] is True


def test_poll_with_no_closes_at_is_open(app):
    with app.app_context():
        alice = _make_user("alice")
        db.session.add(alice)
        db.session.commit()
        poll = _make_poll(alice, "A", "B")
        db.session.commit()

        assert poll.is_closed() is False
        assert poll.results()["closed"] is False


def test_post_cascade_deletes_poll(app):
    with app.app_context():
        alice = _make_user("alice")
        db.session.add(alice)
        db.session.commit()
        poll = _make_poll(alice, "A", "B")
        post_id = poll.post.id
        db.session.commit()

        db.session.delete(poll.post)
        db.session.commit()

        assert Poll.query.filter_by(post_id=post_id).first() is None
        assert PollOption.query.filter_by(poll_id=poll.id).first() is None
