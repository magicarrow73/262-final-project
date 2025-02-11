import socket
import threading
import json

from .db import (
    init_db, create_user, get_user_by_username, delete_user,
    create_message, list_users, get_messages_for_user, 
    mark_message_read, delete_message, 
)
from .utils import hash_password, verify_password

# Server class to handle incoming connections
class Server:
    def __init__(self, host="127.0.0.1", port = 12345):
        self.host = host
        self.port = port
        
        # server socket
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    def start(self):
        # bind the server to the host and port
        self.server.bind((self.host, self.port))
        self.server.listen(5)
        print(f"Server started on {self.host}:{self.port}")
        
        # accept incoming connections
        try:
            while True:
                client_socket, addr = self.server.accept()
                print(f"[Server] Connection from {addr} has been established.")
                client_handler = threading.Thread(target=self.handle_client, args=(client_socket,))
                client_handler.start()
            
        except KeyboardInterrupt:
            print("Server shutting down...")
            # self.server.close()
        finally:
            self.server.close()    


def main():
    
    import argparse
    
    # parse command line arguments
    parser = argparse.ArgumentParser(description="Start the server.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=12345, help="Port to bind to")
    args = parser.parse_args()
    
    # start the server
    server = Server(host=args.host, port=args.port)
    server.start()
    

if __name__ == "__main__":
    main()