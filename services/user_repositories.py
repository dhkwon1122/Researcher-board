from __future__ import annotations

import json
import os
from typing import Protocol

from services import user_store


USERS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config',
    'users.json',
)


class UserRepository(Protocol):
    def available(self) -> bool: ...
    def get_user(self, user_id: str) -> dict | None: ...
    def list_users(self) -> list[dict]: ...
    def has_any(self) -> bool: ...
    def create(self, user_id: str, password_hash: str, display_name: str, role: str,
               email: str = '', must_change_password: bool = False,
               is_admin: bool = False) -> bool: ...
    def update_fields(self, user_id: str, display_name: str | None = None,
                      role: str | None = None, email: str | None = None,
                      is_admin: bool | None = None) -> bool: ...
    def set_password_hash(self, user_id: str, password_hash: str) -> bool: ...
    def delete_user(self, user_id: str) -> bool: ...


class DbUserRepository:
    def available(self) -> bool:
        return user_store.available()

    def get_user(self, user_id: str) -> dict | None:
        return user_store.get_user(user_id)

    def list_users(self) -> list[dict]:
        return user_store.list_all()

    def has_any(self) -> bool:
        return user_store.has_any()

    def create(self, user_id: str, password_hash: str, display_name: str, role: str,
               email: str = '', must_change_password: bool = False,
               is_admin: bool = False) -> bool:
        return user_store.create(
            user_id, password_hash, display_name, role, email,
            must_change_password=must_change_password, is_admin=is_admin,
        )

    def update_fields(self, user_id: str, display_name: str | None = None,
                      role: str | None = None, email: str | None = None,
                      is_admin: bool | None = None) -> bool:
        return user_store.update_fields(user_id, display_name, role, email, is_admin)

    def set_password_hash(self, user_id: str, password_hash: str) -> bool:
        return user_store.set_password_hash(user_id, password_hash)

    def delete_user(self, user_id: str) -> bool:
        return user_store.delete_user(user_id)


class JsonUserRepository:
    def __init__(self, path: str = USERS_FILE) -> None:
        self.path = path

    def available(self) -> bool:
        return True

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding='utf-8') as f:
            return json.load(f)

    def _save(self, users: dict) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)

    def get_user(self, user_id: str) -> dict | None:
        data = self._load().get(user_id)
        if data is None:
            return None
        return {'user_id': user_id, **data}

    def list_users(self) -> list[dict]:
        return [{'user_id': uid, **data} for uid, data in self._load().items()]

    def has_any(self) -> bool:
        return bool(self._load())

    def create(self, user_id: str, password_hash: str, display_name: str, role: str,
               email: str = '', must_change_password: bool = False,
               is_admin: bool = False) -> bool:
        users = self._load()
        if user_id in users:
            return False
        users[user_id] = {
            'password_hash': password_hash,
            'display_name': display_name,
            'role': role,
            'email': email,
            'must_change_password': must_change_password,
            'is_admin': is_admin,
        }
        self._save(users)
        return True

    def update_fields(self, user_id: str, display_name: str | None = None,
                      role: str | None = None, email: str | None = None,
                      is_admin: bool | None = None) -> bool:
        users = self._load()
        if user_id not in users:
            return False
        if display_name is not None:
            users[user_id]['display_name'] = display_name
        if role is not None:
            users[user_id]['role'] = role
        if email is not None:
            users[user_id]['email'] = email
        if is_admin is not None:
            users[user_id]['is_admin'] = is_admin
        self._save(users)
        return True

    def set_password_hash(self, user_id: str, password_hash: str) -> bool:
        users = self._load()
        if user_id not in users:
            return False
        users[user_id]['password_hash'] = password_hash
        users[user_id]['must_change_password'] = False
        self._save(users)
        return True

    def delete_user(self, user_id: str) -> bool:
        users = self._load()
        if user_id not in users:
            return False
        del users[user_id]
        self._save(users)
        return True
