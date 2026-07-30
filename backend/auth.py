"""Email/password authentication routes."""

from __future__ import annotations

from urllib.parse import urlsplit

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db
from models import User


auth_bp = Blueprint("auth", __name__)


def _safe_next_url(raw: str | None) -> str | None:
    candidate = (raw or "").strip()
    parsed = urlsplit(candidate)
    if (
        candidate.startswith("/")
        and not candidate.startswith("//")
        and not parsed.scheme
        and not parsed.netloc
    ):
        return candidate
    return None


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    error = None
    next_url = _safe_next_url(request.args.get("next"))

    if request.method == "POST":
        next_url = _safe_next_url(request.form.get("next")) or next_url
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        password_confirm = request.form.get("password_confirm") or ""

        if not email or "@" not in email:
            error = "올바른 이메일 주소를 입력해 주세요."
        elif len(password) < 6:
            error = "비밀번호는 6자 이상이어야 합니다."
        elif password != password_confirm:
            error = "비밀번호 확인이 일치하지 않습니다."
        elif User.query.filter_by(email=email).first():
            error = "이미 가입된 이메일입니다."
        else:
            user = User(email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(next_url or url_for("index"))

    return render_template(
        "signup.html",
        error=error,
        next_url=next_url or "",
    )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    error = None
    next_url = _safe_next_url(request.args.get("next"))

    if request.method == "POST":
        next_url = _safe_next_url(request.form.get("next")) or next_url
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password):
            error = "이메일 또는 비밀번호가 올바르지 않습니다."
        else:
            login_user(user)
            return redirect(next_url or url_for("index"))

    return render_template(
        "login.html",
        error=error,
        next_url=next_url or "",
    )


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))
