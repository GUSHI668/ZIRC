import sys
import time
import json
import shlex
import threading
from gflzirc import GFLClient, GFLCaptureProxy, set_windows_proxy

CONFIG = {
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": "1234567890abcdefghijklmnopqrstuv",
    "STATIC_KEY": "yundoudou",
    "MACRO_LOOPS": 200,
    "MISSIONS_PER_RETIRE": 50,
    "SQUAD_ID": 106360,
    "BASE_URL": "http://gfcn-game.gw.merge.sunborngame.com/index.php/1000",
    "PROXY_PORT": 8080
}

current_worker_thread = None
worker_mode = None
proxy_instance = None

stop_macro_flag = False
stop_micro_flag = False

def on_keys_captured(uid: str, sign: str):
    CONFIG["USER_UID"] = uid
    CONFIG["SIGN_KEY"] = sign
    print(f"\n[+] SUCCESS! Keys Auto-Configured:")
    print(f"    UID  : {CONFIG['USER_UID']}")
    print(f"    SIGN : {CONFIG['SIGN_KEY']}")
    print("\n[!] CRITICAL: Please wait for the game to fully load into the Commander Screen!")
    print("[!] Then type '-r' to auto-farm, or '-g' to auto-reset GreyZone.")

def check_step_error(resp: dict, step_name: str) -> bool:
    if "error_local" in resp:
        print(f"[-] {step_name} Local Error: {resp['error_local']}")
        return True
    if "error" in resp:
        print(f"[-] {step_name} Server Error: {resp['error']}")
        return True
    return False

def check_drop_result(response_data: dict) -> list:
    collected_guns = []
    win_result = response_data.get("mission_win_result", {})
    if not win_result: return collected_guns
        
    reward_guns = win_result.get("reward_gun", [])
    if reward_guns:
        for gun in reward_guns:
            gun_id = gun.get('gun_id')
            gun_uid = int(gun.get('gun_with_user_id'))
            print(f"[+] Got T-Doll! Gun ID: {gun_id} | UID: {gun_uid} | Time: {time.strftime('%H:%M:%S')}")
            collected_guns.append(gun_uid)
    return collected_guns

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
    
    if CONFIG["SIGN_KEY"] == "1234567890abcdefghijklmnopqrstuv":
        print("[!] SIGN_KEY is default. Run Capture (-c) first!")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    print("=== GFL GreyZone Auto-Reset Started ===")
    
    attempts = 0
    while not stop_macro_flag:
        attempts += 1
        print(f"[*] Attempt {attempts}: Requesting Map Reset...")
        
        resp = client.send_request("Daily/resetMap", {"difficulty": 4})
        if check_step_error(resp, "resetMap"):
            time.sleep(3)
            continue
            
        if check_greyzone_conditions(resp):
            print(f"\n[+] SUCCESS! Desired GreyZone map generated after {attempts} attempts!")
            break
            
        # Sleep to wait server, [0.5, 1.5] might better
        time.sleep(0.1)
        
    print("\n[*] GreyZone reset worker ended.")
    worker_mode, current_worker_thread = None, None

def farm_mission_11880(client: GFLClient, squad_id: int):
    mission_id = 11880
    GUIDE_COURSE = [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,1,1,1,1,0,1,0,0,0,0,0,0,1,1,1,1,1,1,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,1,0,0,0,0,0,0,1,1,1,0,0,1,0,1,1,1,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,1,1,1,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,1,1,1,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]

    if check_step_error(client.send_request("Mission/combinationInfo", {"mission_id": mission_id}), "combinationInfo"): return None
    
    start_payload = {
        "mission_id": mission_id, "spots": [],
        "squad_spots": [{"spot_id": 901926, "squad_with_user_id": squad_id, "battleskill_switch": 1}],
        "sangvis_spots": [], "vehicle_spots": [], "ally_spots": [], "mission_ally_spots": [],
        "ally_id": int(time.time())
    }
    if check_step_error(client.send_request("Mission/startMission", start_payload), "startMission"): return None
    if check_step_error(client.send_request("Index/guide", {"guide": json.dumps({"course": GUIDE_COURSE}, separators=(',', ':'))}), "guide"): return None
    
    time.sleep(0.5)
    if check_step_error(client.send_request("Mission/endTurn", {}), "endTurn"): return None
    time.sleep(0.2)
    if check_step_error(client.send_request("Mission/startEnemyTurn", {}), "startEnemyTurn"): return None
    time.sleep(0.2)
    if check_step_error(client.send_request("Mission/endEnemyTurn", {}), "endEnemyTurn"): return None
    time.sleep(0.2)
    
    final_resp = client.send_request("Mission/startTurn", {})
    if check_step_error(final_resp, "startTurn"): return None
    
    return check_drop_result(final_resp)

def retire_guns(client: GFLClient, gun_uids: list):
    if not gun_uids: return
    print(f"[*] Submitting {len(gun_uids)} T-Dolls for Auto-Retire...")
    resp = client.send_request("Gun/retireGun", gun_uids)
    if resp.get("success"): print("[+] Auto-Retire Successful!")
    else: print(f"[-] Retire Failed: {resp}")

def farm_worker():
    global stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread
    
    if CONFIG["SIGN_KEY"] == "1234567890abcdefghijklmnopqrstuv":
        print("[!] SIGN_KEY is default. Run Capture (-c) first!")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])

    print("=== GFL Protocol Auto-Farming Started ===")
    for macro in range(1, CONFIG["MACRO_LOOPS"] + 1):
        if stop_macro_flag: break
        print(f"\n--- MACRO BATCH {macro} / {CONFIG['MACRO_LOOPS']} ---")
        
        batch_guns = []
        for micro in range(1, CONFIG["MISSIONS_PER_RETIRE"] + 1):
            if stop_micro_flag or stop_macro_flag: break
            dropped = farm_mission_11880(client, CONFIG["SQUAD_ID"])
            if dropped is None:
                client.send_request("Mission/abortMission", {"mission_id": 11880})
                time.sleep(3)
                continue
            batch_guns.extend(dropped)
            time.sleep(1)
            
        retire_guns(client, batch_guns)
        time.sleep(2)
        if stop_micro_flag: break
            
    print("\n[*] Farming runs ended.")
    worker_mode, current_worker_thread = None, None

def print_menu():
    print("\n================= MENU =================")
    print(" -c : Start Capture Proxy")
    print(" -r : Run Auto-Farming")
    print(" -g : Run GreyZone Auto-Reset")
    print(" -q : Stop safely after current Macro")
    print(" -Q : Stop safely after current Micro")
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
            cmd = input("GFL-F2P> ").strip()
            if not cmd: continue
            cmd_prefix = cmd.split()[0]
            
            if cmd_prefix == '-c':
                if proxy_instance:
                    print("[!] Proxy is already running!")
                    continue
                proxy_instance = GFLCaptureProxy(CONFIG["PROXY_PORT"], CONFIG["STATIC_KEY"], on_keys_captured)
                proxy_instance.start()
                set_windows_proxy(True, f"127.0.0.1:{CONFIG['PROXY_PORT']}")
                worker_mode = 'c'
                print(f"[*] Capture Proxy Started on {CONFIG['PROXY_PORT']}. Windows Proxy SET.")
                
            elif cmd_prefix == '-r':
                shutdown_proxy_if_running()
                stop_macro_flag, stop_micro_flag = False, False
                worker_mode = 'r'
                current_worker_thread = threading.Thread(target=farm_worker)
                current_worker_thread.daemon = True
                current_worker_thread.start()
                
            elif cmd_prefix == '-g':
                shutdown_proxy_if_running()
                stop_macro_flag, stop_micro_flag = False, False
                worker_mode = 'g'
                current_worker_thread = threading.Thread(target=greyzone_reset_worker)
                current_worker_thread.daemon = True
                current_worker_thread.start()
                
            elif cmd_prefix == '-q':
                stop_macro_flag = True
                print("[*] Will stop after current MACRO batch or Loop...")
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