# PyP2PChat – Phase 1

A simple **peer-to-peer** chat system that uses Python’s `socket` and `threading` to enable two nodes to send and receive text messages without a central server. Each node also stores a local SQLite database of messages.

## Key Features

- **Peer-to-Peer:** Both nodes act as **client** and **server** simultaneously, so a single TCP connection is established from either side.  
- **Local Storage:** Messages are logged in a local SQLite database (`mychat.db`) per node; no cloud or remote servers are used.  
- **Async Message Handling:** Uses Python threads to handle receiving messages while the main thread continues reading user input.  
- **Two-Way Chat:** Once connected, each node can send messages to the other in real time via the single TCP connection.

## How It Works

Each node performs two roles:

1. **Server** – Listens on a specified port for an incoming connection.  
2. **Client** – Tries to connect to the peer’s listening port.

Whichever node’s client connects first “wins” the race, but the resulting TCP socket is **full-duplex**, allowing both sides to exchange messages.

## Quick Start
Open **two separate terminals** (or two machines on the same network) and choose two different ports. For example, `5001` and `5002`:

- **Terminal A**:
  ```python p2p_node.py 5001 127.0.0.1 5002```

  - **Terminal B**:
  ```python p2p_node.py 5002 127.0.0.1 5001```

  ## Local Database
  Each node automatically creates and maintains a local **SQLite** database names ```mychat.db```:
  
  ```sql
  CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT,
    content TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
  );
  ```

It logs every **sent** and **received** message with timestamps.