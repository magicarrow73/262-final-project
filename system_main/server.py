import socket
import threading
import json

from .db import (
    init_db, close_db, create_user, get_user_by_username, delete_user,
    create_message, list_users, get_messages_for_user, 
    mark_message_read, delete_message, get_num_unread_messages 
)
from .utils import verify_password

CMD_CREATE = 0x01
CMD_LOGIN  = 0x02
CMD_LOGOUT = 0x03
CMD_SEND   = 0x04
CMD_LIST   = 0x05
CMD_READ   = 0x06
CMD_DELMSG = 0x07
CMD_DELUSR = 0x08

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

         # A lock to protect active_users and socket_by_username
         # Prevents race conditions from multiple threads accessing and/or edit these dictionaries
        self.lock = threading.Lock()

        
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
                client_handler = threading.Thread(target=self.handle_client, args=(client_socket,), daemon=True)
                client_handler.start()
            
        except KeyboardInterrupt:
            print("[Server] Shutting down the server rip gg...")
        finally:
            # close db and server socket
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
            print("[Server] Invalid protocol type, please specify a correct one.")
        
        # Cleanup when client disconnects
        with self.lock:
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

    # ===== JSON protocol handler =====
         
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
                    response = self.delete_user_command(client_socket)
                else:
                    response = {"status": "error", "message": "Unknown command."}
                # send response back to client
                client_socket.send((json.dumps(response) + "\n").encode('utf-8'))

    
        # handle any errors, for now just print the error
        # the client socket will be closed in the main `handle_client` method
        except Exception as e:
            print(f"[Server] JSON error handling client: {e}")

    # ===== custom wire protocol handler =====
    
    def handle_custom_client(self, client_socket):
        """
        Expect frames of [CMD(1)][LEN(2)][PAYLOAD] that we parse and then call parse_binary_command
        """
        try:
            while True:
                header = self.recv_n_bytes(client_socket, 3)
                if not header:
                    break
                cmd = header[0]
                length = int.from_bytes(header[1:3], 'big')

                payload = b""
                if length>0:
                    payload = self.recv_n_bytes(client_socket, length)
                    if not payload:
                        break

                resp = self.parse_binary_command(cmd, payload, client_socket)
                if resp:
                    resp += b"\n"
                    client_socket.sendall(resp)

        except Exception as e:
            print(f"[Server] custom wire error: {e}")
        finally:
            with self.lock:
                if client_socket in self.active_users:
                    username = self.active_users[client_socket]
                    del self.active_users[client_socket]
                    if username in self.socket_per_username:
                        del self.socket_per_username[username]
            client_socket.close()

    def recv_n_bytes(self, sock, n):
        """
        Helper to read exactly n bytes or return None if disconnected
        """
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf
    
    def parse_custom_command(self, cmd, payload, client_socket):
        """
        Dispatch based on cmd and return a bytes object like b"OK something" or b"ERR something"
        """

        if cmd == CMD_CREATE:
            parts = payload.split(b"\0")
            if len(parts)<3:
                return b"ERR Not enough fields for create user"
            user = parts[0].decode("utf-8","replace")
            pw   = parts[1].decode("utf-8","replace")
            disp = parts[2].decode("utf-8","replace")

            fake_req = {"username": user, "hashed_password": pw, "display_name": disp}
            r = self.create_user_command(fake_req, client_socket)
            if r["status"] == "success":
                return f"OK {r['message']}".encode("utf-8")
            elif r["status"] == "user_exists":
                return f"ERR {r['message']}".encode("utf-8")
            else:
                return f"ERR {r.get('message','Unknown error')}".encode("utf-8")

        elif cmd == CMD_LOGIN:
            parts = payload.split(b"\0")
            if len(parts)<2:
                return b"ERR Not enough fields for login"
            user = parts[0].decode("utf-8","replace")
            pw   = parts[1].decode("utf-8","replace")

            fake_req = {"username":user,"hashed_password":pw}
            r = self.login_command(fake_req, client_socket)
            if r["status"] == "success":
                unread = r.get("unread_count",0)
                return f"OK Logged in. Unread={unread}".encode("utf-8")
            else:
                return f"ERR {r.get('message','Login error')}".encode("utf-8")

        elif cmd == CMD_LOGOUT:
            r = self.logout_command({}, client_socket)
            if r["status"]=="success":
                return f"OK {r['message']}".encode("utf-8")
            else:
                return f"ERR {r['message']}".encode("utf-8")

        elif cmd == CMD_SEND:
            parts = payload.split(b"\0")
            if len(parts)<2:
                return b"ERR Not enough fields for send"
            receiver = parts[0].decode("utf-8","replace")
            content  = parts[1].decode("utf-8","replace")

            fake_req = {"receiver":receiver,"content":content}
            r = self.send_message_command(fake_req, client_socket)
            if r["status"]=="success":
                return b"OK Message sent."
            else:
                return f"ERR {r['message']}".encode("utf-8")

        elif cmd == CMD_LIST:
            pattern = payload.split(b"\0")[0].decode("utf-8","replace") if payload else "*"
            fake_req = {"pattern":pattern}
            r = self.list_users_command(fake_req)
            if r["status"]=="success":
                users = r["users"]
                lines = [f"OK Found {len(users)} user(s)."]
                for u in users:
                    lines.append(f"USR {u['username']} {u['display_name']}")
                return ("\n".join(lines)).encode("utf-8")
            else:
                return f"ERR {r.get('message','Error listing')} ".encode("utf-8")

        elif cmd == CMD_READ:
            if len(payload)<3:
                only_unread=False
                limit=None
            else:
                only_unread = (payload[0] == 1)
                limit = int.from_bytes(payload[1:3],'big')

            fake_req = {"only_unread":only_unread}
            if limit and limit>0:
                fake_req["limit"] = limit
            r = self.read_messages_command(fake_req, client_socket)
            if r["status"]=="success":
                msgs = r["messages"]
                if not msgs:
                    return b"OK No messages."
                lines = []
                for m in msgs:
                    lines.append(f"MSG {m['id']} from={m['sender_username']} content={m['content']}")
                return ("\n".join(lines)).encode("utf-8")
            else:
                return f"ERR {r['message']}".encode("utf-8")

        elif cmd == CMD_DELMSG:
            # e.g. "12" or "12,13"
            raw = payload.decode("utf-8","replace").strip()
            if not raw:
                return b"ERR No message ID(s)"

            if "," in raw:
                parts = [p.strip() for p in raw.split(",") if p.strip()]
                try:
                    ids = [int(x) for x in parts]
                    fake_req = {"message_ids": ids}
                except ValueError:
                    return b"ERR Invalid ID(s)"
            else:
                try:
                    single_id = int(raw)
                    fake_req = {"message_id": single_id}
                except ValueError:
                    return b"ERR Invalid ID"

            r = self.delete_messages_command(fake_req, client_socket)
            if r["status"]=="success":
                dcount = r.get("deleted_count",0)
                return f"OK Deleted {dcount} messages.".encode("utf-8")
            else:
                return f"ERR {r['message']}".encode("utf-8")

        elif cmd == CMD_DELUSR:
            r = self.delete_user_command(client_socket)
            if isinstance(r, dict):
                if r["status"]=="success":
                    return f"OK {r['message']}".encode("utf-8")
                else:
                    return f"ERR {r.get('message','Error')}".encode("utf-8")
            else:
                return f"ERR {r}".encode("utf-8")

        else:
            return b"ERR Unknown command"
            

    # ===== JSON Command Handlers =====
    """
    Command handlers for the server take as an argument the JSON request, handle the request, and return a JSON response
    """

    def create_user_command(self, request, client_socket):
        '''
        Create user command handler. Creates user and adds to database; returns response.
        If username already exists, return user_exists so client can prompt for login.
        If user is created successfully, return success message.
        '''
        username = request.get("username")
        hashed_password = request.get("hashed_password")
        display_name = request.get("display_name")

        existing_user = get_user_by_username(username)
        if existing_user is not None:
            return {
                "status": "user_exists",
                "message": f"User '{username}' already exists. Please try to log in instead.",
                "username": username
            }

        # create the user
        success = create_user(username, hashed_password, display_name)
        # send response back to client
        if success:
            #do not automatically log in user
            #self.active_users[client_socket] = username
            #self.socket_per_username[username] = client_socket
            response = {"status": "success", "message": "User created successfully."}
        else:
            response = {"status": "error", "message": "Could not create user because of unknown error."}
        return response
                
    def login_command(self, request, client_socket):
        '''
        Login command handler. 
        Incorrect login attempt should return an error message.
        Successful login command should return a response which contains the number of unread messages.
        '''
        username = request.get("username")
        hashed_password = request.get("hashed_password")
        
        # get the user from the database
        user = get_user_by_username(username)
        
        # if user does not exist, show error message 'User not found'.
        if not user:
            response = {"status": "error", "message": "User not found."}
            return response
        
        # verify the password
        if not verify_password(hashed_password, user["password_hash"]):
            response = {"status": "error", "message": "Incorrect password."}
            return response
        
        # add user to active users
        with self.lock:
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
        if not success:
            return {"status": "error", "message": "Could not send message (user not found?)."}
        
        with self.lock:
            if receiver in self.socket_per_username:
                rec_socket = self.socket_per_username[receiver]
                if self.protocol_type == "json":
                    push_obj = {
                        'status': 'push',
                        'push_type': 'incoming_message',
                        'sender': sender,
                        'content': content
                    }
                    try:
                        rec_socket.send((json.dumps(push_obj) + "\n").encode('utf-8'))
                    except Exception as e:
                        print(f"[Server] Failed to push live message to {receiver}: {e}")
                else:
                    push_line = f"P {sender} {content}"
                    try:
                        rec_socket.send((push_line + "\n").encode('utf-8'))
                    except Exception as e:
                        print(f"[Server] Failed to push custom message to {receiver}: {e}")

        return {"status": "success", "message": "Message sent."}
        
    # command to read messages
    def read_messages_command(self, request, client_socket):
        """
        Get messages for currently logged in user.
        - only_unread: bool
        - limit: integer limit
        Return them in descending timestamp order.
        """
        with self.lock:
            username = self.active_users.get(client_socket)
            if not username:
                return {"status": "error", "message": "You are not logged in."}
            
        only_unread = bool(request.get("only_unread", False))
        limit = request.get("limit", None)
        if limit is not None:
            try:
                limit = int(limit)
            except ValueError:
                limit = None
        
        messages = get_messages_for_user(username, only_unread=only_unread, limit=limit)

        mark_as_read = True # TODO: can be an option [in the future version of the app, potentially]. 
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
        with self.lock:
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
    def delete_user_command(self, client_socket):
        """
        Delete your user from the database and cascade delete their messages
        Note that only the user who is logged in can delete themselves, therwise arbitrary deletions may occur.
        """
        with self.lock:
            if client_socket not in self.active_users:
                return "Users not logged in are not allowed to delete other users."
            username = self.active_users[client_socket]
        success = delete_user(username)
        if success:
            response = {"status": "success", "message": f"Your user {username} deleted successfully."}
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
    parser.add_argument("--protocol", type=str, default="json", help="Protocol: either 'json' or 'custom' wire protocol")
    args = parser.parse_args()
    
    # start the server
    server = Server(host=args.host, port=args.port, protocol_type=args.protocol)
    server.start()


if __name__ == "__main__":
    main()


### historical code
### saved in case needs to be referenced in the future 

# # command to delete a user
# PREVIOUS VERSION OF COMMANDS: any user can delete any other user 
# THIS PREVIOUS VERSION is kept for reference, but is obsolete.
# def delete_user_command(self, request, client_socket):
#     """
#     Delete a specified user from the database and cascade delete their messages
#     """
#     with self.lock:
#         if client_socket not in self.active_users:
#             return "Users not logged in are not allowed to delete other users."
#         username = request.get("username")
#     success = delete_user(username)
#     if success:
#         response = {"status": "success", "message": "User deleted successfully."}
#     else:
#         response = {"status": "error", "message": "User not found."}
#     return response
