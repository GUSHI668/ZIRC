import sys
import time
import threading
from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN, API_DAILY_RESET_MAP
)

CONFIG = {
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "BASE_URL": SERVERS["M4A1"],
    "PROXY_PORT": 8080
}

current_worker_thread = None
worker_mode = None
proxy_instance = None
stop_macro_flag = False

def on_traffic(event_type: str, url: str, data: dict):
    if event_type == "SYS_KEY_UPGRADE":
        CONFIG["USER_UID"] = data.get("uid")
        CONFIG["SIGN_KEY"] = data.get("sign")
        print(f"\n[+] SUCCESS! Keys Auto-Configured:")
        print(f"    UID  : {CONFIG['USER_UID']}")
        print(f"    SIGN : {CONFIG['SIGN_KEY']}")
        print("\n[!] CRITICAL: Please wait for the game to fully load into the Commander Screen!")
        print("[!] Then type '-g' to auto-reset GreyZone.")

def check_step_error(resp: dict, step_name: str) -> bool:
    if "error_local" in resp:
        print(f"[-] {step_name} Local Error: {resp['error_local']}")
        return True
    if "error" in resp:
        print(f"[-] {step_name} Server Error: {resp['error']}")
        return True
    return False

def check_greyzone_conditions(resp: dict) -> bool:
    status = resp.get("daily_status_with_user_info", {})
    # Priority 1: Check if respawn(initial) spot_id is 138(RightUpper)
    if str(status.get("spot_id")) != "138":
        return False
        
    map_list = resp.get("daily_map_with_user_info", [])
    # Convert list to dict for faster spot lookup
    spots = {str(spot.get("spot_id")): spot.get("mission", "") for spot in map_list}
    
    # Priority 2: Check spot 136(Right Mountain) mission prefix
    mission_136 = spots.get("136", "")
    if not mission_136.startswith("1:521018,2:"):
        return False
        
    # Priority 3: Check spot 127(Vehicle) exact mission match
    mission_127 = spots.get("127", "")
    valid_127_missions = ["1:550501,2:550005", "1:550001,2:550505"]
    if mission_127 not in valid_127_missions:
        return False
        
    return True

def greyzone_reset_worker():
    global stop_macro_flag, worker_mode, current_worker_thread
    
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] SIGN_KEY is default. Run Capture (-c) first!")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    print("=== GFL GreyZone Auto-Reset Started ===")
    
    attempts = 0
    while not stop_macro_flag:
        attempts += 1
        print(f"[*] Attempt {attempts}: Requesting Map Reset...")
        
        resp = client.send_request(API_DAILY_RESET_MAP, {"difficulty": 4})
        if check_step_error(resp, "resetMap"):
            time.sleep(3)
            continue
            
        if check_greyzone_conditions(resp):
            print(f"\n[+] SUCCESS! Desired GreyZone map generated after {attempts} attempts!")
            break
            
        time.sleep(0.1)
        
    print("\n[*] GreyZone reset worker ended.")
    worker_mode, current_worker_thread = None, None

def print_menu():
    print("\n================= MENU =================")
    print(" -c : Start Capture Proxy")
    print(" -g : Run GreyZone Auto-Reset")
    print(" -q : Stop safely")
    print(" -E : Exit program")
    print("========================================\n")

def shutdown_proxy_if_running():
    global proxy_instance
    if worker_mode == 'c' and proxy_instance:
        print("[*] Stopping Proxy to begin worker...")
        proxy_instance.stop()
        set_windows_proxy(False)
        proxy_instance = None
        time.sleep(1)

if __name__ == '__main__':
    print_menu()
    while True:
        try:
            cmd = input("GFL-GREYZONE> ").strip()
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
                
            elif cmd_prefix == '-g':
                shutdown_proxy_if_running()
                stop_macro_flag = False
                worker_mode = 'g'
                current_worker_thread = threading.Thread(target=greyzone_reset_worker)
                current_worker_thread.daemon = True
                current_worker_thread.start()
                
            elif cmd_prefix == '-q':
                stop_macro_flag = True
                print("[*] Will stop loop...")
                
            elif cmd_prefix == '-E':
                if proxy_instance: proxy_instance.stop()
                set_windows_proxy(False)
                stop_macro_flag = True
                print("[*] Exited cleanly. Windows proxy restored.")
                sys.exit(0)
                
        except KeyboardInterrupt:
            print("\n[!] Use '-E' to exit safely!")