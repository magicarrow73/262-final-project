import socket
import threading
import json

from .db import (
    init_db, close_db, create_user, get_user_by_username, delete_user,
    create_message, list_users, get_messages_for_user, 
    mark_message_read, delete_message, get_num_unread_messages 
)
from .utils import hash_password, verify_password

class Server:
    def __init__(self, host="127.0.0.1", port = 12345, protocol_type = "json"):
        """
        Initialize server with host and port.
        protocol_type: is either "json" or "custom". If "json", use JSON protocol, if "custom", use custom wire protocol.
        """
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
        """
        Start server, bind, listen, and accept incoming connections
        """
        #initialize db tables
        init_db()
        #bind server to host and port
        self.server.bind((self.host, self.port))
        self.server.listen(5)
        print(f"Server started on {self.host}:{self.port} (protocol={self.protocol_type})")
        
        # accept incoming connections
        try:
            while True:
                client_socket, addr = self.server.accept()
                print(f"[Server] Connection from {addr} has been established.")
                client_handler = threading.Thread(target=self.handle_client, args=(client_socket,))
                client_handler.start()
            
        except KeyboardInterrupt:
            print("[Server] Shutting down the server rip gg...")
        finally:
            #close db and server socket
            close_db()
            self.server.close()  
     
    def handle_client(self, client_socket):
        """
        Dispatch to current protocol handler
        After the protocol handler finishes, remove user from active_users
        """
        # handle the client based on the protocol type
        if self.protocol_type == "json":
            self.handle_json_client(client_socket)
        elif self.protocol_type == "custom":
            self.handle_custom_client(client_socket)
        else:
            print("[Server] Invalid protocol type, please specify a new one.")
        
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
        """
        Handle JSON client requests
        That is, read JSON object from socket, dispatch based on command, send back JSON response
        """
        try:
            while True:
                # receive data from the client
                data = client_socket.recv(4096)
                if not data:
                    break
                
                # decode + parse the data as JSON
                try: 
                    request = json.loads(data.decode('utf-8'))
                except json.JSONDecodeError: 
                    print("[Server] Invalid JSON received, please double check the format.")
                    break
                
                # log the request
                print(f"[Server] Received request: {request}")
                
                # get command
                unprocessed_command = request.get("command", "")
                command = unprocessed_command.lower() if isinstance(unprocessed_command, str) else "" #make sure command is a string to avoid attribute error
                
                # process command
                if command == "create_user":
                    response = self.create_user_command(request, client_socket)
                elif command == "login":
                    response = self.login_command(request, client_socket)
                elif command == "logout":
                    response = self.logout_command(request, client_socket)
                elif command == "list_users":
                    response = self.list_users_command(request)
                elif command == "send_message":
                    response = self.send_message_command(request, client_socket)
                elif command == "read_messages":
                    response = self.read_messages_command(request, client_socket)
                elif command == "delete_messages":
                    response = self.delete_messages_command(request, client_socket)
                elif command == "delete_user":
                    response = self.delete_user_command(request)
                else:
                    response = {"status": "error", "message": "Unknown command."}
                # send response back to client
                client_socket.send((json.dumps(response) + "\n").encode('utf-8'))

    
        # handle any errors, for now just print the error
        # the client socket will be closed in the main `handle_client` method
        except Exception as e:
            print(f"[Server] Error handling client: {e}")
    
    def handle_custom_client(self, client_socket):
        """
        Handle custom wire protocol client requests
        """
        # TODO
        pass   
            

    # ===== JSON Command Handlers =====
    """
    Command handlers for the server take as an argument the JSON request, handle the request, and return a JSON response
    """

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
            #do not automatically log in user
            #self.active_users[client_socket] = username
            #self.socket_per_username[username] = client_socket
            response = {"status": "success", "message": "User created successfully."}
        else:
            response = {"status": "error", "message": "Username already taken."}
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
        
        # add user to active users
        self.active_users[client_socket] = username
        self.socket_per_username[username] = client_socket
        
        # get the number of unread messages
        unread_count = get_num_unread_messages(username)
        response = {"status": "success", "message": "Login successful.", "unread_count": unread_count}

        # return response
        return response
    
    def logout_command(self, request, client_socket):
        """
        Logout command handler
        Removes current user from active_users so they are not logged in anymore
        """
        username = self.active_users.get(client_socket)
        if not username:
            return {"status": "error", "message": "No user is currently logged in on this connection"}
        del self.active_users[client_socket]
        if username in self.socket_per_username:
            del self.socket_per_username[username]
        return {"status": "success", "message": f"User {username} is now logged out, thanks for playing"}
                 
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
        response = {"status": "success", "users": users_list, "pattern": pattern}
        return response
        
    # command to send a message
    def send_message_command(self, request, client_socket):
        """
        Send a message from currently logged in user to specified receiver
        Request expects "command"="send_message", "receiver"=..., "content"=...
        """
        sender = self.active_users.get(client_socket)
        if not sender:
            return {"status": "error", "message": "You are not logged in."}
        
        receiver = request.get("receiver")
        content = request.get("content", "")
        if not receiver:
            return {"status": "error", "message": "No receiver specified."}
        
        success = create_message(sender, receiver, content)
        if success:
            return {"status": "success", "message": "Message sent."}
        else:
            return {"status": "error", "message": "Could not send message (user not found?)."}
        
    # command to read messages
    def read_messages_command(self, request, client_socket):
        """
        Get messages for currently logged in user
        Optional "only_unread" acts as a filter
        Optional "mark_read" can mark all returned messages as read
        """
        username = self.active_users.get(client_socket)
        if not username:
            return {"status": "error", "message": "You are not logged in."}
        
        only_unread = bool(request.get("only_unread", False))
        mark_as_read = bool(request.get("mark_read", False))
        
        messages = get_messages_for_user(username, only_unread=only_unread)
        
        #mark each returned message as read
        if mark_as_read:
            for msg in messages:
                mark_message_read(msg["id"], username)
        
        #convert messages to JSON serializable format
        output = []
        for m in messages:
            output.append({
                "id": m["id"],
                "sender_id": m["sender_id"],
                "receiver_id": m["receiver_id"],
                "content": m["content"],
                "timestamp": m["timestamp"],
                "read_status": m["read_status"],
                "sender_username": m["sender_username"]
            })
        
        return {"status": "success", "messages": output}

    # command to delete messages
    def delete_messages_command(self, request, client_socket):
        """
        Delete one or more messages for logged in user
        Expects "message_id" as an int or "message_ids" as a list
        """
        username = self.active_users.get(client_socket)
        if not username:
            return {"status": "error", "message": "You are not logged in, please try again"}
        
        #allow for either single message_id or list of message_ids
        message_id = request.get("message_id")
        message_ids = request.get("message_ids", [])
        deleted_count = 0
        
        if message_id:
            try:
                message_id = int(message_id)
            except ValueError:
                return {"status": "error", "message": "Message ID must be a number, please try again"}

            if delete_message(message_id, username):
                deleted_count += 1
        
        if isinstance(message_ids, list):
            for mid in message_ids:
                if delete_message(mid, username):
                    deleted_count += 1
        
        if deleted_count > 0:
            return {"status": "success", "deleted_count": deleted_count}
        else:
            return {"status": "error", "message": "No messages deleted."}

    # command to delete a user
    def delete_user_command(self, request):
        """
        Delete a specified user from the database and cascade delete their messages
        """
        username = request.get("username")
        success = delete_user(username)
        if success:
            response = {"status": "success", "message": "User deleted successfully."}
        else:
            response = {"status": "error", "message": "User not found."}
        return response

# ===== Main Function =====
       
def main():
    
    import argparse
    
    # parse command line arguments
    parser = argparse.ArgumentParser(description="Start the server.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=12345, help="Port to bind to")
    parser.add_argument("--protocol", type=str, default="json", help="Protocol: either json or custom wire protocol")
    args = parser.parse_args()
    
    # start the server
    server = Server(host=args.host, port=args.port, protocol_type=args.protocol)
    server.start()


if __name__ == "__main__":
    main()
