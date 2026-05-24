from __future__ import annotations

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import Poll, PollOption, PollVote

bp = Blueprint("polls", __name__, url_prefix="/polls")


def build_poll_from_form(form) -> tuple[list[str], list[str]]:
    """Read poll fields from a form. Returns (option_texts, errors)."""
    raw_options = form.getlist("poll_option")
    option_texts = [opt.strip() for opt in raw_options if opt and opt.strip()]
    errors: list[str] = []

    if len(option_texts) < Poll.MIN_OPTIONS:
        errors.append(f"Polls need at least {Poll.MIN_OPTIONS} options.")
    if len(option_texts) > Poll.MAX_OPTIONS:
        errors.append(f"Polls can have at most {Poll.MAX_OPTIONS} options.")
    if any(len(text) > Poll.OPTION_MAX_LENGTH for text in option_texts):
        errors.append(f"Each option must be {Poll.OPTION_MAX_LENGTH} characters or fewer.")

    return option_texts, errors


def attach_poll_to_post(post, option_texts: list[str]) -> Poll:
    poll = Poll(post=post)
    for index, text in enumerate(option_texts):
        poll.options.append(PollOption(display_order=index, text=text))
    db.session.add(poll)
    return poll


@bp.post("/<int:poll_id>/vote")
@login_required
def vote(poll_id: int):
    poll = db.session.get(Poll, poll_id)
    if poll is None:
        abort(404)
    if poll.is_closed():
        return jsonify({"error": "Poll is closed."}), 409

    option_id = request.form.get("option_id", type=int)
    if option_id is None:
        return jsonify({"error": "Missing option_id."}), 400

    option = db.session.get(PollOption, option_id)
    if option is None or option.poll_id != poll.id:
        return jsonify({"error": "Option does not belong to this poll."}), 400

    existing = PollVote.query.filter_by(poll_id=poll.id, user_id=current_user.id).first()
    if existing is None:
        db.session.add(
            PollVote(poll=poll, option=option, user_id=current_user.id)
        )
    else:
        existing.option = option

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Vote could not be recorded."}), 409

    db.session.refresh(poll)
    return jsonify(poll.results(viewer_id=current_user.id))


@bp.get("/<int:poll_id>/results")
@login_required
def results(poll_id: int):
    poll = db.session.get(Poll, poll_id)
    if poll is None:
        abort(404)
    return jsonify(poll.results(viewer_id=current_user.id))
