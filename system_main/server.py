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
    
    # initialize server
    def __init__(self, host="127.0.0.1", port = 12345):
        self.host = host
        self.port = port
        
        # server socket
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
    # start server
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
    
    ### START OF JSON COMMAND HANDLERS
    
    # command handlers for the server take as an argument the JSON request, 
    # handle the request, and return a JSON response

    # command to create a new user
    def create_user_command(self, request):
        
            username = request.get("username")
            password = request.get("password")
            display_name = request.get("display_name")
            
            # hash the password
            hashed_pw = hash_password(password)
            
            # create the user
            success = create_user(username, hashed_pw, display_name)
            
            # send response back to client
            if success:
                response = {"status": "success", "message": "User created successfully."}
            else:
                response = {"status": "error", "message": "Username already taken."}
            return response
                
    # command to login a user
    def login_command(self, request):
        # TODO
        pass
        
    # command to list users
    def list_users_command(self, request):
        # TODO
        pass
        
    # command to send a message
    def send_message_command(self, request):
        # TODO
        pass
    # command to read messages
    def read_messages_command(self, request):
        # TODO
        pass
    # command to delete messages
    def delete_messages_command(self, request):
        # TODO
        pass
    # command to delete a user
    def delete_user_command(self, request):
        username = request.get("username")
        success = delete_user(username)
        if success:
            response = {"status": "success", "message": "User deleted successfully."}
        else:
            response = {"status": "error", "message": "User not found."}
        return response
                
    ### end of command handlers           
    
    
    # handle client requests   
    def handle_client(self, client_socket):
        # handle client requests
        try:
            while True:
                # receive data from the client
                data = client_socket.recv(4096)
                if not data:
                    break
                
                # decode + parse the data as JSON
                try: 
                    request = json.loads(data.decode('utf-8'))
                except: 
                    print("[Server] Invalid JSON received.")
                    break
                # log the request
                print(f"[Server] Received request: {request}")
                
                # process the request
                
                command = request.get("command").lower()
                
                if command == "create_user":
                    response = self.create_user_command(request)
                elif command == "login":
                    response = self.login_command(request)
                elif command == "list_users":
                    response = self.list_users_command(request)
                elif command == "send_message":
                    response = self.send_message_command(request)
                elif command == "read_messages":
                    response = self.read_messages_command(request)
                elif command == "delete_messages":
                    response = self.delete_messages_command(request)
                elif command == "delete_user":
                    response = self.delete_user_command(request)
                else:
                    response = {"status": "error", "message": "Unknown command."}
                # send response back to client
                client_socket.send(json.dumps(response).encode('utf-8'))
    
        # handle any errors, for now just print the error
        except Exception as e:
            print(f"[Server] Error: {e}")
        # close the client socket if error
        finally:
            client_socket.close()       
              


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