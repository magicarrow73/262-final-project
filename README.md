Below is our documentation.
---

# Fault-Tolerant gRPC Chat Service

This repository contains a fault-tolerant chat service implemented using gRPC and a Raft consensus algorithm for state replication. The system is designed to handle node failures while maintaining persistent user data and messages.

## Overview

Our chat service allows users to:
- Create user accounts
- Log in and log out
- Send and read messages
- List available users
- Delete messages and accounts

The system leverages Raft to replicate state across a cluster of nodes, ensuring that the service continues to operate even if some nodes fail. Persistence is maintained via local SQLite databases on each node.

## Features

- **Fault Tolerance:** The system is designed to withstand up to *f* node failures in a 2f+1 node cluster.
- **Persistence:** User accounts and messages are stored in local SQLite databases and persist even after node restarts.
- **Leader Election:** If the current leader fails, a new leader is elected automatically.
- **gRPC Interface:** All operations are accessible through a gRPC interface for efficient communication.

## Installation

1. **Clone the Repository:**

   ```bash
   git clone https://github.com/magicarrow73/262-gRPC.git
   cd 262-gRPC
   ```

2. **Create a Virtual Environment and Install Dependencies:**

   ```bash
   python -m venv 262-env
   source 262-env/bin/activate
   pip install -r requirements.txt
   ```

   > **Note:** Ensure that you have the required version of `grpcio` and `grpcio-tools` to match the generated protobuf code.

## Running the Cluster and Client

You can start the cluster and client using the provided scripts. For example:

1. **Start the Cluster:**

   Open a terminal and run:

   ```bash
   python start_cluster.py --servers 5
   ```

   This command starts a 5-node cluster. The nodes are configured using the `ft_server_grpc.py` file and each node uses its own SQLite database.

2. **Start the Client:**

   Open another terminal and run:

   ```bash
   python ft_client_grpc.py --servers 127.0.0.1:50051,127.0.0.1:50052,127.0.0.1:50053,127.0.0.1:50054,127.0.0.1:50055
   ```

   This launches a Tkinter-based client that connects to the cluster. You can then create accounts, log in, and send messages through the GUI.

## Testing

We have included a comprehensive set of unit and integration tests to ensure that:
- The persistent data store works correctly.
- The system maintains fault tolerance (i.e., it remains operational when some nodes fail).
- The cluster correctly re-elects a leader when the current leader fails.
- Data persists even after the cluster is shut down and restarted.

To run the tests, execute the following command from the project root:

```bash
python -m unittest discover -s unit_tests
```

> **Note:** Our tests include scenarios for normal operations as well as fault-tolerance cases. For detailed information about each test, please refer to the [Engineering Notebook](#engineering-notebook).

## Engineering Notebook

For more detailed explanations of our design decisions, implementation challenges, and testing procedures, please refer to our [Engineering Notebook](https://docs.google.com/document/d/1esiCXiTv-_OiAmb66p9OGL7wYtLlkvueDtkRiMJyd2w/edit?usp=sharing). This document includes:
- Detailed design diagrams and flowcharts
- Discussion of fault tolerance and persistence strategies
- Testing methodologies and results
- Lessons learned and future improvements

## Contributing

We welcome contributions! If you would like to contribute to this project, please fork the repository and submit a pull request with your changes. Be sure to include tests for any new functionality.

## License

This project is licensed under the [MIT License](LICENSE).

---

We hope this README provides a clear overview of the project, its features, and how to get started. For further details, please refer to our Engineering Notebook via the link above.

If you have any questions, please feel free to contact us.
