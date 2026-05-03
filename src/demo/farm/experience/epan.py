# src/demo/farm/experience/epan.py

import sys
import time
import threading
from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN,
    API_MISSION_COMBINFO, API_MISSION_START,
    API_MISSION_TEAM_MOVE, API_MISSION_END_TURN,
    API_MISSION_START_ENEMY_TURN, API_MISSION_END_ENEMY_TURN,
    API_MISSION_START_TURN, API_MISSION_ABORT, API_GUN_RETIRE,
    API_MISSION_SUPPLY, API_MISSION_BATTLE_FINISH,API_RETIRE_EQUIP,
)

CONFIG = {
# === Authentication & Connection ===
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "BASE_URL": SERVERS["M4A1"],
    "PROXY_PORT": 8080,

# === Farm Loop Settings ===
    "MACRO_LOOPS": 200,
    "MISSIONS_PER_RETIRE": 10,

# === Mission Specific Config ===
    # EPA: N1
    "MISSION_ID": 151,
    "START_SPOT": 97253,
    "ROUTE": [97248, 97249, 97250, 97251, 97252],
    
    # Target Device Hash 
    "USER_DEVICE": "705e6cc2f7bcc635accfcbac7df9bf86cd6f0e05",

# === Team Config ===
    # Echelon ID
    "TEAM_ID": 1,
    
    # Target Fairy UID (Set to 0 or None if no fairy is equipped)
    "FAIRY_ID": 3566859,
    
    # Target Echelon Guns UID and starting life(HP)
    "GUNS": [
        {
            "id": 515093632,
            "life": 895
        }
    ]
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
        print("\n[+] SUCCESS! Keys Auto-Configured:")
        print("    UID  : %s" % CONFIG['USER_UID'])
        print("    SIGN : %s" % CONFIG['SIGN_KEY'])
        print("\n[!] CRITICAL: Please wait for the game to fully load into the Commander Screen!")
        print("[!] Then type '-r' to automatically stop proxy and begin farming.")

def check_step_error(resp: dict, step_name: str) -> bool:
    if "error_local" in resp:
        print("[-] %s Local Error: %s" % (step_name, resp['error_local']))
        return True
    if "error" in resp:
        print("[-] %s Server Error: %s" % (step_name, resp['error']))
        return True
    return False

def check_battle_drop(resp_data: dict, spot_id: int) -> list:
    collected = []
    bg = resp_data.get("battle_get_equip", [])
    if bg:
        for gun in bg:
            equip_id = gun.get("equip_id")
            equip_uid = int(gun.get("id"))
            print("    [+] Battle Drop (Node %d)! Equip ID: %s | UID: %d" % 
                  (spot_id, equip_id, equip_uid))
            collected.append(equip_uid)
    return collected

def check_battle_exp(resp_data: dict, spot_id: int) -> bool:
    """Parses gun_exp from response. Returns True if any gun hit MAX level (0 EXP)."""
    gun_exp_list = resp_data.get("gun_exp", [])
    cap_reached = False
    
    if gun_exp_list:
        exp_details = []
        for item in gun_exp_list:
            gun_uid = str(item.get("gun_with_user_id", "unknown"))
            exp_val = str(item.get("exp", "0"))
            exp_details.append("%s: +%s" % (gun_uid[-4:], exp_val))  # Show last 4 digits of UID for clean logs
            
            if exp_val == "0":
                print("    [!] WARNING: T-Doll %s has reached MAX level (0 EXP)!" % gun_uid)
                cap_reached = True
                
        print("    [+] Node %d EXP | %s" % (spot_id, " | ".join(exp_details)))
        
    return cap_reached

def check_win_drop(resp_data: dict) -> list:
    collected = []
    win_result = resp_data.get("mission_win_result", {})
    if win_result:
        rg = win_result.get("reward_equip", [])
        for gun in rg:
            equip_id = gun.get("equip_id")
            equip_uid = int(gun.get("id"))
            print("    [+] Mission Win Drop! Equip ID: %s | UID: %d" % 
                  (equip_id, equip_uid))
            collected.append(equip_uid)
    return collected

def get_mvp_generator():
    guns = CONFIG["GUNS"]
    idx = 0
    while True:
        yield guns[idx]["id"]
        idx = (idx + 1) % len(guns)

def farm_mission_epa(client: GFLClient, team_id: int, mvp_gen):
    global stop_macro_flag, stop_micro_flag
    
    mission_id = CONFIG["MISSION_ID"]
    start_spot = CONFIG["START_SPOT"]
    route = CONFIG["ROUTE"]
    
    dropped_uids = []
    current_spots_state = {}

    def update_seeds(resp):
        if isinstance(resp, dict) and "spot_act_info" in resp:
            for s in resp["spot_act_info"]:
                current_spots_state[str(s.get("spot_id"))] = int(s.get("seed", 0))

    # === 1. CombInfo & Start Mission ===
    print("[>] Requesting Combination Info...")
    if check_step_error(client.send_request(API_MISSION_COMBINFO, {"mission_id": mission_id}), "combInfo"): 
        return None

    print("[>] Starting Mission %d..." % mission_id)
    start_payload = {
        "mission_id": mission_id,
        "spots": [{"spot_id": start_spot, "team_id": team_id}],
        "squad_spots": [], "sangvis_spots": [], "vehicle_spots": [],
        "ally_spots": [], "mission_ally_spots": [],
        "ally_id": int(time.time())
    }
    start_resp = client.send_request(API_MISSION_START, start_payload)
    if check_step_error(start_resp, "startMission"): return None
    update_seeds(start_resp)

    # === 2. Supply Team (Uncomment if needed) ===
    # print("[>] Supplying Team %d at Node %d..." % (team_id, start_spot))
    # supply_payload = {
    #     "mission_id": mission_id,
    #     "target_type": 1,
    #     "target_id": team_id,
    #     "spot_id": start_spot
    # }
    # if check_step_error(client.send_request(API_MISSION_SUPPLY, supply_payload), "supplyTeam"): return None

    # === 3. Route Execution ===
    curr_spot = start_spot
    for step, next_spot in enumerate(route, 1):
        print("[>] Step %d: Moving %d -> %d..." % (step, curr_spot, next_spot))
        move_payload = {
            "person_type": 1, "person_id": team_id,
            "from_spot_id": curr_spot, "to_spot_id": next_spot, "move_type": 1
        }
        move_resp = client.send_request(API_MISSION_TEAM_MOVE, move_payload)
        if check_step_error(move_resp, "teamMove(%d->%d)" % (curr_spot, next_spot)): return None
        update_seeds(move_resp)

        client.send_request(API_MISSION_COMBINFO, {"mission_id": mission_id})

        seed = current_spots_state.get(str(next_spot), 0)
        current_mvp = next(mvp_gen)
        print("[>] Battle at Node %d (Seed: %d, MVP: %d)..." % (next_spot, seed, current_mvp))
        
        fairy_dict = {}
        if CONFIG.get("FAIRY_ID"):
            fairy_dict = {
                str(CONFIG["FAIRY_ID"]): {
                    "9": 1,
                    "68": 0
                }
            }

        battle_payload = {
            "spot_id": next_spot,
            "if_enemy_die": True,
            "current_time": int(time.time()),
            "boss_hp": 0,
            "mvp": current_mvp,
            "last_battle_info": "",
            "use_skill_squads": [],
            "use_skill_ally_spots": [],
            "use_skill_vehicle_spots": [],
            "guns": CONFIG["GUNS"],
            "user_rec": '{"seed":%d,"record":[]}' % seed,
            
            "1000": { "10": 37356, "11": 37356, "12": 37356, "13": 37356, "15": 27416, "16": 0, "17": 169, "33": 10016, "40": 307, "18": 0, "19": 415, "20": 0, "21": 0, "22": 200, "23": 600, "24": 42340, "25": 0, "26": 42340, "27": 6, "34": 84, "35": 84, "41": 137, "42": 0, "43": 0, "44": 0 },
            "1001": {},
            "1002": {str(g["id"]): {"47": 0} for g in CONFIG["GUNS"]},
            "1003": fairy_dict,
            "1005": {}, "1007": {}, "1008": {}, "1009": {},
            "battle_damage": {},
            "micalog": {
                "user_device": CONFIG["USER_DEVICE"],
                "user_ip": ""
            }
        }

        battle_resp = client.send_request(API_MISSION_BATTLE_FINISH, battle_payload)
        if check_step_error(battle_resp, "battleFinish(%d)" % next_spot): return None
        
        # Parse Drops
        dropped_uids.extend(check_battle_drop(battle_resp, next_spot))
        
        # --- Parse EXP and check for MAX level ---
        if check_battle_exp(battle_resp, next_spot):
            stop_macro_flag = True
            stop_micro_flag = True
            print("    [*] Auto-stop triggered to prevent EXP waste. Will safely stop after this run.")

        curr_spot = next_spot
        time.sleep(0.5)

    # === 4. Mission End Sequence ===
    print("[>] Ending Turn and calculating Win Condition...")
    if check_step_error(client.send_request(API_MISSION_END_TURN, {}), "endTurn"): return None
    time.sleep(0.2)
    if check_step_error(client.send_request(API_MISSION_START_ENEMY_TURN, {}), "startEnemyTurn"): return None
    time.sleep(0.2)
    if check_step_error(client.send_request(API_MISSION_END_ENEMY_TURN, {}), "endEnemyTurn"): return None
    time.sleep(0.2)

    win_resp = client.send_request(API_MISSION_START_TURN, {})
    if check_step_error(win_resp, "startTurn"): return None
    
    dropped_uids.extend(check_win_drop(win_resp))

    return dropped_uids

def equip_equips(client: GFLClient, equip_uids: list):
    if not equip_uids: 
        return
    print("[*] Submitting %d Equips for Auto-Retire..." % len(equip_uids))
    print(equip_uids)
    
    retire_payload = {
        "equips": equip_uids
    }

    resp = client.send_request(API_RETIRE_EQUIP, retire_payload)
    if resp.get("success"): 
        print("[+] Auto-Retire Successful!")
    else: 
        print("[-] Retire Failed: %s" % str(resp))

def farm_worker():
    global stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread
    
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] SIGN_KEY is default. Run Capture (-c) first or input manually!")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    mvp_gen = get_mvp_generator()

    print("=== GFL Protocol Auto-Farming Started (EPA) ===")
    for macro in range(1, CONFIG["MACRO_LOOPS"] + 1):
        if stop_macro_flag: break
        print("\n=== MACRO BATCH %d / %d ===" % (macro, CONFIG['MACRO_LOOPS']))
        
        batch_guns = []
        for micro in range(1, CONFIG["MISSIONS_PER_RETIRE"] + 1):
            if stop_micro_flag or stop_macro_flag: break
            
            print("\n[*] Starting Micro Run %d / %d ..." % (micro, CONFIG["MISSIONS_PER_RETIRE"]))
            dropped = farm_mission_epa(client, CONFIG["TEAM_ID"], mvp_gen)
            
            if dropped is None:
                print("[-] Run failed or aborted. Aborting mission...")
                client.send_request(API_MISSION_ABORT, {"mission_id": CONFIG["MISSION_ID"]})
                time.sleep(3)
                continue
                
            batch_guns.extend(dropped)
            time.sleep(1)
            
        equip_equips(client, batch_guns)
        time.sleep(2)
        if stop_micro_flag: break
            
    print("\n[*] Farming runs ended.")
    worker_mode, current_worker_thread = None, None

def print_menu():
    print("\n================= MENU =================")
    print(" -c : Start Capture Proxy")
    print(" -r : Run Auto-Farming (EPA)")
    print(" -q : Stop safely after current Macro")
    print(" -Q : Stop safely after current Micro")
    print(" -E : Exit program")
    print("========================================\n")

if __name__ == '__main__':
    print_menu()
    while True:
        try:
            cmd = input("GFL-EPA> ").strip()
            if not cmd: continue
            cmd_prefix = cmd.split()[0]
            
            if cmd_prefix == '-c':
                if proxy_instance:
                    print("[!] Proxy is already running!")
                    continue
                proxy_instance = GFLProxy(CONFIG["PROXY_PORT"], STATIC_KEY, on_traffic)
                proxy_instance.start()
                set_windows_proxy(True, "127.0.0.1:%d" % CONFIG['PROXY_PORT'])
                worker_mode = 'c'
                print("[*] Capture Proxy Started on %d. Windows Proxy SET." % CONFIG['PROXY_PORT'])
                
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
                if proxy_instance: 
                    proxy_instance.stop()
                set_windows_proxy(False)
                stop_macro_flag, stop_micro_flag = True, True
                print("[*] Exited cleanly. Windows proxy restored.")
                sys.exit(0)
                
        except KeyboardInterrupt:
            print("\n[!] Use '-E' to exit safely!")