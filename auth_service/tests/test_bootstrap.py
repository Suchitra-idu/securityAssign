from shared_security.passwords import verify_password

from auth_service.application.bootstrap import ensure_admin


def test_ensure_admin_creates_when_missing(bag):
    ensure_admin(username="root", password="hunter2-hunter2", deps=bag.deps)
    user = bag.users.get_by_username("root")
    assert user is not None
    assert user.role == "admin"
    assert verify_password("hunter2-hunter2", user.password_hash)


def test_ensure_admin_no_op_when_user_exists(bag, registered_admin):
    # registered_admin already created "root" with password "hunter2-hunter2"
    ensure_admin(username="root", password="different-password", deps=bag.deps)
    user = bag.users.get_by_username("root")
    # Existing user unchanged: original password still verifies, new one does not.
    assert verify_password("hunter2-hunter2", user.password_hash)
    assert not verify_password("different-password", user.password_hash)


def test_ensure_admin_is_idempotent_across_multiple_calls(bag):
    ensure_admin(username="root", password="hunter2-hunter2", deps=bag.deps)
    ensure_admin(username="root", password="hunter2-hunter2", deps=bag.deps)
    ensure_admin(username="root", password="hunter2-hunter2", deps=bag.deps)
    # Only one user with that username exists.
    assert bag.users.get_by_username("root") is not None
    assert len(bag.users._by_username) == 1
