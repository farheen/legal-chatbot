"""User accounts (scrypt password hashes in the database) and the audit log.

    python -m legalbot.auth add-user alice      # prompts for a password
    python -m legalbot.auth remove-user alice
    python -m legalbot.auth list-users
"""
import argparse
import getpass
import hashlib
import hmac
import json
import os
import sqlite3

from .db import connect

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)


# A real hash to compare against when the username does not exist, so lookups take the same time either way.
_DUMMY_HASH = hash_password(os.urandom(8).hex())


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> bool:
    row = conn.execute("SELECT password_hash FROM users WHERE username = ?", (username,)).fetchone()
    ok = check_password(password, row["password_hash"] if row else _DUMMY_HASH)
    return ok and row is not None


def add_user(conn: sqlite3.Connection, username: str, password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")
    with conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?) "
            "ON CONFLICT (username) DO UPDATE SET password_hash = excluded.password_hash",
            (username, hash_password(password)),
        )


def audit(conn: sqlite3.Connection, username: str | None, action: str, detail: dict | None = None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO audit_log (username, action, detail) VALUES (?, ?, ?)",
            (username, action, json.dumps(detail) if detail is not None else None),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("add-user").add_argument("username")
    sub.add_parser("remove-user").add_argument("username")
    sub.add_parser("list-users")
    args = parser.parse_args()
    conn = connect()
    if args.command == "add-user":
        password = getpass.getpass("Password (12+ characters): ")
        if password != getpass.getpass("Repeat password: "):
            raise SystemExit("Passwords do not match.")
        add_user(conn, args.username, password)
        print(f"Saved user {args.username}.")
    elif args.command == "remove-user":
        with conn:
            conn.execute("DELETE FROM users WHERE username = ?", (args.username,))
        print(f"Removed user {args.username}.")
    else:
        for row in conn.execute("SELECT username, created_at FROM users ORDER BY username"):
            print(row["username"], row["created_at"])


if __name__ == "__main__":
    main()
