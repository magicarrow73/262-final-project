# 262-wireprotocol: User Guide and Testing Instructions

## Creating chat_pb2.py, chat_pb2_grpc.py

To use the gRPC client/server, first compile the chat.proto file:

``` python -m grpc_tools.protoc \
  --proto_path=. \
  --python_out=. \
  --grpc_python_out=. \
  chat.proto
```
This will create two files, containing the protobuf message structs and service classes.

## Running the Client and Server
### Running the Client
To run the client remotely, use the following command:

```python -m system_main.client --host 192.168.1.10 --port 12345```

where `192.168.1.10` is the IP address of the computer hosting the server.

To run the client locally, use:

```python -m system_main.client --host 127.0.0.1 --port 12345```

### Running the Server
To start the server, run:

```python -m system_main.server --host 127.0.0.1 --port 12345```

## Choosing the Protocol
### Server-Side Protocol Selection
To use JSON protocol:

```python -m system_main.server --host 127.0.0.1 --port 12345 --protocol json```

To use Custom protocol:

```python -m system_main.server --host 127.0.0.1 --port 12345 --protocol custom```

### Client-Side Protocol Selection
To use JSON protocol, add the --json flag:

python -m system_main.client --host 127.0.0.1 --port 12345 --json

To use Custom protocol, simply omit the flag:

python -m system_main.client --host 127.0.0.1 --port 12345

## Running Tests
The test suite is located in the unit_tests/ directory, including:

`tests_db.py`: Tests related to database operations.
`tests_server_client.py`: Tests interactions between the client and server.
To run all unit tests, use the following command:

```python -m unittest discover -s unit_tests```

One needs to make adjustments to a few of the files before running these tests, please refer to our engineering notebook for more details.

## Additional Information
For elaboration on the intricacies of our codebase and test regime, please refer to our engineering notebook since it details these aspects in depth.
