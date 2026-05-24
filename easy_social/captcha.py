from __future__ import annotations

import io
import random
import secrets
import string
import time
from typing import Any

from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

ALPHABET = string.ascii_uppercase + string.digits
LENGTH = 5
TTL_SECONDS = 300
WIDTH, HEIGHT = 180, 60
SESSION_KEY = "_captcha"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def generate_answer() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().upper()


def hash_answer(answer: str) -> str:
    return generate_password_hash(_normalize(answer))


def verify_answer(submitted: str | None, expected_hash: str | None) -> bool:
    if not expected_hash:
        return False
    candidate = _normalize(submitted)
    if len(candidate) != LENGTH:
        return False
    return check_password_hash(expected_hash, candidate)


def render_image(answer: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    img = Image.new("RGB", (WIDTH, HEIGHT), color=(245, 245, 240))
    draw = ImageDraw.Draw(img)

    for _ in range(8):
        x1, y1 = random.randint(0, WIDTH), random.randint(0, HEIGHT)
        x2, y2 = random.randint(0, WIDTH), random.randint(0, HEIGHT)
        color = tuple(random.randint(120, 200) for _ in range(3))
        draw.line([(x1, y1), (x2, y2)], fill=color, width=1)

    font = _load_font(36)
    for i, ch in enumerate(answer):
        x = 15 + i * 30 + random.randint(-4, 4)
        y = 8 + random.randint(-6, 6)
        color = tuple(random.randint(0, 80) for _ in range(3))
        draw.text((x, y), ch, fill=color, font=font)

    for _ in range(200):
        x, y = random.randint(0, WIDTH - 1), random.randint(0, HEIGHT - 1)
        draw.point((x, y), fill=(0, 0, 0))

    img = img.filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _load_font(size: int):
    from PIL import ImageFont

    candidates = ("arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf")
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def issue_to_session(session: Any) -> str:
    answer = generate_answer()
    record: dict[str, Any] = {
        "hash": hash_answer(answer),
        "expires_at": time.time() + TTL_SECONDS,
    }
    if current_app.config.get("TESTING"):
        record["_test_plain"] = answer
    session[SESSION_KEY] = record
    return answer


def consume_from_session(session: Any, submitted: str | None) -> bool:
    record = session.pop(SESSION_KEY, None)
    if not isinstance(record, dict):
        return False
    try:
        expires_at = float(record.get("expires_at", 0))
    except (TypeError, ValueError):
        return False
    if time.time() > expires_at:
        return False
    return verify_answer(submitted, record.get("hash"))
