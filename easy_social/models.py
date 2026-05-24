from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


followers = db.Table(
    "followers",
    db.Column("follower_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("followed_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column(
        "created_at",
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    ),
    CheckConstraint("follower_id != followed_id", name="ck_follow_not_self"),
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    bio = db.Column(db.String(280), nullable=False, default="")
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    posts = db.relationship("Post", back_populates="author", lazy="dynamic")
    comments = db.relationship("Comment", back_populates="author", lazy="dynamic")
    following = db.relationship(
        "User",
        secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref("followers", lazy="dynamic"),
        lazy="dynamic",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def follow(self, user: "User") -> None:
        if user.id != self.id and not self.is_following(user):
            self.following.append(user)

    def unfollow(self, user: "User") -> None:
        if self.is_following(user):
            self.following.remove(user)

    def is_following(self, user: "User") -> bool:
        return (
            self.following.filter(followers.c.followed_id == user.id).count() > 0
        )


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False, default="")
    media_filename = db.Column(db.String(255), nullable=True)
    media_type = db.Column(db.String(20), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    repost_of_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=True, index=True)

    author = db.relationship("User", back_populates="posts")
    comments = db.relationship(
        "Comment", back_populates="post", cascade="all, delete-orphan", lazy="dynamic"
    )
    repost_of = db.relationship("Post", remote_side=[id], backref="reposts")
    poll = db.relationship(
        "Poll",
        back_populates="post",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "(length(body) > 0) OR (media_filename IS NOT NULL) OR (repost_of_id IS NOT NULL)",
            name="ck_post_has_content",
        ),
    )

    @property
    def display_post(self) -> "Post":
        return self.repost_of or self

    @property
    def is_repost(self) -> bool:
        return self.repost_of_id is not None


class Poll(db.Model):
    MIN_OPTIONS = 2
    MAX_OPTIONS = 4
    OPTION_MAX_LENGTH = 80

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(
        db.Integer,
        db.ForeignKey("post.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    closes_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    post = db.relationship("Post", back_populates="poll")
    options = db.relationship(
        "PollOption",
        back_populates="poll",
        cascade="all, delete-orphan",
        order_by="PollOption.display_order",
    )
    votes = db.relationship(
        "PollVote",
        back_populates="poll",
        cascade="all, delete-orphan",
    )

    def is_closed(self) -> bool:
        if self.closes_at is None:
            return False
        closes_at = self.closes_at
        if closes_at.tzinfo is None:
            closes_at = closes_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= closes_at

    def total_votes(self) -> int:
        return len(self.votes)

    def vote_counts(self) -> dict[int, int]:
        counts = {option.id: 0 for option in self.options}
        for vote in self.votes:
            if vote.option_id in counts:
                counts[vote.option_id] += 1
        return counts

    def user_vote(self, user_id: int) -> "PollVote | None":
        for vote in self.votes:
            if vote.user_id == user_id:
                return vote
        return None

    def results(self, viewer_id: int | None = None) -> dict:
        counts = self.vote_counts()
        total = sum(counts.values())
        viewer_vote = self.user_vote(viewer_id) if viewer_id is not None else None
        return {
            "poll_id": self.id,
            "total": total,
            "closed": self.is_closed(),
            "viewer_option_id": viewer_vote.option_id if viewer_vote else None,
            "options": [
                {
                    "id": option.id,
                    "text": option.text,
                    "votes": counts[option.id],
                    "ratio": (counts[option.id] / total) if total else 0.0,
                }
                for option in self.options
            ],
        }


class PollOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(
        db.Integer,
        db.ForeignKey("poll.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_order = db.Column(db.SmallInteger, nullable=False)
    text = db.Column(db.String(Poll.OPTION_MAX_LENGTH), nullable=False)

    poll = db.relationship("Poll", back_populates="options")
    votes = db.relationship(
        "PollVote",
        back_populates="option",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("poll_id", "display_order", name="uq_poll_option_order"),
        CheckConstraint(
            f"display_order >= 0 AND display_order < {Poll.MAX_OPTIONS}",
            name="ck_poll_option_order_range",
        ),
    )


class PollVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(
        db.Integer,
        db.ForeignKey("poll.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    option_id = db.Column(
        db.Integer,
        db.ForeignKey("poll_option.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    poll = db.relationship("Poll", back_populates="votes")
    option = db.relationship("PollOption", back_populates="votes")
    user = db.relationship("User")

    __table_args__ = (
        UniqueConstraint("poll_id", "user_id", name="uq_poll_vote_one_per_user"),
    )


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False, index=True)

    author = db.relationship("User", back_populates="comments")
    post = db.relationship("Post", back_populates="comments")

    __table_args__ = (
        UniqueConstraint("author_id", "post_id", "body", name="uq_comment_duplicate_guard"),
    )

