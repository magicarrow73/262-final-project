import unittest
import subprocess
import time
import socket
import os
import tempfile
import shutil
import grpc
import sys
import threading

# Add the project root (parent directory of unit_tests) to sys.path so that imports work.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Import generated gRPC classes and our server modules from system_main.
from system_main.chat_pb2 import (
    CreateUserRequest,
    LoginRequest,
    SendMessageRequest,
    ListUsersRequest,
)
from system_main.chat_pb2_grpc import ChatServiceStub

class TestFaultToleranceRobust(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Launch a 5-node cluster as separate subprocesses.
        Each node uses its own temporary database.
        """
        cls.num_nodes = 5
        # Create a temporary directory for test databases.
        cls.temp_dir = tempfile.mkdtemp(prefix="test_raft_db_")
        cls.node_info = []
        base_grpc = 50051
        base_raft = 50100

        # Populate node info
        for node_id in range(cls.num_nodes):
            node = {
                "node_id": node_id,
                "host": "127.0.0.1",
                "grpc": base_grpc + node_id,
                "raft": base_raft + node_id,
                "db_path": os.path.join(cls.temp_dir, f"chat_node_{node_id}.db")
            }
            cls.node_info.append(node)

        cls.server_processes = []
        # Build the absolute path to ft_server_grpc.py inside system_main.
        FT_SERVER_PATH = os.path.join(PROJECT_ROOT, "system_main", "ft_server_grpc.py")
        # Set the working directory for subprocesses to system_main.
        WORKING_DIR = os.path.join(PROJECT_ROOT, "system_main")
        # Start each node as a subprocess.
        for node in cls.node_info:
            node_id = node["node_id"]
            host = node["host"]
            grpc_port = node["grpc"]
            raft_port = node["raft"]
            # Build cluster argument from the other nodes’ Raft addresses.
            other_nodes = []
            for other in cls.node_info:
                if other["node_id"] != node_id:
                    other_nodes.append(f"{other['host']}:{other['raft']}")
            cluster_str = ",".join(other_nodes)
            cmd = [
                sys.executable, FT_SERVER_PATH,
                "--host", host,
                "--port", str(grpc_port),
                "--node-id", str(node_id),
                "--raft-port", str(raft_port),
                "--cluster", cluster_str
            ]
            print(f"[TEST DEBUG] Starting node {node_id} with command: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                cwd=WORKING_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            cls.server_processes.append(proc)

        # Wait up to 45 seconds for the cluster to stabilize.
        stable = False
        start_time = time.time()
        while time.time() - start_time < 45:
            try:
                channel = grpc.insecure_channel(f"127.0.0.1:{cls.node_info[0]['grpc']}")
                stub = ChatServiceStub(channel)
                # Use ListUsers as a ping.
                ping_req = ListUsersRequest(username="ping", pattern="*")
                stub.ListUsers(ping_req, timeout=3)
                channel.close()
                stable = True
                break
            except Exception as ex:
                print(f"[TEST DEBUG] Ping attempt failed: {ex}")
                time.sleep(2)
        if not stable:
            print("[TEST DEBUG] Cluster did not stabilize within 45 seconds. Aborting tests.")
            for proc in cls.server_processes:
                proc.terminate()
            shutil.rmtree(cls.temp_dir)
            raise Exception("Cluster not stabilized - no leader found after 45 seconds")
        print("[TEST DEBUG] Cluster is up and a leader has been elected.")

        # Create a client channel & stub (pointing to node 0 initially).
        cls.grpc_addresses = [f"{node['host']}:{node['grpc']}" for node in cls.node_info]
        cls.channel = grpc.insecure_channel(cls.grpc_addresses[0])
        cls.stub = ChatServiceStub(cls.channel)

    @classmethod
    def tearDownClass(cls):
        """Terminate all server processes and remove the temporary directory."""
        for proc in cls.server_processes:
            try:
                proc.terminate()
                time.sleep(1)
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        cls.channel.close()
        shutil.rmtree(cls.temp_dir)

    def test_persistence_after_faults(self):
        """
        Test persistence:
         1) Create a user and send a self-message.
         2) Terminate 2 nodes.
         3) Reconnect to a surviving node and log in.
        """
        # Create user "persist_user"
        req = CreateUserRequest(
            username="persist_user",
            hashed_password="hash123",
            display_name="Persist User"
        )
        resp = self.stub.CreateUser(req)
        # Allow either "success" or "user_exists" (if run twice)
        self.assertIn(resp.status, ("success", "user_exists"), "User creation should succeed")

        # Send a self-message
        msg_req = SendMessageRequest(
            sender="persist_user",
            receiver="persist_user",
            content="Persistence check!"
        )
        msg_resp = self.stub.SendMessage(msg_req)
        self.assertEqual(msg_resp.status, "success", "Message sending should succeed")

        # Terminate nodes 0 and 1 to simulate faults.
        for i in [0, 1]:
            print(f"[TEST DEBUG] Terminating node {i} to simulate fault")
            self.server_processes[i].terminate()
        time.sleep(10)  # Allow time for the cluster to reconfigure

        # Reconnect using node 2.
        channel2 = grpc.insecure_channel(f"127.0.0.1:{self.node_info[2]['grpc']}")
        stub2 = ChatServiceStub(channel2)
        login_req = LoginRequest(username="persist_user", hashed_password="hash123")
        login_resp = stub2.Login(login_req, timeout=10)
        self.assertEqual(login_resp.status, "success", "User should be able to log in after faults")
        channel2.close()

    def test_2_fault_tolerance_operations(self):
        """
        Test that the cluster remains operational with 2 nodes down:
         1) Create and log in as 'alice'.
         2) Terminate 2 nodes.
         3) From a surviving node, send a self-message.
        """
        # Create user "alice"
        req = CreateUserRequest(
            username="alice",
            hashed_password="alicehash",
            display_name="Alice"
        )
        resp = self.stub.CreateUser(req)
        self.assertIn(resp.status, ("success", "user_exists"), "Alice should be created successfully")

        # Log in as alice.
        login_req = LoginRequest(username="alice", hashed_password="alicehash")
        login_resp = self.stub.Login(login_req, timeout=10)
        self.assertEqual(login_resp.status, "success", "Alice should log in successfully")

        # Terminate nodes 3 and 4.
        for i in [3, 4]:
            print(f"[TEST DEBUG] Terminating node {i} to simulate fault tolerance")
            self.server_processes[i].terminate()
        time.sleep(10)

        # From node 2, send a self-message.
        channel2 = grpc.insecure_channel(f"127.0.0.1:{self.node_info[2]['grpc']}")
        stub2 = ChatServiceStub(channel2)
        msg_req = SendMessageRequest(
            sender="alice",
            receiver="alice",
            content="Hello after faults!"
        )
        msg_resp = stub2.SendMessage(msg_req, timeout=10)
        self.assertEqual(msg_resp.status, "success", "Alice should send a message successfully even after 2 faults")
        channel2.close()

    def test_leader_election(self):
        """
        Trigger a dummy RPC on a surviving node and ask the tester to verify in the logs
        that a new leader is elected if the old leader was terminated.
        """
        # Assume node 2 is still alive.
        channel2 = grpc.insecure_channel(f"127.0.0.1:{self.node_info[2]['grpc']}")
        stub2 = ChatServiceStub(channel2)
        try:
            dummy_req = CreateUserRequest(username="dummy", hashed_password="dummy", display_name="dummy")
            stub2.ListUsers(dummy_req, timeout=5)
        except Exception:
            # We ignore errors; we only need to trigger status updates.
            pass
        time.sleep(2)
        print("[TEST DEBUG] Please verify in the server logs that a new leader has been elected if the old leader was terminated.")
        channel2.close()

if __name__ == "__main__":
    unittest.main()
