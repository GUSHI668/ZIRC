import sys
import time
import threading
from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy, 
    SERVERS, STATIC_KEY, DEFAULT_SIGN, API_TARGET_TRAIN_ADD
)

CONFIG = {
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "TARGET_ENEMIES": [6519263, 6519225, 6519223, 6519246, 6519206],
    "TARGET_ORDERS": [1, 2, 3, 4, 5],
    "BASE_URL": SERVERS["M4A1"],
    "PROXY_PORT": 8080
}

current_worker_thread = None
worker_mode = None
proxy_instance = None
stop_flag = False

def on_traffic(event_type: str, url: str, data: dict):
    if event_type == "SYS_KEY_UPGRADE":
        CONFIG["USER_UID"] = data.get("uid")
        CONFIG["SIGN_KEY"] = data.get("sign")
        print(f"\n[+] SUCCESS! Keys Auto-Configured:")
        print(f"    UID  : {CONFIG['USER_UID']}")
        print(f"    SIGN : {CONFIG['SIGN_KEY']}")
        print("\n[!] CRITICAL: Please wait for the game to fully load into the Commander Screen!")
        print("[!] Then type '-r' to automatically stop proxy and begin injection.")

def add_target_practice_enemy(client: GFLClient, enemy_id: int, order_id: int):
    payload = {
        "enemy_team_id": enemy_id,
        "fight_type": 0,
        "fight_coef": "",
        "fight_environment_group": "",
        "order_id": order_id
    }
    
    print(f"[*] Sending Request - Enemy ID: {enemy_id} | Order ID: {order_id} ...", end=" ")
    response = client.send_request(API_TARGET_TRAIN_ADD, payload)
    
    if response and (response.get("success") or "1" in str(response.get("raw", ""))):
        print("[ SUCCESS ]")
    else:
        print(f"[ FAIL ] Server returned: {response}")

def baji_worker():
    global stop_flag, worker_mode, current_worker_thread
    
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] SIGN_KEY is default. Run Capture (-c) first!")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    
    target_enemies = CONFIG["TARGET_ENEMIES"]
    target_orders = CONFIG["TARGET_ORDERS"]
    use_custom_orders = (len(target_enemies) == len(target_orders))
    
    if use_custom_orders:
        print("[*] Order list length matches. Using custom order IDs.")
    else:
        print("[!] Order list length mismatch. Using auto-increment sequence.")

    print("\n=== GFL Target Practice Injection Started ===")
    
    for idx, enemy in enumerate(target_enemies):
        if stop_flag:
            print("[*] Injection interrupted by user.")
            break
            
        current_order = target_orders[idx] if use_custom_orders else (idx + 1)
        add_target_practice_enemy(client, enemy, current_order)
        
        if idx < len(target_enemies) - 1:
            time.sleep(1)
            
    print("\n[*] Injection runs ended.")
    worker_mode, current_worker_thread = None, None

def print_menu():
    print("\n================= MENU =================")
    print(" -c : Start Capture Proxy")
    print(" -r : Run Target Practice Injection")
    print(" -q : Stop safely")
    print(" -E : Exit program")
    print("========================================\n")

if __name__ == '__main__':
    print_menu()
    while True:
        try:
            cmd = input("GFL-BAJI> ").strip()
            if not cmd: continue
            cmd_prefix = cmd.split()[0]
            
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
                    print("[*] Stopping Proxy to begin injection...")
                    proxy_instance.stop()
                    set_windows_proxy(False)
                    proxy_instance = None
                    time.sleep(1)
                
                stop_flag = False
                worker_mode = 'r'
                current_worker_thread = threading.Thread(target=baji_worker)
                current_worker_thread.daemon = True
                current_worker_thread.start()
                
            elif cmd_prefix == '-q':
                stop_flag = True
                print("[*] Will stop injection safely...")
                
            elif cmd_prefix == '-E':
                if proxy_instance: proxy_instance.stop()
                set_windows_proxy(False)
                stop_flag = True
                print("[*] Exited cleanly. Windows proxy restored.")
                sys.exit(0)
                
            else:
                print(f"[!] Unknown command: {cmd_prefix}")
                print_menu()
                
        except KeyboardInterrupt:
            print("\n[!] Use '-E' to exit safely!")