import unittest
import os

os.environ["CHAT_DB_PATH"] = ":memory:"

from system_main.db import init_db, close_db, create_user, get_user_by_username, delete_user, create_message, get_messages_for_user, mark_message_read, delete_message, get_num_unread_messages
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

class TestMessageOperations(unittest.TestCase):
    def setUp(self):
        """
        Runs before each test method, calls init_db() and creates two sample users
        """
        init_db()
        self.userA = "rahul"
        self.passA = "rahulpw"
        self.userB = "brandon"
        self.passB = "brandonpw"

        create_user(self.userA, hash_password(self.passA), "Rahul User")
        create_user(self.userB, hash_password(self.passB), "Brandon User")

    def tearDown(self):
        close_db()

    def test_create_message(self):
        """
        Verify we can create a message between two users
        """
        success = create_message(self.userA, self.userB, "Hello, Brandon!")
        self.assertTrue(success, "Should succeed for valid sender and receiver")

        # Try sending to nonexistent user
        fail = create_message(self.userA, "kcong", "Are you there?")
        self.assertFalse(fail, "Creating a message to a nonexistent user should fail")

    def test_get_messages_for_user(self):
        """
        Verify fetching messages for a user works and that we can perform unread filtering
        """
        create_message(self.userA, self.userB, "Message 1")
        create_message(self.userA, self.userB, "Message 2")
        create_message(self.userB, self.userA, "Reply 1")

        brandon_msgs = get_messages_for_user(self.userB)
        self.assertEqual(len(brandon_msgs), 2, "Brandon should have 2 messages from Rahul")

        rahul_msgs = get_messages_for_user(self.userA)
        self.assertEqual(len(rahul_msgs), 1, "Rahul should have 1 message from Brandon")

        unread_brandon = get_messages_for_user(self.userB, only_unread=True)
        self.assertEqual(len(unread_brandon), 2, "Brandon's 2 messages are still unread")

    def test_mark_message_read(self):
        """
        Verify marking a message as read updates read_status
        """
        create_message(self.userA, self.userB, "Test read message")
        brandon_msgs = get_messages_for_user(self.userB)
        msg_id = brandon_msgs[0]["id"]

        marked = mark_message_read(msg_id, self.userB)
        self.assertTrue(marked, "Brandon should be able to mark his message as read")

        unread_count = get_num_unread_messages(self.userB)
        self.assertEqual(unread_count, 0, "Brandon should have 0 unread messages now")

        not_marked = mark_message_read(msg_id, self.userA)
        self.assertFalse(not_marked, "Rahul cannot mark Brandon's message as read")

    def test_delete_message(self):
        """
        Verify deleting messages can be done by either sender or receiver
        """
        create_message(self.userA, self.userB, "To Brandon #1")
        create_message(self.userA, self.userB, "To Brandon #2")

        brandon_msgs = get_messages_for_user(self.userB)
        self.assertEqual(len(brandon_msgs), 2)

        msg_id = brandon_msgs[0]["id"]
        deleted = delete_message(msg_id, self.userB)
        self.assertTrue(deleted, "Receiver should be able to delete the message")

        updated_brandon_msgs = get_messages_for_user(self.userB)
        self.assertEqual(len(updated_brandon_msgs), 1, "One message remains for Brandon")

        second_id = updated_brandon_msgs[0]["id"]
        deleted_by_sender = delete_message(second_id, self.userA)
        self.assertTrue(deleted_by_sender, "Sender should also be able to delete the message")

        final_brandon_msgs = get_messages_for_user(self.userB)
        self.assertEqual(len(final_brandon_msgs), 0, "No messages left for Brandon")

    def test_cascade_delete_on_user_removal(self):
        """
        Verify that deleting a user also deletes any messages that involve them as a sender or receiver
        """
        create_message(self.userA, self.userB, "Hello from Rahul")
        create_message(self.userB, self.userA, "Hello from Brandon")
        self.assertEqual(len(get_messages_for_user(self.userB)), 1)
        self.assertEqual(len(get_messages_for_user(self.userA)), 1)

        success = delete_user(self.userB)
        self.assertTrue(success, "Brandon user should be deleted")
        rahul_inbox_after = get_messages_for_user(self.userA)
        self.assertEqual(len(rahul_inbox_after), 0,
            "Deleting Brandon should remove messages from Brandon->Rahul too")

if __name__ == "__main__":
    unittest.main()
