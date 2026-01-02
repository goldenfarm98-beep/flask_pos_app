from werkzeug.security import generate_password_hash, check_password_hash

from app import db
from app.models import User, PasswordResetToken
from app.routes import _create_password_reset_token


def _create_user(username, email, password):
    user = User(
        username=username,
        email=email,
        password=generate_password_hash(password, method="pbkdf2:sha256", salt_length=8),
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_reset_password_updates_hash_and_marks_token_used(client, app):
    with app.app_context():
        user = _create_user("reset_user", "reset@example.com", "oldpassword")
        token = _create_password_reset_token(user)
        token_value = token.token
        user_id = user.id

    response = client.post(
        f"/reset-password/{token_value}",
        data={"password": "newpassword", "confirm_password": "newpassword"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")

    with app.app_context():
        refreshed_user = db.session.get(User, user_id)
        assert check_password_hash(refreshed_user.password, "newpassword")
        refreshed_token = PasswordResetToken.query.filter_by(token=token_value).first()
        assert refreshed_token.used is True


def test_profile_password_change_requires_current_password(client, app):
    with app.app_context():
        user = _create_user("profile_user", "profile@example.com", "oldpassword")
        user_id = user.id

    with client.session_transaction() as session:
        session["user_id"] = user_id

    response = client.post(
        "/profile",
        data={
            "username": "profile_user",
            "email": "profile@example.com",
            "current_password": "oldpassword",
            "new_password": "newpassword",
            "confirm_password": "newpassword",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/profile" in response.headers.get("Location", "")

    with app.app_context():
        refreshed_user = db.session.get(User, user_id)
        assert check_password_hash(refreshed_user.password, "newpassword")


def test_profile_password_change_rejects_wrong_current_password(client, app):
    with app.app_context():
        user = _create_user("profile_user_two", "profile2@example.com", "oldpassword")
        user_id = user.id

    with client.session_transaction() as session:
        session["user_id"] = user_id

    response = client.post(
        "/profile",
        data={
            "username": "profile_user_two",
            "email": "profile2@example.com",
            "current_password": "wrongpassword",
            "new_password": "newpassword",
            "confirm_password": "newpassword",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/profile" in response.headers.get("Location", "")

    with app.app_context():
        refreshed_user = db.session.get(User, user_id)
        assert check_password_hash(refreshed_user.password, "oldpassword")
