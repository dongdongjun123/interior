"""Persistent user accounts and saved interior-design history."""

from __future__ import annotations

from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    designs = db.relationship(
        "SavedDesign",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class SavedDesign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    title = db.Column(db.String(255), nullable=False)

    generated_file = db.Column(db.String(255))
    original_floorplan_file = db.Column(db.String(255))
    modified_floorplan_file = db.Column(db.String(255))
    selected_products_file = db.Column(db.String(255))
    description = db.Column(db.Text)
    tags_json = db.Column(db.Text, nullable=False, default="[]")
    furniture_choices_json = db.Column(db.Text, nullable=False, default="[]")
    purchase_items_json = db.Column(db.Text, nullable=False, default="[]")

    user = db.relationship("User", back_populates="designs")
