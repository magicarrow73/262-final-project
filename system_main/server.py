import socket
import threading
import json

from .db import (
    init_db, create_user, get_user_by_username, delete_user,
    create_message, list_users, get_messages_for_user, 
    mark_message_read, delete_message, get_num_unread_messages 
)
from .utils import hash_password, verify_password

# Server class to handle incoming connections
class Server:
    
    def __init__(self, host="127.0.0.1", port = 12345, protocol_type = "json"):
        '''
        Initialize the server with host and port.
        '''
        self.host = host
        self.port = port
        self.protocol_type = protocol_type
        # server socket
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # dictionary of {`client_socket, `username`}
        self.active_users = {}
        
        # reverse (for easy search): dictionary of {`username`: `client_socket`}
        self.socket_per_username = {}
        
    def start(self):
        '''
        Start the server and listen for incoming connections.
        Accept incoming connections and handle requests continuously.
        '''
        
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
     
    def handle_client(self, client_socket):
        ''' 
        Handle client requests.
        Accept incoming requests and process them.
        '''
        
        # handle the client based on the protocol type
        if self.protocol_type == "json":
            self.handle_json_client(client_socket)
        elif self.protocol_type == "custom":
            # TODO
            pass
        else:
            print("[Server] Invalid protocol type.")
        
        # cleanup after client disconnects (or error)
        if client_socket in self.active_users:
            username = self.active_users[client_socket]
            
            # remove (user, socket) pair
            del self.active_users[client_socket] 
            
            # remove (socket, user) pair
            # this is a check, the `if` statement should always hold
            if username in self.socket_per_username:
                del self.socket_per_username[username]
        
        # close the client socket
        client_socket.close()
         
    def handle_json_client(self, client_socket):
        '''
        Handle JSON client requests.
        Accept incoming requests and process them.
        Sends response back to client.
        '''
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
                
                # get command
                command = request.get("command").lower()
                
                # process command
                if command == "create_user":
                    response = self.create_user_command(request, client_socket)
                elif command == "login":
                    response = self.login_command(request, client_socket)
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
        # the client socket will be closed in the main `handle_client` method
        except Exception as e:
            print(f"[Server] Error: {e}")
               
    ### START OF JSON COMMAND HANDLERS
    '''
    Command handlers for the server take as an argument the JSON request, 
    handle the request, and return a JSON response
    '''
    ### START OF JSON COMMAND HANDLERS
    
    def create_user_command(self, request, client_socket):
        '''
        Create user command handler. Creates user and adds to database; returns response.
        If username already exists, return error message.
        If user is created successfully, return success message.
        '''
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
            
        # add user to active users
        self.active_users[client_socket] = username
        self.socket_per_username[username] = client_socket
        return response
                
    def login_command(self, request, client_socket):
        '''
        Login command handler. 
        Incorrect login attempt should return an error message.
        Successful login command should return a response which contains the number of unread messages.
        '''
        username = request.get("username")
        password = request.get("password")
        
        # get the user from the database
        user = get_user_by_username(username)
        
        # if user does not exist, show error message 'User not found'.
        if not user:
            response = {"status": "error", "message": "User not found."}
            return response
        
        # verify the password
        if not verify_password(password, user["password_hash"]):
            response = {"status": "error", "message": "Incorrect password."}
            return response
        
        # get the number of unread messages
        unread_count = get_num_unread_messages(username)
        response = {"status": "success", "message": "Login successful.", "unread_count": unread_count}
        # add user to active users
        self.active_users[client_socket] = username
        self.socket_per_username[username] = client_socket
        # return response
        return response
                 
    # command to list users
    def list_users_command(self, request):
        '''
        List users command handler. 
        Sends a list of users matching the given pattern; if no pattern is given, return all users.
        Returns response.
        '''
        pattern = request.get("pattern", "*")
        users = list_users(pattern)
        
        # format the users into a list of dictionaries
        users_list = [{"username": u[0], "display_name": u[1]} for u in users]
        
        # return response to send back to client
        response = {"status": "success", "users": users_list}
        return response
        
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
    
    ### end of JSON command handlers 
    ### end of server class          
       
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