"""
Integration tests for the full user management spec using FastAPI TestClient.
"""

import time
import unittest

from fastapi.testclient import TestClient
from app.api import app
from app.db import db


def _unique(prefix: str) -> str:
    return f"{prefix}_{time.time_ns()}"


class UserManagementTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def _register(self, username: str, email: str, password: str = "Password1"):
        return self.client.post(
            "/register",
            json={"username": username, "email": email, "password": password},
        )

    def _login(self, username: str, password: str = "Password1"):
        return self.client.post(
            "/login", json={"username": username, "password": password}
        )

    def _token(self, response) -> str:
        return response.cookies.get("userjwt")

    def _auth(self, token: str) -> dict:
        return {"userjwt": token}

    def _make_admin(self, user_id: str) -> None:
        db.supabase.table("users").update({"is_admin": True}).eq(
            "id", user_id
        ).execute()


class TestUserListRequiresAuth(UserManagementTestCase):
    def test_list_users_unauthenticated(self):
        resp = self.client.get("/v1/users")
        self.assertEqual(resp.status_code, 401)

    def test_list_users_authenticated(self):
        username = _unique("listuser")
        reg = self._register(username, f"{username}@example.com")
        self.assertEqual(reg.status_code, 201)

        resp = self.client.get("/v1/users", cookies=self._auth(self._token(reg)))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("users", resp.json())
        self.assertTrue(
            any(u["username"] == username for u in resp.json()["users"])
        )

    def test_user_list_excludes_deleted(self):
        username = _unique("deleteme")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        self.client.delete("/v1/users/me", cookies=self._auth(token))

        # Use a different user to list
        other = _unique("other")
        other_reg = self._register(other, f"{other}@example.com")
        resp = self.client.get(
            "/v1/users", cookies=self._auth(self._token(other_reg))
        )
        self.assertEqual(resp.status_code, 200)
        usernames = [u["username"] for u in resp.json()["users"]]
        self.assertNotIn(username, usernames)

    def test_user_list_includes_status(self):
        username = _unique("statususer")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        resp = self.client.get("/v1/users", cookies=self._auth(token))
        self.assertEqual(resp.status_code, 200)
        user_entry = next(
            u for u in resp.json()["users"] if u["username"] == username
        )
        self.assertIn("status", user_entry)
        self.assertEqual(user_entry["status"], "active")


class TestRegistrationAutoLogin(UserManagementTestCase):
    def test_register_sets_session_cookie(self):
        username = _unique("regcookie")
        resp = self._register(username, f"{username}@example.com")
        self.assertEqual(resp.status_code, 201)
        self.assertIsNotNone(self._token(resp))

    def test_registered_user_can_access_protected_endpoint(self):
        username = _unique("regaccess")
        reg = self._register(username, f"{username}@example.com")
        self.assertEqual(reg.status_code, 201)
        resp = self.client.get("/v1/users", cookies=self._auth(self._token(reg)))
        self.assertEqual(resp.status_code, 200)


class TestLoginBlocked(UserManagementTestCase):
    def test_login_blocked_for_deleted_account(self):
        username = _unique("deletedlogin")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        self.client.delete("/v1/users/me", cookies=self._auth(token))

        resp = self._login(username)
        self.assertEqual(resp.status_code, 401)

    def test_login_blocked_for_deactivated_account(self):
        # Create target user
        username = _unique("deactivatedlogin")
        reg = self._register(username, f"{username}@example.com")
        user_id = reg.json()["id"]

        # Create admin
        admin_name = _unique("admin")
        admin_reg = self._register(admin_name, f"{admin_name}@example.com")
        admin_id = admin_reg.json()["id"]
        self._make_admin(admin_id)
        admin_token = self._token(admin_reg)

        # Deactivate the target
        resp = self.client.post(
            f"/v1/users/{user_id}/deactivate", cookies=self._auth(admin_token)
        )
        self.assertEqual(resp.status_code, 200)

        # Login should be blocked
        resp = self._login(username)
        self.assertEqual(resp.status_code, 401)


class TestChangePassword(UserManagementTestCase):
    def test_change_password_success(self):
        username = _unique("changepw")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        resp = self.client.patch(
            "/v1/users/me/password",
            json={"old_password": "Password1", "new_password": "NewPass2"},
            cookies=self._auth(token),
        )
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(self._login(username, "Password1").status_code, 401)
        self.assertEqual(self._login(username, "NewPass2").status_code, 200)

    def test_change_password_wrong_old_password(self):
        username = _unique("wrongpw")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        resp = self.client.patch(
            "/v1/users/me/password",
            json={"old_password": "WrongPass1", "new_password": "NewPass2"},
            cookies=self._auth(token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_change_password_requires_auth(self):
        resp = self.client.patch(
            "/v1/users/me/password",
            json={"old_password": "Password1", "new_password": "NewPass2"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_change_password_invalid_new_password(self):
        username = _unique("badnewpw")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        resp = self.client.patch(
            "/v1/users/me/password",
            json={"old_password": "Password1", "new_password": "short"},
            cookies=self._auth(token),
        )
        self.assertEqual(resp.status_code, 400)


class TestLogout(UserManagementTestCase):
    def test_logout_clears_cookie(self):
        reg = self._register(_unique("logoutcookie"), f"{_unique('lc')}@example.com")
        token = self._token(reg)
        resp = self.client.post("/logout", cookies=self._auth(token))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("userjwt", resp.headers.get("set-cookie", ""))

    def test_token_invalidated_after_logout(self):
        username = _unique("invalidate")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        # Token works before logout
        resp = self.client.get("/v1/users", cookies=self._auth(token))
        self.assertEqual(resp.status_code, 200)

        # Logout — records logged_out_at on the user
        self.client.post("/logout", cookies=self._auth(token))

        # Same token is now rejected (iat <= logged_out_at)
        resp = self.client.get("/v1/users", cookies=self._auth(token))
        self.assertEqual(resp.status_code, 401)

    def test_new_token_valid_after_logout(self):
        username = _unique("relogin")
        reg = self._register(username, f"{username}@example.com")
        old_token = self._token(reg)

        self.client.post("/logout", cookies=self._auth(old_token))

        # Log back in — new token has a later iat
        login_resp = self._login(username)
        new_token = self._token(login_resp)
        self.assertIsNotNone(new_token)

        resp = self.client.get("/v1/users", cookies=self._auth(new_token))
        self.assertEqual(resp.status_code, 200)

    def test_logout_without_token_still_succeeds(self):
        resp = self.client.post("/logout")
        self.assertEqual(resp.status_code, 200)


class TestDeleteAccount(UserManagementTestCase):
    def test_delete_own_account(self):
        username = _unique("selfdelete")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        resp = self.client.delete("/v1/users/me", cookies=self._auth(token))
        self.assertEqual(resp.status_code, 200)

    def test_delete_requires_auth(self):
        resp = self.client.delete("/v1/users/me")
        self.assertEqual(resp.status_code, 401)

    def test_deleted_user_cannot_login(self):
        username = _unique("deletedlogin2")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        self.client.delete("/v1/users/me", cookies=self._auth(token))

        resp = self._login(username)
        self.assertEqual(resp.status_code, 401)

    def test_delete_clears_cookie_in_response(self):
        username = _unique("cookieclear")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        resp = self.client.delete("/v1/users/me", cookies=self._auth(token))
        self.assertEqual(resp.status_code, 200)
        # FastAPI delete_cookie sets the cookie to empty; verify the Set-Cookie header
        set_cookie = resp.headers.get("set-cookie", "")
        self.assertIn("userjwt", set_cookie)


class TestUserDetails(UserManagementTestCase):
    def test_user_details_returns_full_fields(self):
        username = _unique("details")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        resp = self.client.get("/userDetails", cookies=self._auth(token))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("id", data)
        self.assertIn("username", data)
        self.assertIn("email", data)
        self.assertIn("status", data)
        self.assertIn("is_admin", data)
        self.assertEqual(data["status"], "active")
        self.assertFalse(data["is_admin"])

    def test_user_details_requires_auth(self):
        resp = self.client.get("/userDetails")
        self.assertEqual(resp.status_code, 401)


class TestAdminDeactivateReactivate(UserManagementTestCase):
    def _setup_admin(self):
        admin_name = _unique("admin")
        reg = self._register(admin_name, f"{admin_name}@example.com")
        admin_id = reg.json()["id"]
        self._make_admin(admin_id)
        return self._token(reg), admin_id

    def test_admin_deactivate_blocks_login(self):
        admin_token, _ = self._setup_admin()

        username = _unique("deactivatetarget")
        reg = self._register(username, f"{username}@example.com")
        user_id = reg.json()["id"]

        resp = self.client.post(
            f"/v1/users/{user_id}/deactivate", cookies=self._auth(admin_token)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._login(username).status_code, 401)

    def test_admin_reactivate_restores_login(self):
        admin_token, _ = self._setup_admin()

        username = _unique("reactivatetarget")
        reg = self._register(username, f"{username}@example.com")
        user_id = reg.json()["id"]

        self.client.post(
            f"/v1/users/{user_id}/deactivate", cookies=self._auth(admin_token)
        )
        resp = self.client.post(
            f"/v1/users/{user_id}/reactivate", cookies=self._auth(admin_token)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._login(username).status_code, 200)

    def test_non_admin_cannot_deactivate(self):
        username = _unique("noadmin")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        target = _unique("target")
        target_reg = self._register(target, f"{target}@example.com")
        user_id = target_reg.json()["id"]

        resp = self.client.post(
            f"/v1/users/{user_id}/deactivate", cookies=self._auth(token)
        )
        self.assertEqual(resp.status_code, 403)

    def test_deactivate_requires_auth(self):
        # Use a fresh client with no cookies so the request is truly unauthenticated
        fresh = TestClient(app)
        from uuid import uuid4
        resp = fresh.post(f"/v1/users/{uuid4()}/deactivate")
        self.assertEqual(resp.status_code, 401)

    def test_reactivate_requires_auth(self):
        fresh = TestClient(app)
        from uuid import uuid4
        resp = fresh.post(f"/v1/users/{uuid4()}/reactivate")
        self.assertEqual(resp.status_code, 401)

    def test_admin_list_users(self):
        admin_token, _ = self._setup_admin()
        resp = self.client.get("/v1/admin/users", cookies=self._auth(admin_token))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("users", data)
        if data["users"]:
            self.assertIn("email", data["users"][0])

    def test_non_admin_cannot_access_admin_list(self):
        username = _unique("noadminlist")
        reg = self._register(username, f"{username}@example.com")
        token = self._token(reg)

        resp = self.client.get("/v1/admin/users", cookies=self._auth(token))
        self.assertEqual(resp.status_code, 403)

    def test_cannot_deactivate_already_deactivated(self):
        admin_token, _ = self._setup_admin()

        username = _unique("alreadydeact")
        reg = self._register(username, f"{username}@example.com")
        user_id = reg.json()["id"]

        self.client.post(
            f"/v1/users/{user_id}/deactivate", cookies=self._auth(admin_token)
        )
        resp = self.client.post(
            f"/v1/users/{user_id}/deactivate", cookies=self._auth(admin_token)
        )
        self.assertEqual(resp.status_code, 400)

    def test_cannot_reactivate_active_user(self):
        admin_token, _ = self._setup_admin()

        username = _unique("stillactive")
        reg = self._register(username, f"{username}@example.com")
        user_id = reg.json()["id"]

        resp = self.client.post(
            f"/v1/users/{user_id}/reactivate", cookies=self._auth(admin_token)
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
