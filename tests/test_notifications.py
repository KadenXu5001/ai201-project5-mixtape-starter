"""
tests/test_notifications.py - Mixtape

Tests for notification logic.
"""

import pytest
from app import create_app, db
from models import Notification, Song, User
from services.notification_service import rate_song


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_rating_data(app):
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(
            title="Shared Track",
            artist="Artist X",
            shared_by=sharer.id,
        )
        db.session.add(song)
        db.session.commit()

        yield {
            "sharer": sharer,
            "rater": rater,
            "song": song,
        }


def test_rating_a_song_creates_notification_for_sharer(app, seed_rating_data):
    with app.app_context():
        rate_song(seed_rating_data["rater"].id, seed_rating_data["song"].id, 4)

        notifications = db.session.query(Notification).filter_by(
            user_id=seed_rating_data["sharer"].id
        ).all()

        assert len(notifications) == 1
        assert notifications[0].notification_type == "song_rated"
        assert "rater rated your song 'Shared Track' 4/5." == notifications[0].body


def test_rating_your_own_song_does_not_create_notification(app, seed_rating_data):
    with app.app_context():
        rate_song(seed_rating_data["sharer"].id, seed_rating_data["song"].id, 5)

        notifications = db.session.query(Notification).filter_by(
            user_id=seed_rating_data["sharer"].id
        ).all()

        assert notifications == []
