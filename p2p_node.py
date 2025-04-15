import socket
import threading
import sys
import time
import sqlite3
from datetime import datetime

##################################################
#                   DATABASE
##################################################

def create_local_database(db_name='mychat.db'):
    """Create local SQLite database for storing messages."""
    conn = sqlite3.connect(db_name, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT,                -- 'sent' or 'received'
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            sent_to_network INTEGER DEFAULT 0
            -- "sent_to_network=1" means it was physically delivered (for 'sent'),
            -- or physically received (for 'received').
        )
    ''')
    conn.commit()
    return conn

def store_message(db_conn, direction, content, sent_to_network=0):
    """Store a single message (sent or received) into the local DB."""
    cursor = db_conn.cursor()
    cursor.execute(
        "INSERT INTO messages (direction, content, sent_to_network) VALUES (?, ?, ?)",
        (direction, content, sent_to_network)
    )
    db_conn.commit()

def mark_message_as_delivered(db_conn, message_id):
    """Mark the given message (by ID) as physically delivered over the network."""
    cursor = db_conn.cursor()
    cursor.execute("UPDATE messages SET sent_to_network=1 WHERE id=?", (message_id,))
    db_conn.commit()

def get_unsent_messages(db_conn):
    """
    Fetch all 'sent' messages that have not yet been delivered over the network
    (sent_to_network=0). Order by time ascending so older messages go first.
    """
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT id, content
        FROM messages
        WHERE direction='sent' AND sent_to_network=0
        ORDER BY id ASC
    """)
    return cursor.fetchall()

##################################################
#                   FILE-BASED PEER DISCOVERY
##################################################

def load_peers(filepath='peers.txt'):
    """
    Read lines from a file like:
        127.0.0.1:5001
        127.0.0.1:5002
        etc.
    Returns a list of (ip, port) tuples.
    """
    peers = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if ':' not in line:
                continue
            ip_str, port_str = line.split(':', 1)
            try:
                port = int(port_str)
                peers.append((ip_str, port))
            except ValueError:
                pass
    return peers

##################################################
#               MESSAGE HANDLERS
##################################################

def handle_incoming_messages(peer_socket, db_conn, on_disconnect_callback):
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

            # Mark 'received' + sent_to_network=1 since it arrived from the network
            store_message(db_conn, 'received', message, sent_to_network=1)

        except ConnectionResetError:
            print("[*] Connection lost.")
            break
        except OSError:
            # Socket probably closed
            break

    # Once we exit the loop, the connection is gone
    on_disconnect_callback()

def send_unsent_messages(peer_socket, db_conn):
    """
    Send any unsent messages that the local peer typed while offline.
    Mark them as delivered once successfully sent.
    """
    unsent = get_unsent_messages(db_conn)
    for msg_id, content in unsent:
        try:
            peer_socket.sendall(content.encode('utf-8'))
            mark_message_as_delivered(db_conn, msg_id)
            print(f"[Offline->Sent] {content}")
            # tiny sleep to avoid spamming the remote side
            time.sleep(0.05)
        except:
            # If sending fails mid-way, break so we can retry later when reconnected
            break

##################################################
#               SERVER + CLIENT
##################################################

def start_server(my_port, db_conn, connection_ready_event, peer_socket_box, on_disconnect_callback):
    """
    Start a server socket listening on my_port.
    Accept a connection, store the socket in peer_socket_box[0],
    set connection_ready_event, spawn a thread to handle messages.
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('', my_port))
    server_socket.listen(5)

    print(f"[*] Listening as a server on port {my_port}...")

    while True:
        # If we already have a connection, no need to accept more for a single peer
        if connection_ready_event.is_set():
            time.sleep(1)
            continue
        try:
            server_socket.settimeout(3)
            conn, addr = server_socket.accept()
            print(f"[*] Accepted connection from {addr}")

            peer_socket_box[0] = conn
            connection_ready_event.set()

            # Spawn a thread to read incoming messages
            t = threading.Thread(
                target=handle_incoming_messages,
                args=(conn, db_conn, on_disconnect_callback),
                daemon=True
            )
            t.start()
        except socket.timeout:
            pass
        except Exception as e:
            print(f"[!] Server exception: {e}")

def start_client(peer_ip, peer_port, db_conn, connection_ready_event, peer_socket_box, on_disconnect_callback):
    """
    Attempt to connect to the peer's server. If successful, store the socket,
    set connection_ready_event, and spawn a thread for incoming messages.
    """
    while not connection_ready_event.is_set():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((peer_ip, peer_port))
            print(f"[*] Connected to peer at {peer_ip}:{peer_port}")

            peer_socket_box[0] = s
            connection_ready_event.set()

            # Spawn a thread to read incoming messages
            t = threading.Thread(
                target=handle_incoming_messages,
                args=(s, db_conn, on_disconnect_callback),
                daemon=True
            )
            t.start()

            return  # stop trying once connected
        except (ConnectionRefusedError, socket.timeout):
            time.sleep(2)
        except Exception as e:
            print(f"[!] Client exception: {e}")
            time.sleep(2)

##################################################
#                      MAIN
##################################################

def main():
    """
    Usage:
        python p2p_node.py <my_port>

    Example:
        # Terminal / Node A (listening on 5001)
        python p2p_node.py 5001

        # Terminal / Node B (listening on 5002)
        python p2p_node.py 5002

    You also need a peers.txt file with lines like:
        127.0.0.1:5001
        127.0.0.1:5002
    """
    if len(sys.argv) != 2:
        print("Usage: python p2p_node.py <my_port>")
        sys.exit(1)

    my_port = int(sys.argv[1])

    # Load known peers from a file
    peers = load_peers('peers.txt')
    # Filter out ourselves
    peers_to_connect = [(ip, port) for (ip, port) in peers if port != my_port]

    # Setup local DB
    db_conn = create_local_database()

    # A container for the single peer socket we use
    peer_socket_box = [None]

    # Event to signal "we have a live connection"
    connection_ready_event = threading.Event()

    # Called whenever we lose our connection
    def on_disconnect():
        connection_ready_event.clear()
        peer_socket_box[0] = None
        print("[!] Disconnected. Will attempt to reconnect...")

    # Start the server in a background thread
    server_thread = threading.Thread(
        target=start_server,
        args=(my_port, db_conn, connection_ready_event, peer_socket_box, on_disconnect),
        daemon=True
    )
    server_thread.start()

    # To prevent double-connections, only connect to peers with ports higher than ours
    for (peer_ip, peer_port) in peers_to_connect:
        if my_port < peer_port:
            client_thread = threading.Thread(
                target=start_client,
                args=(peer_ip, peer_port, db_conn, connection_ready_event, peer_socket_box, on_disconnect),
                daemon=True
            )
            client_thread.start()

    print("\n[*] Attempting to establish peer-to-peer connection(s)...")
    print("[*] Type your messages below. Type 'exit' to quit.\n")

    while True:
        try:
            # Main thread waits for user input
            msg = input("")
            if msg.lower() == "exit":
                print("[*] Exiting.")
                if peer_socket_box[0]:
                    peer_socket_box[0].close()
                sys.exit(0)

            # Store the typed message in DB (offline queue)
            store_message(db_conn, 'sent', msg, sent_to_network=0)

            # If connected, attempt immediate send
            if connection_ready_event.is_set() and peer_socket_box[0] is not None:
                sock = peer_socket_box[0]
                try:
                    sock.sendall(msg.encode('utf-8'))
                    # Mark the last inserted message as delivered
                    unsent = get_unsent_messages(db_conn)
                    if unsent:
                        last_id, _ = unsent[-1]
                        mark_message_as_delivered(db_conn, last_id)
                except:
                    # If send fails, message remains unsent in DB
                    pass

        except (KeyboardInterrupt, EOFError):
            print("\n[*] Exiting chat.")
            if peer_socket_box[0]:
                peer_socket_box[0].close()
            sys.exit(0)

        # Periodically flush older unsent messages if we have a connection
        if connection_ready_event.is_set() and peer_socket_box[0] is not None:
            send_unsent_messages(peer_socket_box[0], db_conn)

if __name__ == "__main__":
    main()
