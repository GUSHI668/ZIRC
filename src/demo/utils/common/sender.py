# src/demo/utils/sender.py

# Send payload to endpoint

import sys
import time
from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN
)

API_ENDPOINT = "Equip/retire"

CONFIG = {
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "BASE_URL": SERVERS["M4A1"],
    "PROXY_PORT": 8080
}

TARGET_PAYLOAD = {
    "equips": [
        119720565,
    ]
}

proxy_instance = None
worker_mode = None

def on_traffic(event_type: str, url: str, data: dict):
    if event_type == "SYS_KEY_UPGRADE":
        CONFIG["USER_UID"] = data.get("uid")
        CONFIG["SIGN_KEY"] = data.get("sign")
        print(f"\n[+] SUCCESS! Keys Auto-Configured:")
        print(f"    UID  : {CONFIG['USER_UID']}")
        print(f"    SIGN : {CONFIG['SIGN_KEY']}")
        print("\n[!] CRITICAL: Please wait for the game to fully load into the Commander Screen!")
        print("[!] Then type '-s' to stop proxy and send the payload.")

def send_payload_worker():
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] SIGN_KEY is default. Run Capture (-c) first!")
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    
    # Timestamp Replace: ally_id to time()
    # current_timestamp = int(time.time())
    # TARGET_PAYLOAD["ally_id"] = current_timestamp

    print(f"\n[*] Sending Request to {API_ENDPOINT} ...")
    print(f"[*] Payload Info (ally_id dynamically updated): {TARGET_PAYLOAD}")
    
    # Send payload
    response = client.send_request(API_ENDPOINT, TARGET_PAYLOAD)
    
    if isinstance(response, dict) and "error_local" in response:
        print(f"[-] Local Error: {response['error_local']}")
        print(f"    Raw Response: '{response.get('raw', 'N/A')}'")
        return
        
    if isinstance(response, dict) and "error" in response:
        print(f"[-] Server Error: {response['error']}")
        return
        
    print(f"[+] Request finished. Server returned:")
    print(f"    Parsed JSON: {response}")

def print_menu():
    print("\n========================= MENU =========================")
    print(" -c  : Start Capture Proxy")
    print(" -s  : Send Payload")
    print(" -E  : Exit program")
    print("========================================================\n")

if __name__ == '__main__':
    print_menu()
    while True:
        try:
            cmd = input("GFL-SENDER> ").strip()
            if not cmd: continue
            
            if cmd == '-c':
                if proxy_instance:
                    print("[!] Proxy is already running!")
                    continue
                proxy_instance = GFLProxy(CONFIG["PROXY_PORT"], STATIC_KEY, on_traffic)
                proxy_instance.start()
                set_windows_proxy(True, f"127.0.0.1:{CONFIG['PROXY_PORT']}")
                worker_mode = 'c'
                print(f"[*] Capture Proxy Started on {CONFIG['PROXY_PORT']}. Windows Proxy SET.")
                
            elif cmd == '-s':
                if worker_mode == 'c' and proxy_instance:
                    print("[*] Stopping Proxy before sending request...")
                    proxy_instance.stop()
                    set_windows_proxy(False)
                    proxy_instance = None
                    time.sleep(1)
                
                worker_mode = 's'
                send_payload_worker()
                
            elif cmd == '-E':
                if proxy_instance: proxy_instance.stop()
                set_windows_proxy(False)
                print("[*] Exited cleanly. Windows proxy restored.")
                sys.exit(0)
                
            else:
                print(f"[!] Unknown command: {cmd}")
                print_menu()
                
        except KeyboardInterrupt:
            print("\n[!] Use '-E' to exit safely!")