#!/usr/bin/env python3
# server.py
# Accepts client connections, coordinates proxy selection and client-list tests.

import socket, threading, json, time, traceback, sys

HOST = '0.0.0.0'
PORT = 9090

lock = threading.Lock()
clients = {}        # client_id -> {conn, addr, peer_addr, name}
available_ids = []  # freed IDs to reuse (sorted)
next_id = 1         # next brand-new ID if no reusable ones exist

running = True      # for clean shutdown flag


def send_json(conn, obj):
    data = json.dumps(obj).encode('utf-8') + b'\n'
    try:
        conn.sendall(data)
    except Exception:
        pass


def recv_lines(conn):
    buf = b""
    while True:
        try:
            data = conn.recv(4096)
            if not data:
                break
            buf += data
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                yield line.decode('utf-8')
        except Exception:
            break


def broadcast_chat(sender_id, text, name):
    with lock:
        for cid, info in list(clients.items()):
            try:
                send_json(info['conn'], {
                    'type': 'CHAT',
                    'from_id': sender_id,
                    'from_name': name,
                    'text': text
                })
            except Exception:
                pass


# ----------------------------------------
# Clean removal with ID reuse
# ----------------------------------------
def remove_client(client_id):
    if client_id is None:
        return
    with lock:
        if client_id in clients:
            del clients[client_id]
            available_ids.append(client_id)
            available_ids.sort()
            print(f"[server] Client {client_id} disconnected. Total: {len(clients)}")


def allocate_id():
    global next_id
    with lock:
        if available_ids:
            return available_ids.pop(0)
        cid = next_id
        next_id += 1
        return cid


def handle_client(conn, addr):
    global clients
    my_id = None
    peer_addr = None
    name = None

    try:
        for line in recv_lines(conn):
            try:
                msg = json.loads(line)
            except Exception:
                continue

            if msg.get('type') == 'REGISTER':
                # ID allocation
                my_id = allocate_id()

                with lock:
                    peer_addr = (msg.get('peer_ip', addr[0]), int(msg.get('peer_port')))
                    name = msg.get('name') or f"Client{my_id}"

                    clients[my_id] = {
                        'conn': conn,
                        'addr': addr,
                        'peer_addr': peer_addr,
                        'name': name
                    }

                send_json(conn, {'type': 'ASSIGN_ID', 'id': my_id})
                print(f"[server] Registered client {my_id} {addr} peer {peer_addr} name {name}")

                # Special rules
                with lock:
                    total = len(clients)

                    # Client 2 uses client 1 as proxy
                    if my_id == 2 and total <= 2:
                        if 1 in clients:
                            proxy_info = clients[1]['peer_addr']
                            send_json(conn, {
                                'type': 'USE_PROXY',
                                'proxy_id': 1,
                                'proxy_peer': proxy_info
                            })
                            send_json(clients[1]['conn'], {
                                'type': 'PROXY_FOR',
                                'client_id': 2
                            })

                    # Clients >= 3 get client list
                    if my_id >= 3:
                        lst = []
                        for cid in sorted(clients.keys()):
                            if cid < my_id:
                                lst.append({
                                    'id': cid,
                                    'peer': clients[cid]['peer_addr'],
                                    'name': clients[cid]['name']
                                })
                        send_json(conn, {'type': 'CLIENT_LIST', 'clients': lst})

            elif msg.get('type') == 'CHAT':
                text = msg.get('text', '')
                name = msg.get('name', name)
                print(f"[server] CHAT from {my_id} ({name}): {text}")
                broadcast_chat(my_id, text, name)

            elif msg.get('type') == 'CHOICE':
                chosen = msg.get('chosen_id')
                print(f"[server] Client {my_id} chose proxy {chosen}")
                with lock:
                    if chosen in clients:
                        send_json(clients[chosen]['conn'], {
                            'type': 'PROXY_FOR',
                            'client_id': my_id
                        })
                        send_json(conn, {
                            'type': 'USE_PROXY',
                            'proxy_id': chosen,
                            'proxy_peer': clients[chosen]['peer_addr']
                        })

            elif msg.get('type') == 'FORWARDED_CHAT':
                orig_id = msg.get('orig_id')
                text = msg.get('text', '')
                name = msg.get('name')
                print(f"[server] FORWARDED_CHAT on behalf {orig_id} ({name}): {text}")
                broadcast_chat(orig_id, text, name)

            elif msg.get('type') == 'MEASURE_REQUEST':
                send_json(conn, {'type': 'MEASURE_REPLY', 'ts': time.time()})

            elif msg.get('type') == 'PING':
                send_json(conn, {'type': 'PONG', 'ts': time.time()})

    except Exception as e:
        print("[server] client handler error:", e)
        traceback.print_exc()

    finally:
        remove_client(my_id)
        try:
            conn.close()
        except:
            pass


# ----------------------------------------
# Keybind thread (press ENTER to stop server)
# ----------------------------------------
def key_listener():
    global running
    sys.stdin.readline()
    print("[server] Shutdown requested.")
    running = False


def main():
    global running

    # Start key listener
    threading.Thread(target=key_listener, daemon=True).start()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(100)
    print(f"[server] Listening on {HOST}:{PORT}  (press ENTER to stop)")

    s.settimeout(0.5)

    try:
        while running:
            try:
                c, a = s.accept()
                threading.Thread(target=handle_client, args=(c, a), daemon=True).start()
            except socket.timeout:
                pass

    finally:
        print("[server] Closing sockets...")
        with lock:
            for cid, info in list(clients.items()):
                try:
                    info['conn'].close()
                except:
                    pass
        s.close()
        print("[server] Shutdown complete.")


if __name__ == '__main__':
    main()
