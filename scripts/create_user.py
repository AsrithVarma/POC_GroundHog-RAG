"""CLI tool to create a user in the GroundHog RAG system.

Reads database connection from environment variables.
Never stores or logs plaintext passwords.

Usage:
    python scripts/create_user.py --username alice --access-group legal --role analyst
"""

import argparse
import getpass
import logging
import os
import sys
import uuid

import psycopg2
from passlib.context import CryptContext

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

VALID_ROLES = ("admin", "analyst", "viewer")


def get_db_connection():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def create_user(
    username: str,
    password: str,
    access_group: str,
    role: str,
) -> str:
    password_hash = pwd_context.hash(password)
    user_id = str(uuid.uuid4())

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Check for existing user
            cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                logger.error("User '%s' already exists", username)
                sys.exit(1)

            cur.execute(
                """
                INSERT INTO users (id, username, password_hash, access_group, role)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, username, password_hash, access_group, role),
            )
            conn.commit()
    except Exception:
        conn.rollback()
        logger.error("Failed to create user '%s'", username, exc_info=True)
        sys.exit(1)
    finally:
        conn.close()

    return user_id


def main():
    parser = argparse.ArgumentParser(description="Create a GroundHog RAG user")
    parser.add_argument("--username", required=True, help="Unique username")
    parser.add_argument("--access-group", required=True, help="RBAC access group")
    parser.add_argument(
        "--role",
        required=True,
        choices=VALID_ROLES,
        help="User role: admin, analyst, or viewer",
    )
    args = parser.parse_args()

    # Prompt for password securely (no echo, no logging)
    password = getpass.getpass("Enter password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        logger.error("Passwords do not match")
        sys.exit(1)

    if len(password) < 8:
        logger.error("Password must be at least 8 characters")
        sys.exit(1)

    user_id = create_user(args.username, password, args.access_group, args.role)

    logger.info(
        "User created — username=%s, role=%s, access_group=%s, id=%s",
        args.username,
        args.role,
        args.access_group,
        user_id,
    )


if __name__ == "__main__":
    main()
