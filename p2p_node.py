import socket
import threading
import sys
import time
import sqlite3

def create_local_database(db_name='mychat.db'):
    """Create local SQLite database for storing messages."""
    conn = sqlite3.connect(db_name, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    return conn

def store_message(db_conn, direction, content):
    """Store a single message (sent or received) into the local DB."""
    cursor = db_conn.cursor()
    cursor.execute(
        "INSERT INTO messages (direction, content) VALUES (?, ?)",
        (direction, content)
    )
    db_conn.commit()

def handle_incoming_messages(peer_socket, db_conn):
    """
    Continuously listen for incoming messages on peer_socket and
    print them to the console. Also store each incoming message in DB.
    """
    while True:
        try:
            data = peer_socket.recv(1024)
            if not data:
                print("[*] Connection closed by peer.")
                break
            message = data.decode('utf-8')
            print(f"[Received] {message}")
            store_message(db_conn, 'received', message)
        except ConnectionResetError:
            print("[*] Connection lost.")
            break
        except OSError:
            # Socket probably closed
            break

def start_server(my_port, db_conn, connection_ready_event, peer_socket_box):
    """
    Start a server socket that listens on my_port.
    If a client connects, store the socket in peer_socket_box[0],
    set the connection_ready_event, and start a listener thread.
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('', my_port))
    server_socket.listen(1)

    print(f"[*] Listening as a server on port {my_port}...")

    # accept a single connection
    try:
        conn, addr = server_socket.accept()
        print(f"[*] Accepted connection from {addr}")

        # store the connection so main thread can use it
        peer_socket_box[0] = conn
        connection_ready_event.set()

        # start a thread to handle incoming messages from this connection
        t = threading.Thread(target=handle_incoming_messages, args=(conn, db_conn), daemon=True)
        t.start()
    except Exception as e:
        print(f"[!] Server exception: {e}")
    finally:
        server_socket.close()

def start_client(peer_ip, peer_port, db_conn, connection_ready_event, peer_socket_box):
    """
    Attempt to connect to the peer's server repeatedly until successful
    or until the connection_ready_event is set by the server side.
    """
    while not connection_ready_event.is_set():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((peer_ip, peer_port))
            print(f"[*] Connected to peer at {peer_ip}:{peer_port}")

            # store this socket so main thread can use it
            peer_socket_box[0] = s
            connection_ready_event.set()

            # start a thread to handle incoming messages from this connection
            t = threading.Thread(target=handle_incoming_messages, args=(s, db_conn), daemon=True)
            t.start()
            return  # Exit after successful connection
        except ConnectionRefusedError:
            # peer not up yet or not listening on that port
            time.sleep(2)
        except Exception as e:
            print(f"[!] Client exception: {e}")
            time.sleep(2)

def main():
    """
    Usage:
        python p2p_node.py <my_port> <peer_ip> <peer_port>

    Example:
        # Terminal 1
        python p2p_node.py 5001 127.0.0.1 5002

        # Terminal 2
        python p2p_node.py 5002 127.0.0.1 5001
    """
    if len(sys.argv) != 4:
        print("Usage: python p2p_node.py <my_port> <peer_ip> <peer_port>")
        sys.exit(1)

    my_port = int(sys.argv[1])
    peer_ip = sys.argv[2]
    peer_port = int(sys.argv[3])

    # setup local DB
    db_conn = create_local_database()

    # a thread-safe way to share the peer socket once established
    peer_socket_box = [None]  # We'll store the socket in index 0

    # an event that signals a connection is established (either server or client side)
    connection_ready_event = threading.Event()

    # start the server in a background thread
    server_thread = threading.Thread(
        target=start_server,
        args=(my_port, db_conn, connection_ready_event, peer_socket_box),
        daemon=True
    )
    server_thread.start()

    # start the client logic (which tries to connect to the peer)
    client_thread = threading.Thread(
        target=start_client,
        args=(peer_ip, peer_port, db_conn, connection_ready_event, peer_socket_box),
        daemon=True
    )
    client_thread.start()

    print("\n[*] Attempting to establish peer-to-peer connection...")
    print("[*] Type your messages below. Type 'exit' to quit.\n")

    # wait until we have a connected socket or we decide to quit
    while not connection_ready_event.is_set():
        # just wait for either server accept or client connect
        time.sleep(1)

    peer_socket = peer_socket_box[0]
    if not peer_socket:
        print("[!] Could not establish connection. Exiting.")
        sys.exit(1)

    # now we can send messages in a loop
    while True:
        try:
            msg = input("")
            if msg.lower() == "exit":
                print("[*] Closing connection and exiting.")
                peer_socket.close()
                sys.exit(0)

            # Send the message to the peer
            peer_socket.sendall(msg.encode('utf-8'))
            store_message(db_conn, 'sent', msg)

        except (KeyboardInterrupt, EOFError):
            print("\n[*] Exiting chat.")
            peer_socket.close()
            sys.exit(0)
        except BrokenPipeError:
            print("[!] The peer connection was lost.")
            sys.exit(1)

if __name__ == "__main__":
    main()
