# src/demo/utils/recover_gun.py

# Note: 
# This script cannot "create" a T-Doll out of 'void'; 
# it still adheres to the basic requirement: a T-Doll that has been unlocked with a quantity of 0 in the repository.
# 
# Therefore, its possible function is to poll from 1 to 400+ T-Dolls' IDs 
# to recover a T-Doll that no longer exists in your repository, instead of manual ID filtering.

import sys
import time
from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN
)

# Define API locally if not present in constants.py
API_GUN_RECOVER = "Gun/coreRecoverGun"

CONFIG = {
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "BASE_URL": SERVERS["RO635"],
    "PROXY_PORT": 8080
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
        print("[!] Then type '-r <gun_id>' to stop proxy and recover a T-Doll.")

def recover_gun_worker(gun_id: int):
    global worker_mode
    
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] SIGN_KEY is default. Run Capture (-c) first!")
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    
    print(f"\n[*] Sending Request - Recovering Gun ID: {gun_id} ...")
    payload = {
        "gun_id": gun_id
    }
    
    response = client.send_request(API_GUN_RECOVER, payload)
    
    # 1. Handle library-level local errors (decryption failed, plaintext error code, etc.)
    if isinstance(response, dict) and "error_local" in response:
        print(f"[-] Local Error: {response['error_local']}")
        # Print the raw text returned by the server (e.g. "0", "-1", HTML errors)
        print(f"    Raw Response: '{response.get('raw', 'N/A')}'")
        return
        
    # 2. Handle server-level logical errors format {"error": "message"}
    if isinstance(response, dict) and "error" in response:
        print(f"[-] Server Error: {response['error']}")
        return
        
    # 3. Handle successful recovery
    if isinstance(response, dict):
        uid_result = response.get("gun_with_user_id")
        if uid_result:
            print(f"[+] SUCCESS! Recovered T-Doll ID: {gun_id}")
            print(f"    -> New Gun UID: {uid_result}")
            return
            
    # 4. Handle Empty or Unexpected parsed JSON (like {}, [], or missing expected keys)
    print(f"[!] Request finished, but response lacks target data.")
    print(f"    It could be rejected due to game limits (e.g., weekly limit).")
    print(f"    Parsed JSON/Result: {response}")

def print_menu():
    print("\n================= MENU =================")
    print(" -c         : Start Capture Proxy")
    print(" -r <id>    : Recover T-Doll by Gun ID (e.g. -r 316)")
    print(" -E         : Exit program")
    print("========================================\n")

if __name__ == '__main__':
    print_menu()
    while True:
        try:
            cmd = input("GFL-RECOVER> ").strip()
            if not cmd: continue
            
            cmd_parts = cmd.split()
            cmd_prefix = cmd_parts[0]
            
            if cmd_prefix == '-c':
                if proxy_instance:
                    print("[!] Proxy is already running!")
                    continue
                proxy_instance = GFLProxy(CONFIG["PROXY_PORT"], STATIC_KEY, on_traffic)
                proxy_instance.start()
                set_windows_proxy(True, f"127.0.0.1:{CONFIG['PROXY_PORT']}")
                worker_mode = 'c'
                print(f"[*] Capture Proxy Started on {CONFIG['PROXY_PORT']}. Windows Proxy SET.")
                
            elif cmd_prefix == '-r':
                if worker_mode == 'c' and proxy_instance:
                    print("[*] Stopping Proxy before sending request...")
                    proxy_instance.stop()
                    set_windows_proxy(False)
                    proxy_instance = None
                    time.sleep(1)
                
                if len(cmd_parts) < 2:
                    print("[!] Missing parameter. Usage: -r <gun_id> (e.g. -r 316)")
                    continue
                    
                try:
                    target_gun_id = int(cmd_parts[1])
                except ValueError:
                    print(f"[!] Invalid gun_id: '{cmd_parts[1]}'. Must be an integer.")
                    continue
                    
                worker_mode = 'r'
                recover_gun_worker(target_gun_id)
                
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