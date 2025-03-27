Group 10 (Kevin Cong, Russell Li)
---

# gRPC Fault-Tolerant Chat System

This project implements a fault-tolerant chat service using gRPC and Raft consensus. Following the specifications, our system is designed to remain available and consistent even if several nodes fail. The state is replicated across a cluster of nodes, and users can create accounts, log in, send messages, and read persisted messages even after a cluster restart.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Testing](#testing)
- [Engineering Notebook](#engineering-notebook)

## Features

- **Fault Tolerance:** Our chat service uses a Raft-based replication strategy to tolerate up to *f* node failures in a 2*f*+1 node cluster.
- **Persistence:** User accounts and messages are stored persistently in SQLite databases on each node even in the face of shutdown.
- **Automatic Reconnection:** The client automatically reconnects to surviving nodes if one or more nodes become unavailable.
- **Real-time Messaging:** Server streaming is used to push incoming messages to logged-in users.

## Installation

We use a conda environment for this project. Please follow these steps to set up the environment:

1. **Clone the repository:**

   ```bash
   git clone https://github.com/magicarrow73/262-gRPC.git
   cd 262-gRPC
   ```

2. **Create the conda environment:**

   Our environment is specified in the [`environment.yaml`](./environment.yaml) file. To create the environment, run:

   ```bash
   conda env create -f environment.yaml
   ```

   *Note:* We have removed the `prefix` field from the YAML file to ensure that the environment can be created on any system.

3. **Activate the environment:**

   ```bash
   conda activate 262-env
   ```

## Usage

### Starting the Cluster

Start the cluster using the provided `start_cluster.py` script. For example, to start a 5-node cluster, run:

```bash
python start_cluster.py --servers 5
```

Make sure you are in the project root directory (the directory that contains the `system_main` folder) when you run this command.

### Running the Client

In a separate terminal, you can start the fault-tolerant client using the `ft_client_grpc.py` script. For example:

```bash
python ft_client_grpc.py --servers 127.0.0.1:50051,127.0.0.1:50052,127.0.0.1:50053,127.0.0.1:50054,127.0.0.1:50055
```

The client provides a simple GUI to create accounts, log in, send messages, list users, read messages, and delete messages or accounts.

## Testing

We have included a comprehensive test suite to verify the fault tolerance and persistence features of the system. To run the tests, navigate to the project root and run:

```bash
python -m unittest discover -s system_main
```

Make sure that the working directory is set to the project root so that the module paths are correct.

## Engineering Notebook

For more detail, please refer to our [Engineering Notebook](https://docs.google.com/document/d/1esiCXiTv-_OiAmb66p9OGL7wYtLlkvueDtkRiMJyd2w/edit?usp=sharing).

---

Thanks for reading, and if you encounter any issues, please refer to the engineering notebook for further context.
