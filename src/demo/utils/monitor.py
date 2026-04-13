import sys
import time
import os
import json
from gflzirc import GFLProxy, set_windows_proxy, STATIC_KEY

CONFIG = {
    "PROXY_PORT": 8080,
    "OUTPUT_DIR": "traffic_dumps"
}

proxy_instance = None
packet_counter = 1

def save_json(content_obj, tag, url=""):
    global packet_counter
    
    if not os.path.exists(CONFIG["OUTPUT_DIR"]):
        os.makedirs(CONFIG["OUTPUT_DIR"])
        
    timestamp = int(time.time())
    
    endpoint = "unknown"
    if url and "index.php" in url:
        parts = url.split("index.php")
        if len(parts) > 1 and parts[1]:
            endpoint = parts[1].strip('/').replace('/', '_')
            
    filename = f"{packet_counter:04d}_{tag}_{endpoint}_{timestamp}.json"
    filepath = os.path.join(CONFIG["OUTPUT_DIR"], filename)
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(content_obj, f, indent=4, ensure_ascii=False)
        print(f"[+] Saved: {filename}")
        packet_counter += 1
    except Exception as e:
        print(f"[!] Error saving file: {e}")

def parse_payload(payload):
    """
    Robust payload parser to prevent json.dump crashes.
    Always returns a dictionary.
    """
    if isinstance(payload, dict):
        return payload
        
    elif isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return {"raw_string": payload}
            
    elif isinstance(payload, bytes):
        try:
            return json.loads(payload.decode('utf-8'))
        except Exception:
            return {"raw_hex": payload.hex()}
            
    else:
        return {"raw_type": str(type(payload))}

def on_traffic(event_type: str, url: str, data):
    # Ensure event_type is upper case for matching
    event_upper = str(event_type).upper()
    
    if event_upper == "SYS_KEY_UPGRADE":
        print(f"\n[!] SYSTEM UPGRADE: Sniffed dynamic user keys.")
        if isinstance(data, dict):
            print(f"    New UID  : {data.get('uid')}")
            print(f"    New SIGN : {data.get('sign')}")
        print("[*] Proxy crypto key has been updated automatically.\n")
        
    elif event_upper == "C2S":
        print(f"\n[--> C2S] Captured Request: {url}")
        json_obj = parse_payload(data)
        save_json(json_obj, "C2S", url)
        
    elif event_upper == "S2C":
        print(f"[<-- S2C] Decrypted Server Response.")
        json_obj = parse_payload(data)
        save_json(json_obj, "S2C", url)
        
    else:
        # [CATCH-ALL] Catch any undocumented events from gflzirc
        # (e.g. RAW_C2S, ERROR, UNPARSED) that failed normal decryption
        print(f"\n[?] UNKNOWN/FALLBACK EVENT ({event_type}): {url}")
        json_obj = parse_payload(data)
        save_json(json_obj, f"UNHANDLED_{event_upper}", url)

def print_menu():
    print("\n================= MENU =================")
    print(" -c : Start Network Monitor (MITM)")
    print(" -q : Stop Network Monitor")
    print(" -E : Exit program")
    print("========================================\n")

if __name__ == '__main__':
    print_menu()
    while True:
        try:
            cmd = input("GFL-MONITOR> ").strip()
            if not cmd: continue
            cmd_prefix = cmd.split()[0]
            
            if cmd_prefix == '-c':
                if proxy_instance:
                    print("[!] Monitor is already running!")
                    continue
                proxy_instance = GFLProxy(CONFIG["PROXY_PORT"], STATIC_KEY, on_traffic)
                proxy_instance.start()
                set_windows_proxy(True, f"127.0.0.1:{CONFIG['PROXY_PORT']}")
                print(f"[*] Network Monitor Started on {CONFIG['PROXY_PORT']}. Windows Proxy SET.")
                print("[*] All decrypted C2S and S2C traffic will be saved to /traffic_dumps/.")
                
            elif cmd_prefix == '-q':
                if proxy_instance:
                    print("[*] Stopping Network Monitor...")
                    proxy_instance.stop()
                    set_windows_proxy(False)
                    proxy_instance = None
                    print("[*] Monitor stopped safely.")
                else:
                    print("[!] Monitor is not running.")
                
            elif cmd_prefix == '-E':
                if proxy_instance: proxy_instance.stop()
                set_windows_proxy(False)
                print("[*] Exited cleanly. Windows proxy restored.")
                sys.exit(0)
                
            else:
                print(f"[!] Unknown command: {cmd_prefix}")
                print_menu()
                
        except KeyboardInterrupt:
            print("\n[!] Use '-E' to exit safely!")