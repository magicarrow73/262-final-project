import unittest
import os

os.environ["CHAT_DB_PATH"] = ":memory:"

from system_main.db import init_db, create_user, get_user_by_username, delete_user, close_db
from system_main.utils import hash_password, verify_password


class TestUserOperations(unittest.TestCase):
    def setUp(self):
        """
        Runs before each test method, calls init_db() to give each test a clean slate
        """
        init_db()
        self.username = "rahul"
        self.password = "secret123"
        self.hashed_pw = hash_password(self.password)
        self.display_name = "Rahul"

    def tearDown(self):
        close_db()

    def test_create_user(self):
        """
        Verify that we can create a new user and that creating the same user again returns False because it is a duplicate
        """
        success = create_user(self.username, self.hashed_pw, self.display_name)
        self.assertTrue(success)
        #this is the second creation so it should fail
        duplicate = create_user(self.username, self.hashed_pw, self.display_name)
        self.assertFalse(duplicate)

    def test_get_user_by_username(self):
        """
        Recreate the user and verify that we can retrieve it correctly
        """
        create_user(self.username, self.hashed_pw, self.display_name)
        row = get_user_by_username(self.username)
        self.assertIsNotNone(row)
        stored_hash = row["password_hash"]
        self.assertTrue(verify_password(self.password, stored_hash))

    def test_delete_user(self):
        """
        Verify we can delete the user correctly
        """
        create_user(self.username, self.hashed_pw, self.display_name)
        was_deleted = delete_user(self.username)
        self.assertTrue(was_deleted)
        row = get_user_by_username(self.username)
        self.assertIsNone(row)

if __name__ == "__main__":
    unittest.main()
