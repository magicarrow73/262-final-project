"""
start_cluster.py
================
Launch a local or distributed cluster of fault-tolerant *chat* servers that
communicate via **gRPC** and coordinate state with **Raft** consensus.

Each server is spawned as a separate Python subprocess, so the cluster can be
run entirely on one machine (handy for demos / unit-tests) or distributed
across several hosts by passing a different `--host` value for each node.
"""

import sys
import os
import subprocess
import time
import argparse
import signal
import atexit

# List to track running processes
running_procs = []

def cleanup():
    """Terminate **all** server subprocesses before the script exits.

    The function is registered with :pymod:`atexit`, making it a finaliser that is
    executed when either the Python interpreter finishes normally or the user sends **SIGINT** (``Ctrl+C``) / **SIGTERM**.

    It first tries a *graceful* ``terminate()``.  If the child has not exited after 500 ms, a hard ``kill()`` is issued as a last resort.
    """
    for proc in running_procs:
        try:
            proc.terminate()
            time.sleep(0.5)
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass

# Register cleanup handler
atexit.register(cleanup)

def start_server(server_id, num_servers, host='127.0.0.1', base_port=50051, base_raft_port=50100):
    """Spawn a single chat server as a detached subprocess.

    Parameters
    ----------
    server_id
        Unique integer identifier ``[0, num_servers)`` for the node.
    num_servers
        Total size of the cluster; used to build each node’s *peer list*.
    host
        Interface that the server binds to.  Can be an IP address or hostname.
    base_port
        First gRPC port – node *i* listens on ``base_port + i``.
    base_raft_port
        First Raft port – node *i* listens on ``base_raft_port + i``.

    Returns
    -------
    str
        The ``"{host}:{grpc_port}"`` address the new server is reachable at.
    """
    # Calculate ports for this server
    grpc_port = base_port + server_id
    raft_port = base_raft_port + server_id
    
    # Generate the list of other servers for Raft consensus
    other_servers = []
    for i in range(num_servers):
        if i != server_id:
            other_servers.append(f"{host}:{base_raft_port + i}")
    
    # Command to start the server
    cmd = [
        sys.executable, "ft_server_grpc.py",
        "--host", host,
        "--port", str(grpc_port),
        "--node-id", str(server_id),
        "--raft-port", str(raft_port),  # Use the unique port
        "--peers", ",".join(other_servers)
    ]
    
    # Start the server process
    print(f"Starting server {server_id} on {host}:{grpc_port} (Raft: {host}:{raft_port})")
    proc = subprocess.Popen(cmd)
    running_procs.append(proc)
    
    # Return the gRPC address of this server
    return f"{host}:{grpc_port}"

def main():
    """Parse CLI flags and launch a full cluster.

    The method is intentionally blocking: it sits in an infinite loop and
    monitors its children.  If any server dies, a warning is printed but the
    script stays alive so that the rest of the cluster keeps running – mimicking
    real‑world tolerance to node failures.
    """
    parser = argparse.ArgumentParser(description="Start a cluster of fault-tolerant chat servers")
    parser.add_argument("--servers", type=int, default=5, help="Number of servers to start")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind servers to")
    parser.add_argument("--base-port", type=int, default=50051, help="Base port for gRPC servers")
    parser.add_argument("--base-raft-port", type=int, default=50100, help="Base port for Raft consensus")
    args = parser.parse_args()
    
    print(f"Starting a cluster of {args.servers} servers...")
    
    # Start each server and collect their addresses
    server_addresses = []
    for i in range(args.servers):
        addr = start_server(
            i, args.servers, args.host, args.base_port, args.base_raft_port
        )
        server_addresses.append(addr)
        time.sleep(1)  # Give each server a moment to start
    
    # Print the cluster information
    print("\nCluster started successfully!")
    print(f"Server addresses: {', '.join(server_addresses)}")
    print("\nTo start a client, run:")
    print(f"python ft_client_grpc.py --servers {','.join(server_addresses)}")
    print("\nPress Ctrl+C to stop the cluster...")
    
    # Keep the cluster running until interrupted
    crashed_set = set()
    try:
        while True:
            time.sleep(1)

            for i, proc in enumerate(running_procs):
                # If we already reported this server as crashed, skip
                if i in crashed_set:
                    continue
                
                if proc.poll() is not None:
                    print(f"Warning: Server {i} has crashed (exit code: {proc.returncode})")
                    crashed_set.add(i)

    except KeyboardInterrupt:
        print("\nStopping the cluster...")

if __name__ == "__main__":
    main()
