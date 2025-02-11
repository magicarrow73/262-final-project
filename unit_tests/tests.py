import unittest
from system_main.db import init_db, create_user, get_user_by_username, delete_user
from system_main.utils import hash_password, verify_password


class TestUserOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        This will run run once before all tests, and we call init_db() to make sure 'users' table exists
        """
        init_db()

    def test_create_user(self):
        """
        Verify that we can create a new user and that creating the same user again returns False because it is a duplicate
        """
        username = "rahul"
        password = "secret123"
        hashed_pw = hash_password(password)
        display_name = "Rahul"

        #this is the first creation so it should succeed
        success = create_user(username, hashed_pw, display_name)
        self.assertTrue(success, "Creating a fresh user should succeed")

        #this is the second creation so it should fail
        duplicate = create_user(username, hashed_pw, display_name)
        self.assertFalse(duplicate, "Duplicate username creation should fail")

    def test_get_user_by_username(self):
        """
        Check that we can retrieve the user we created, and that the stored hash is correct
        """
        username = "rahul"
        password = "secret123"

        row = get_user_by_username(username)
        self.assertIsNotNone(row, "Should find 'rahul' in DB")

        stored_hash = row["password_hash"]
        self.assertTrue(verify_password(password, stored_hash), "verify_password should match the stored hash")

    def test_delete_user(self):
        """
        Verify we can delete the user correctly
        """
        username = "rahul"
        was_deleted = delete_user(username)
        self.assertTrue(was_deleted, "Deleting existing user 'rahul' should succeed")

        # Now it should be gone
        row = get_user_by_username(username)
        self.assertIsNone(row, "User 'rahul' should no longer exist in DB")

if __name__ == "__main__":
    unittest.main()
