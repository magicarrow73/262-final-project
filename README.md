Group 10 (Kevin Cong, Russell Li)
---

# CS 262 Final Project: Combinatorial Auction

This project implements a robust distributed combinatorial auction service using gRPC and Raft consensus. Following the specifications, our system is designed to remain available and consistent even if several nodes fail. The state is replicated across a cluster of nodes, and users can create accounts, log in, start auctions, show bids, and review auction results.

## Table of Contents

- [Features](#features)
- [Usage](#usage)
- [Testing](#testing)
- [Engineering Notebook](#engineering-notebook)

## Features

- **Fault Tolerance:** Our chat service uses a Raft-based replication strategy to tolerate up to *f* node failures in a 2*f*+1 node cluster.
- **Persistence:** User accounts and auction results are stored persistently in SQLite databases on each node even in the face of shutdown.
- **Automatic Reconnection:** The client automatically reconnects to surviving nodes if one or more nodes become unavailable.

## Usage

### Initialization

Please refer to the requirements-dev.txt file for information on the necessary contents of a virtual environment to run the service. For setup it is recommended to run the following commands from the project root directory.

```bash
conda create --name 262-env python=3.9
conda activate 262-env
pip install -r requirements-dev.txt
pip install -e .
```

### Starting the Cluster

Start the cluster using the provided `start_cluster.py` script. For example, to start a 3-node cluster, run:

```bash
python start_cluster.py --servers 3
```

Make sure you are in the project root directory (the directory that contains the `system_main` folder) when you run this command.

### Running the Client

In a separate terminal, you can start the fault-tolerant client using the `ft_client_grpc.py` script. For example:

```bash
python ft_client_grpc.py --servers 127.0.0.1:50051,127.0.0.1:50052,127.0.0.1:50053
```

The client provides a simple GUI allowing users access to all the functionality of the auction system. 

## Testing

We have included unit tests for our system in the tests directory. Please run the following command from the project root directory to run the tests.

```bash
pytest --cov=system_main --cov-report=term-missing -q
```

## Engineering Notebook

For more detail, please refer to our [Engineering Notebook](https://docs.google.com/document/d/1fi81EBqNnZ-MLOsu6i4XVBm_860L6RcDv8utSS7vPKw/edit?usp=sharing).

---

Thanks for reading, and if you encounter any issues, please refer to the engineering notebook for further context.
