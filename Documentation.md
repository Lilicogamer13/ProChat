# ProChat — Complete Documentation

ProChat is a lightweight, proxy-based chat system built in Python. Instead of routing all messages through the server, clients can be selected to act as proxies for newly connected users. This reduces server load and creates a distributed message-routing structure.

This documentation describes the project’s structure, the behavior of each Python file, and how to use the system in a clear, standard GitHub-style format.

---

# Contents

* Overview
* Architecture
* Repository Structure
* Server (`server.py`)
* Client (`client.py`)
* Proxy Selection Logic
* Protocol Overview
* Running ProChat
* Troubleshooting
* Extending the Project
* License

---

# Overview

ProChat establishes a chat network where:

* The server coordinates clients and decides which client new users should connect through.
* The first two users connect directly to each other.
* Every new user is assigned a proxy client based on latency measurements rather than routing through the server.

This reduces server bandwidth requirements by offloading routing to clients.

---

# Architecture

ProChat uses a hybrid server–peer architecture:

* **Server** accepts client connections and assigns proxy relationships based on latency.
* **Clients** connect to the server, then optionally connect to other clients as instructed. Clients may serve as proxies for others.

The network expands as a chain or tree of client-to-client connections.

---

# Repository Structure

```
ProChat/
│
├── client.py       # Client application
├── server.py       # Server application
├── README.md       # High-level description and proxy algorithm
└── LICENSE         # GNU license
```

---

# Server (`server.py`)

## Purpose

* Accept TCP connections.
* Track active clients and their latency metrics.
* Pair the first two connected clients directly.
* Select the best proxy for each subsequent client.
* Relay routing instructions to clients.

## Key Characteristics

* Runs on **port 9090** by default.
* Port number is **hard-coded**; change it inside `server.py` if needed.
* No command-line arguments.

## Operation

1. Server starts and waits for incoming connections.
2. First client connects; stored but not paired.
3. Second client connects; server pairs both directly.
4. From the third client onward, server:

   * Performs latency tests,
   * Selects the best proxy using the algorithm described below,
   * Sends connection instructions to the new client.

## How to Run

```
python3 server.py
```

Ensure port 9090 is accessible on your network.

---

# Client (`client.py`)

## Purpose

* Connects to the server.
* Sends registration information (user name, listen port).
* Receives proxy assignment and connects to another client when required.
* Acts as a proxy for additional clients when selected by the server.

## Command-Line Usage

```
python3 client.py --server-ip <ip> --server-port <port>
```

Example:

```
python3 client.py --server-ip 127.0.0.1 --server-port 9090
```

## Behavior

* Prompts for a name. Press Enter to accept the default.
* Includes an option to use the machine’s local IP as display name.
* After registration, the server may instruct the client to connect to another client.
* May be assigned to proxy additional clients.

---

# Proxy Selection Logic

The server evaluates all existing clients when choosing a proxy for a new connection.

Selection steps:

1. Choose the client with the **lowest direct latency** to the new client.
2. If tied, choose the client with the **lowest latency to the server**.
3. If still tied, choose the client with the **lowest combined latency** (new ↔ candidate ↔ server).
4. If still tied, select randomly.

This ensures predictable routing and minimal total delay.

---

# Protocol Overview

ProChat uses a simple JSON-over-TCP message format. Message structures vary per implementation, but generally include:

### Registration

```json
{"type": "register", "name": "Example", "listen_port": 50000}
```

### Latency Probes

```json
{"type": "ping"}
{"type": "pong"}
```

### Proxy Assignment

```json
{"type": "assign_proxy", "ip": "1.2.3.4", "port": 50000}
```

### Chat Message

```json
{"type": "chat", "from": "Example", "msg": "Hello"}
```

Fields depend on the exact implementation in the Python files.

---

# Running ProChat

### 1. Start the server

```
python3 server.py
```

### 2. Start the first two clients

```
python3 client.py --server-ip <server-ip> --server-port 9090
```

These two clients are paired directly.

### 3. Start additional clients

Each additional client will automatically receive a proxy assignment from the server.

---

# Troubleshooting

### Client cannot connect

* Ensure the server is running.
* Verify correct IP and port.
* Allow inbound traffic to port 9090.

### Proxy connections fail

* Clients acting as proxies may require reachable ports (LAN or port-forwarded).
* NAT or symmetric NAT may block peer-to-peer connections.

### Server refusing connections

* Check if another application is using port 9090.
* Restart the server to clear stale connections.

---

# Extending the Project

Potential improvements:

* Add configuration file for ports and host settings.
* Add command-line flags to the server for flexibility.
* Improve logging with Python’s logging module.
* Implement NAT traversal techniques.
* Add SSL/TLS support.
* Introduce user authentication.
* Implement chat rooms or broadcast groups.

---

# License

ProChat is licensed under the **GNU License**.
Refer to the `LICENSE` file for the full terms.

---
### written by the same person who said "that a hard path" on a gd comment 1 year ago 😭😭
