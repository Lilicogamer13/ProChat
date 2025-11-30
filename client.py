#!/usr/bin/env python3
# client.py
# Run: python3 client.py --server-ip 127.0.0.1 --server-port 9090
# Press Enter in the name field to set name; toggle "use local ip" to use machine IP as name.

import socket, threading, json, time, argparse, sys, random
import pygame
from queue import Queue, Empty

# ---------- Networking helpers ----------
def send_json(conn, obj):
    try:
        conn.sendall((json.dumps(obj) + '\n').encode('utf-8'))
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
                line, buf = buf.split(b'\n',1)
                yield line.decode('utf-8')
        except Exception:
            break

# ---------- Peer listener ----------
def start_peer_listener(listen_port, incoming_queue):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', listen_port))
    s.listen(5)
    def loop():
        while True:
            try:
                c,a = s.accept()
                threading.Thread(target=handle_peer_conn, args=(c,a,incoming_queue), daemon=True).start()
            except Exception:
                break
    threading.Thread(target=loop, daemon=True).start()
    return s

def handle_peer_conn(conn, addr, incoming_queue):
    try:
        for line in recv_lines(conn):
            try:
                msg = json.loads(line)
            except:
                continue
            t = msg.get('type')
            if t == 'PING':
                send_json(conn, {'type':'PONG','ts': time.time()})
            elif t == 'FORWARD_TO_SERVER':
                action = msg.get('action')
                if action == 'MEASURE_SERVER':
                    incoming_queue.put(('PEER_MEASURE_REQUEST', msg.get('req_id'), conn))
                elif action == 'FORWARD_CHAT':
                    incoming_queue.put(('PEER_FORWARD_CHAT', msg.get('orig_id'), msg.get('name'), msg.get('text'), conn))
            else:
                incoming_queue.put(('PEER_MSG', msg, conn))
    except Exception:
        pass
    finally:
        try: conn.close()
        except: pass

# ---------- Client core ----------
class Client:
    def __init__(self, server_ip, server_port, peer_listen_port, name, use_local_ip):
        self.server_ip = server_ip
        self.server_port = server_port
        self.peer_listen_port = peer_listen_port
        self.name = name
        self.use_local_ip = use_local_ip
        self.server_conn = None
        self.id = None
        self.peer_addr = None
        self.incoming_peer_queue = Queue()
        self.chat_queue = Queue()
        self.stop = False
        self.proxy_targets = set()
        self.peer_sock = start_peer_listener(self.peer_listen_port, self.incoming_peer_queue)

        threading.Thread(target=self.server_loop, daemon=True).start()
        threading.Thread(target=self.peer_incoming_processor, daemon=True).start()

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return socket.gethostbyname(socket.gethostname())

    def server_loop(self):
        while not self.stop:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((self.server_ip, self.server_port))
                self.server_conn = s
                my_ip = self.get_local_ip()
                send_json(s, {'type':'REGISTER', 'peer_ip': my_ip, 'peer_port': self.peer_listen_port, 'name': self.name})
                for line in recv_lines(s):
                    try:
                        msg = json.loads(line)
                    except:
                        continue
                    self.handle_server_msg(msg)
            except Exception:
                time.sleep(1)
            finally:
                try:
                    if self.server_conn:
                        self.server_conn.close()
                except:
                    pass
                self.server_conn = None
                time.sleep(1)

    def peer_incoming_processor(self):
        while True:
            try:
                item = self.incoming_peer_queue.get()
                if item[0] == 'PEER_MEASURE_REQUEST':
                    req_id, conn = item[1], item[2]
                    if not self.server_conn:
                        send_json(conn, {'type':'FORWARD_REPLY', 'req_id': req_id, 'error': 'no_server_conn'})
                    else:
                        try:
                            tstart = time.time()
                            send_json(self.server_conn, {'type':'PING'})
                            self.server_conn.settimeout(2.0)
                            try:
                                data = b''
                                while b'\n' not in data:
                                    data += self.server_conn.recv(4096)
                            except Exception:
                                pass
                            self.server_conn.settimeout(None)
                            tend = time.time()
                            rtt = (tend - tstart) * 1000.0
                            send_json(conn, {'type':'FORWARD_REPLY', 'req_id': req_id, 'server_rtt_ms': rtt})
                        except Exception as e:
                            send_json(conn, {'type':'FORWARD_REPLY', 'req_id': req_id, 'error': str(e)})

                elif item[0] == 'PEER_FORWARD_CHAT':
                    orig_id, nm, txt, conn = item[1], item[2], item[3], item[4]
                    if not self.server_conn:
                        send_json(conn, {'type':'FORWARD_CHAT_RESULT', 'ok': False, 'error':'no_server_conn'})
                    else:
                        send_json(self.server_conn, {'type':'FORWARDED_CHAT', 'orig_id': orig_id, 'name': nm, 'text': txt})
                        send_json(conn, {'type':'FORWARD_CHAT_RESULT', 'ok': True})
                else:
                    self.chat_queue.put(item)
            except Exception:
                pass

    def handle_server_msg(self, msg):
        t = msg.get('type')
        if t == 'ASSIGN_ID':
            self.id = msg.get('id')
        elif t == 'USE_PROXY':
            proxy_id = msg.get('proxy_id')
            proxy_peer = msg.get('proxy_peer')
            self.current_proxy = {'id': proxy_id, 'peer': tuple(proxy_peer)}
        elif t == 'PROXY_FOR':
            self.proxy_targets.add(msg.get('client_id'))
        elif t == 'CLIENT_LIST':
            cl = msg.get('clients', [])
            threading.Thread(target=self.perform_latency_selection, args=(cl,), daemon=True).start()
        elif t == 'CHAT':
            self.chat_queue.put(('CHAT', msg.get('from_name'), msg.get('text')))
        elif t in ('MEASURE_REPLY','PONG'):
            pass

    def perform_latency_selection(self, client_list):
        results = []
        for entry in client_list:
            cid = entry['id']; ip, port = entry['peer']
            rtt = self.ping_peer(ip, port)
            if rtt is None:
                rtt = float('inf')
            results.append({'id':cid, 'peer':(ip,port), 'rtt': rtt, 'name':entry.get('name')})
        results.sort(key=lambda x: x['rtt'])
        best = results[0]['rtt']
        candidates = [r for r in results if abs(r['rtt'] - best) < 1e-6]

        if len(candidates) == 1:
            chosen = candidates[0]['id']
        else:
            server_rtts = []
            for c in candidates:
                ip,port = c['peer']
                req_id = f"m{random.randint(1,10**9)}"
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(2.0)
                    s.connect((ip,port))
                    send_json(s, {'type':'FORWARD_TO_SERVER','action':'MEASURE_SERVER','req_id':req_id})
                    data = b''
                    s.settimeout(3.0)
                    while b'\n' not in data:
                        chunk = s.recv(4096)
                        if not chunk: break
                        data += chunk
                    if data:
                        resp = json.loads(data.decode().split('\n',1)[0])
                        server_rtt = resp.get('server_rtt_ms', float('inf'))
                    else:
                        server_rtt = float('inf')
                    s.close()
                except Exception:
                    server_rtt = float('inf')
                server_rtts.append({'id': c['id'], 'peer': c['peer'], 'server_rtt': server_rtt, 'local_rtt': c['rtt']})

            server_rtts.sort(key=lambda x: x['server_rtt'])
            best2 = server_rtts[0]['server_rtt']
            candidates2 = [r for r in server_rtts if abs(r['server_rtt'] - best2) < 1e-6]

            if len(candidates2) == 1:
                chosen = candidates2[0]['id']
            else:
                chain_results = []
                for c in candidates2:
                    ip,port = c['peer']
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(3.0)
                        s.connect((ip,port))
                        req_id = f"chain{random.randint(1,10**9)}"
                        t0 = time.time()
                        send_json(s, {'type':'FORWARD_TO_SERVER','action':'MEASURE_SERVER','req_id':req_id})
                        data = b''
                        while b'\n' not in data:
                            data += s.recv(4096)
                        t1 = time.time()
                        resp = json.loads(data.decode().split('\n',1)[0])
                        server_total = (t1 - t0) * 1000.0
                    except Exception:
                        server_total = float('inf')
                    chain_results.append({'id': c['id'], 'total': server_total})

                chain_results.sort(key=lambda x: x['total'])
                best3 = chain_results[0]['total']
                bests = [r for r in chain_results if abs(r['total'] - best3) < 1e-6]
                chosen = bests[0]['id'] if len(bests) == 1 else random.choice(bests)['id']

        send_json(self.server_conn, {'type':'CHOICE', 'chosen_id': chosen})
        for e in client_list:
            if e['id'] == chosen:
                self.current_proxy = {'id': chosen, 'peer': tuple(e['peer']), 'name': e.get('name')}
                break

    def ping_peer(self, ip, port, timeout=1.0):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((ip,port))
            t0 = time.time()
            send_json(s, {'type':'PING'})
            data = b''
            while b'\n' not in data:
                data += s.recv(4096)
            t1 = time.time()
            s.close()
            return (t1 - t0) * 1000.0
        except Exception:
            return None

    def send_chat(self, text):
        nm = self.name if not self.use_local_ip else self.get_local_ip()
        cp = getattr(self, 'current_proxy', None)
        if cp:
            try:
                ip,port = cp['peer']
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect((ip,port))
                send_json(s, {'type':'FORWARD_TO_SERVER', 'action':'FORWARD_CHAT', 'orig_id': self.id, 'name': nm, 'text': text})
                data = b''
                while b'\n' not in data:
                    data += s.recv(4096)
                s.close()
                return
            except Exception:
                pass
        if self.server_conn:
            send_json(self.server_conn, {'type':'CHAT', 'text': text, 'name': nm})

# ---------- Pygame GUI ----------
pygame.init()

# *** FIXED FONT HERE ***
clean_font = pygame.font.match_font("dejavusans") or pygame.font.get_default_font()
FONT = pygame.font.Font(clean_font, 20)

class UI:
    def __init__(self, client: Client):
        self.client = client
        self.width = 700; self.height = 500
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("P2P Chat Client")
        self.input_box = pygame.Rect(10, self.height-40, 480, 30)
        self.send_btn = pygame.Rect(500, self.height-40, 80, 30)
        self.name_box = pygame.Rect(590, self.height-40, 100, 30)
        self.use_ip_box = pygame.Rect(590, self.height-80, 14, 14)
        self.use_ip = client.use_local_ip
        self.name_text = client.name
        self.msg_text = ''
        self.chat_lines = []
        self.clock = pygame.time.Clock()

    def add_chat(self, who, text):
        time_tag = time.strftime('%H:%M:%S')
        self.chat_lines.append(f"[{time_tag}] {who}: {text}")
        if len(self.chat_lines) > 100:
            self.chat_lines.pop(0)

    def run(self):
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); sys.exit(0)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        if self.msg_text.strip():
                            self.client.send_chat(self.msg_text.strip())
                            self.msg_text = ''
                    elif event.key == pygame.K_BACKSPACE:
                        self.msg_text = self.msg_text[:-1]
                    else:
                        if event.unicode:
                            self.msg_text += event.unicode
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    mx,my = event.pos
                    if self.send_btn.collidepoint(mx,my):
                        if self.msg_text.strip():
                            self.client.send_chat(self.msg_text.strip())
                            self.msg_text = ''
                    if self.use_ip_box.collidepoint(mx,my):
                        self.use_ip = not self.use_ip
                        self.client.use_local_ip = self.use_ip
                    if self.name_box.collidepoint(mx,my):
                        newname = self.prompt_text("Set name (Enter):", default=self.name_text)
                        if newname:
                            self.name_text = newname
                            self.client.name = newname

            try:
                while True:
                    item = self.client.chat_queue.get_nowait()
                    if isinstance(item, tuple) and item[0] == 'CHAT':
                        _, who, text = item
                        self.add_chat(who, text)
                    else:
                        if isinstance(item, tuple) and item[0] == 'PEER_MSG':
                            self.add_chat('PEER', str(item[1]))
            except Empty:
                pass

            self.screen.fill((30,30,30))

            y = 10
            for line in self.chat_lines[-18:]:
                surf = FONT.render(line, True, (240,240,240))
                self.screen.blit(surf, (10,y))
                y += 22

            pygame.draw.rect(self.screen, (50,50,50), self.input_box)
            txt_surf = FONT.render(self.msg_text, True, (240,240,240))
            self.screen.blit(txt_surf, (self.input_box.x+4, self.input_box.y+6))

            pygame.draw.rect(self.screen, (70,120,70), self.send_btn)
            self.screen.blit(FONT.render("Send", True, (255,255,255)), (self.send_btn.x+18, self.send_btn.y+6))

            pygame.draw.rect(self.screen, (50,50,60), self.name_box)
            self.screen.blit(FONT.render(self.name_text, True, (230,230,230)), (self.name_box.x+4, self.name_box.y+6))

            pygame.draw.rect(self.screen, (50,50,50), (self.use_ip_box.x, self.use_ip_box.y, 14, 14))
            if self.use_ip:
                pygame.draw.line(self.screen, (200,200,200), (self.use_ip_box.x, self.use_ip_box.y), (self.use_ip_box.x+14, self.use_ip_box.y+14), 2)
                pygame.draw.line(self.screen, (200,200,200), (self.use_ip_box.x+14, self.use_ip_box.y), (self.use_ip_box.x, self.use_ip_box.y+14), 2)
            self.screen.blit(FONT.render("Use local IP", True, (220,220,220)), (self.use_ip_box.x+20, self.use_ip_box.y-3))

            pygame.display.flip()
            self.clock.tick(30)

    def prompt_text(self, prompt, default=''):
        return input(f"{prompt} ") or default

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server-ip', default='127.0.0.1')
    parser.add_argument('--server-port', type=int, default=9090)
    parser.add_argument('--peer-port', type=int, default=10000 + random.randint(0,5000))
    parser.add_argument('--name', default='Anon')
    parser.add_argument('--use-local-ip', action='store_true')
    args = parser.parse_args()

    client = Client(args.server_ip, args.server_port, args.peer_port, args.name, args.use_local_ip)
    ui = UI(client)
    ui.run()

if __name__ == '__main__':
    main()
