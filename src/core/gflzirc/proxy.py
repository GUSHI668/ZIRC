import socket
import select
import re
import json
import threading
import winreg
import ctypes
import urllib.parse
from .crypto import gf_authcode

INTERNET_OPTION_REFRESH = 37
INTERNET_OPTION_SETTINGS_CHANGED = 39

def refresh_windows_proxy():
    try:
        internet_set_option = ctypes.windll.wininet.InternetSetOptionW
        internet_set_option(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        internet_set_option(0, INTERNET_OPTION_REFRESH, 0, 0)
    except:
        pass

def set_windows_proxy(enable: bool, proxy_addr="127.0.0.1:8080"):
    try:
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        hKey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_WRITE)
        
        if enable:
            winreg.SetValueEx(hKey, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(hKey, "ProxyServer", 0, winreg.REG_SZ, proxy_addr)
        else:
            winreg.SetValueEx(hKey, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            
        winreg.CloseKey(hKey)
        refresh_windows_proxy()
        return True
    except Exception:
        return False

class GFLCaptureProxy:
    def __init__(self, port: int, static_key: str, on_capture_callback=None):
        self.port = port
        self.static_key = static_key
        self.on_capture_callback = on_capture_callback
        self.stop_event = threading.Event()
        self.server_thread = None

    def _blind_relay_with_sniffer(self, src_sock, dst_sock, is_target_api):
        sockets = [src_sock, dst_sock]
        response_buffer = b""
        keys_captured = False
        
        try:
            while not self.stop_event.is_set():
                readable, _, _ = select.select(sockets, [], [], 1.0)
                if not readable:
                    continue
                for sock in readable:
                    data = sock.recv(8192)
                    if not data:
                        return 
                    if sock is src_sock:
                        dst_sock.sendall(data)
                    else:
                        src_sock.sendall(data)
                        
                        if is_target_api and not keys_captured:
                            response_buffer += data
                            match = re.search(b'#([A-Za-z0-9+/=]+)', response_buffer)
                            if match:
                                encrypted_b64 = match.group(1).decode('ascii')
                                decrypted = gf_authcode(encrypted_b64, 'DECODE', self.static_key)
                                
                                if decrypted:
                                    try:
                                        json_data = json.loads(decrypted)
                                        uid = json_data.get("uid")
                                        sign = json_data.get("sign")
                                        if uid and sign:
                                            keys_captured = True
                                            if self.on_capture_callback:
                                                self.on_capture_callback(str(uid), str(sign))
                                    except Exception:
                                        pass
        except Exception:
            pass

    def _handle_client(self, client_socket):
        target_socket = None
        try:
            request_header = b""
            while b"\r\n\r\n" not in request_header:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                request_header += chunk
                
            if not request_header:
                return
                
            header_str = request_header.split(b"\r\n\r\n")[0].decode('ascii', errors='ignore')
            lines = header_str.split('\r\n')
            if not lines: return
            first_line = lines[0].split()
            if len(first_line) < 3: return
                
            method, url, _ = first_line
            host, port = "", 80
            
            for line in lines[1:]:
                if line.lower().startswith("host:"):
                    host_val = line.split(":", 1)[1].strip()
                    if ":" in host_val:
                        host, p = host_val.split(":", 1)
                        port = int(p)
                    else:
                        host = host_val
                        port = 443 if method == "CONNECT" else 80
                    break
                    
            if not host: return

            target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target_socket.connect((host, port))
            
            if method == "CONNECT":
                client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._blind_relay_with_sniffer(client_socket, target_socket, False)
            else:
                is_target_api = "/Index/getUidPC" in url
                target_socket.sendall(request_header)
                self._blind_relay_with_sniffer(client_socket, target_socket, is_target_api)

        except Exception:
            pass
        finally:
            if client_socket:
                try: client_socket.close()
                except: pass
            if target_socket:
                try: target_socket.close()
                except: pass

    def _server_loop(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("127.0.0.1", self.port))
            server.listen(100)
            server.settimeout(1.0)
            
            while not self.stop_event.is_set():
                try:
                    client_sock, _ = server.accept()
                    t = threading.Thread(target=self._handle_client, args=(client_sock,))
                    t.daemon = True
                    t.start()
                except socket.timeout:
                    continue
        except Exception as e:
            print(f"[!] CaptureProxy Server Error: {e}")
        finally:
            server.close()

    def start(self):
        self.stop_event.clear()
        self.server_thread = threading.Thread(target=self._server_loop)
        self.server_thread.daemon = True
        self.server_thread.start()

    def stop(self):
        self.stop_event.set()
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)

class GFLMonitorProxy:
    """
    Full traffic interceptor for GFL API.
    Decrypts both S2C and C2S payloads and dynamically upgrades the crypto key.
    """
    def __init__(self, port: int, static_key: str, on_traffic_callback=None):
        self.port = port
        self.current_key = static_key
        self.on_traffic_callback = on_traffic_callback
        self.stop_event = threading.Event()
        self.server_thread = None

    def _trigger_callback(self, direction, url, json_obj):
        if self.on_traffic_callback:
            try:
                self.on_traffic_callback(direction, url, json_obj)
            except Exception:
                pass

    def _relay_and_analyze(self, src_sock, dst_sock, is_target_api, request_url):
        sockets = [src_sock, dst_sock]
        req_buffer = b""
        res_buffer = b""
        c2s_parsed = False
        s2c_parsed = False
        
        try:
            while not self.stop_event.is_set():
                readable, _, _ = select.select(sockets, [], [], 1.0)
                if not readable:
                    continue
                for sock in readable:
                    data = sock.recv(8192)
                    if not data:
                        return 
                        
                    if sock is src_sock:
                        dst_sock.sendall(data)
                        if is_target_api and not c2s_parsed:
                            req_buffer += data
                            # Attempt to parse C2S outdatacode
                            try:
                                body_str = req_buffer.split(b'\r\n\r\n', 1)[1].decode('ascii', errors='ignore')
                                parsed_qs = urllib.parse.parse_qs(body_str)
                                if 'outdatacode' in parsed_qs:
                                    encrypted_b64 = parsed_qs['outdatacode'][0]
                                    decrypted = gf_authcode(encrypted_b64, 'DECODE', self.current_key)
                                    if decrypted:
                                        try:
                                            json_data = json.loads(decrypted)
                                            self._trigger_callback("C2S", request_url, json_data)
                                            c2s_parsed = True
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                    else:
                        src_sock.sendall(data)
                        if is_target_api and not s2c_parsed:
                            res_buffer += data
                            # Attempt to parse S2C response starting with #
                            match = re.search(b'#([A-Za-z0-9+/=]+)', res_buffer)
                            if match:
                                encrypted_b64 = match.group(1).decode('ascii')
                                decrypted = gf_authcode(encrypted_b64, 'DECODE', self.current_key)
                                if decrypted:
                                    try:
                                        json_data = json.loads(decrypted)
                                        self._trigger_callback("S2C", request_url, json_data)
                                        s2c_parsed = True
                                        
                                        # Key Upgrade Mechanism
                                        uid = json_data.get("uid")
                                        sign = json_data.get("sign")
                                        if uid and sign and str(sign) != self.current_key:
                                            self.current_key = str(sign)
                                            self._trigger_callback("SYS", "KEY_UPGRADE", {"uid": uid, "sign": sign})
                                    except Exception:
                                        pass
        except Exception:
            pass

    def _handle_client(self, client_socket):
        target_socket = None
        try:
            request_header = b""
            while b"\r\n\r\n" not in request_header:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                request_header += chunk
                
            if not request_header:
                return
                
            header_str = request_header.split(b"\r\n\r\n")[0].decode('ascii', errors='ignore')
            lines = header_str.split('\r\n')
            if not lines: return
            first_line = lines[0].split()
            if len(first_line) < 3: return
                
            method, url, _ = first_line
            host, port = "", 80
            
            for line in lines[1:]:
                if line.lower().startswith("host:"):
                    host_val = line.split(":", 1)[1].strip()
                    if ":" in host_val:
                        host, p = host_val.split(":", 1)
                        port = int(p)
                    else:
                        host = host_val
                        port = 443 if method == "CONNECT" else 80
                    break
                    
            if not host: return

            target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target_socket.connect((host, port))
            
            if method == "CONNECT":
                client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._relay_and_analyze(client_socket, target_socket, False, url)
            else:
                is_target_api = "index.php" in url
                target_socket.sendall(request_header)
                self._relay_and_analyze(client_socket, target_socket, is_target_api, url)

        except Exception:
            pass
        finally:
            if client_socket:
                try: client_socket.close()
                except: pass
            if target_socket:
                try: target_socket.close()
                except: pass

    def _server_loop(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("127.0.0.1", self.port))
            server.listen(100)
            server.settimeout(1.0)
            
            while not self.stop_event.is_set():
                try:
                    client_sock, _ = server.accept()
                    t = threading.Thread(target=self._handle_client, args=(client_sock,))
                    t.daemon = True
                    t.start()
                except socket.timeout:
                    continue
        except Exception as e:
            pass
        finally:
            server.close()

    def start(self):
        self.stop_event.clear()
        self.server_thread = threading.Thread(target=self._server_loop)
        self.server_thread.daemon = True
        self.server_thread.start()

    def stop(self):
        self.stop_event.set()
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)