import sys
import time
import json
import threading
from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN,
    API_MISSION_COMBINFO, API_MISSION_START, API_INDEX_GUIDE,
    API_MISSION_TEAM_MOVE, API_MISSION_ABORT, API_GUN_RETIRE,
    GUIDE_COURSE_10352
)

CONFIG = {
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "MACRO_LOOPS": 200,
    "MISSIONS_PER_RETIRE": 50,
    "TEAM_ID": 1,
    "BASE_URL": SERVERS["M4A1"],
    "PROXY_PORT": 8080
}

current_worker_thread = None
worker_mode = None
proxy_instance = None

stop_macro_flag = False
stop_micro_flag = False

def on_traffic(event_type: str, url: str, data: dict):
    if event_type == "SYS_KEY_UPGRADE":
        CONFIG["USER_UID"] = data.get("uid")
        CONFIG["SIGN_KEY"] = data.get("sign")
        print(f"\n[+] SUCCESS! Keys Auto-Configured:")
        print(f"    UID  : {CONFIG['USER_UID']}")
        print(f"    SIGN : {CONFIG['SIGN_KEY']}")
        print("\n[!] CRITICAL: Please wait for the game to fully load into the Commander Screen!")
        print("[!] Then type '-r' to automatically stop proxy and begin farming.")

def check_step_error(resp: dict, step_name: str) -> bool:
    if "error_local" in resp:
        print(f"[-] {step_name} Local Error: {resp['error_local']}")
        return True
    if "error" in resp:
        print(f"[-] {step_name} Server Error: {resp['error']}")
        return True
    return False

def parse_random_node_drop(resp_data: dict):
    keys = list(resp_data.keys())
    try:
        target_idx = keys.index("building_defender_change") - 1
        if target_idx >= 0:
            reward_key = keys[target_idx]
            if reward_key not in ["trigger_para", "mission_win_step_control_ids", "spot_act_info"]:
                reward_val = resp_data[reward_key]
                print(f"[+] Random Node Drop Captured -> {reward_key} : {reward_val}")
    except ValueError:
        pass

def farm_mission_10352(client: GFLClient, team_id: int):
    mission_id = 10352

    if check_step_error(client.send_request(API_MISSION_COMBINFO, {"mission_id": mission_id}), "combinationInfo"): return None
    
    start_payload = {
        "mission_id": mission_id, 
        "spots": [{"spot_id": 13280, "team_id": team_id}],
        "squad_spots": [], 
        "sangvis_spots": [], 
        "vehicle_spots": [], 
        "ally_spots": [], 
        "mission_ally_spots": [],
        "ally_id": int(time.time())
    }
    if check_step_error(client.send_request(API_MISSION_START, start_payload), "startMission"): return None
    
    if check_step_error(client.send_request(API_INDEX_GUIDE, {"guide": json.dumps({"course": GUIDE_COURSE_10352}, separators=(',', ':'))}), "guide"): return None
    time.sleep(0.2)

    move1_payload = {
        "person_type": 1, "person_id": team_id,
        "from_spot_id": 13280, "to_spot_id": 13277, "move_type": 1
    }
    if check_step_error(client.send_request(API_MISSION_TEAM_MOVE, move1_payload), "teamMove1"): return None
    time.sleep(0.2)

    move2_payload = {
        "person_type": 1, "person_id": team_id,
        "from_spot_id": 13277, "to_spot_id": 13278, "move_type": 1
    }
    move2_resp = client.send_request(API_MISSION_TEAM_MOVE, move2_payload)
    if check_step_error(move2_resp, "teamMove2"): return None
    
    parse_random_node_drop(move2_resp)
    time.sleep(0.2)

    client.send_request(API_MISSION_ABORT, {"mission_id": mission_id})
    time.sleep(0.5)
    
    return []

def retire_guns(client: GFLClient, gun_uids: list):
    if not gun_uids: return
    print(f"[*] Submitting {len(gun_uids)} T-Dolls for Auto-Retire...")
    resp = client.send_request(API_GUN_RETIRE, gun_uids)
    if resp.get("success"): print("[+] Auto-Retire Successful!")
    else: print(f"[-] Retire Failed: {resp}")

def farm_worker():
    global stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread
    
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] SIGN_KEY is default. Run Capture (-c) first!")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])

    print("=== GFL Protocol Auto-Farming Started (Mission 10352) ===")
    for macro in range(1, CONFIG["MACRO_LOOPS"] + 1):
        if stop_macro_flag: break
        print(f"\n--- MACRO BATCH {macro} / {CONFIG['MACRO_LOOPS']} ---")
        
        batch_guns = []
        for micro in range(1, CONFIG["MISSIONS_PER_RETIRE"] + 1):
            if stop_micro_flag or stop_macro_flag: break
            dropped = farm_mission_10352(client, CONFIG["TEAM_ID"])
            if dropped is None:
                client.send_request(API_MISSION_ABORT, {"mission_id": 10352})
                time.sleep(3)
                continue
            batch_guns.extend(dropped)
            
        retire_guns(client, batch_guns)
        time.sleep(1)
        if stop_micro_flag: break
            
    print("\n[*] Farming runs ended.")
    worker_mode, current_worker_thread = None, None

def print_menu():
    print("\n================= MENU =================")
    print(" -c : Start Capture Proxy")
    print(" -r : Run Auto-Farming")
    print(" -q : Stop safely after current Macro")
    print(" -Q : Stop safely after current Micro")
    print(" -E : Exit program")
    print("========================================\n")

if __name__ == '__main__':
    print_menu()
    while True:
        try:
            cmd = input("GFL-COIN> ").strip()
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
                    print("[*] Stopping Proxy to begin farming...")
                    proxy_instance.stop()
                    set_windows_proxy(False)
                    proxy_instance = None
                    time.sleep(1)
                
                stop_macro_flag, stop_micro_flag = False, False
                worker_mode = 'r'
                current_worker_thread = threading.Thread(target=farm_worker)
                current_worker_thread.daemon = True
                current_worker_thread.start()
                
            elif cmd_prefix == '-q':
                stop_macro_flag = True
                print("[*] Will stop after current MACRO batch...")
            elif cmd_prefix == '-Q':
                stop_micro_flag = True
                print("[*] Will stop after current MICRO run...")
            elif cmd_prefix == '-E':
                if proxy_instance: proxy_instance.stop()
                set_windows_proxy(False)
                stop_macro_flag, stop_micro_flag = True, True
                print("[*] Exited cleanly. Windows proxy restored.")
                sys.exit(0)
                
        except KeyboardInterrupt:
            print("\n[!] Use '-E' to exit safely!")