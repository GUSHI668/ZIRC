# src/demo/farm/greyzone/greyzone_halloween.py

import sys
import time
import threading
from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN,
    API_DAILY_RESET_MAP, API_MISSION_START,
    API_MISSION_TEAM_MOVE, API_MISSION_ALLY_MYSIDE_MOVE,
    API_MISSION_END_TURN, API_MISSION_START_ENEMY_TURN,
    API_MISSION_END_ENEMY_TURN, API_MISSION_START_TURN,
    API_MISSION_ABORT, API_GUN_RETIRE,API_MISSION_BATTLE_FINISH,API_MISSION_BUILDING_SKILL_PERFORM_ON_DEATH
)

CONFIG = {
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "BASE_URL": SERVERS["M4A1"],
    "PROXY_PORT": 8080,
    # 1:探查点数，2:四项
    "TICKET_TYPE": 2,
    "USER_DEVICE": "705e6cc2f7bcc635accfcbac7df9bf86cd6f0e05"
}

# ==========================================
# Mission Configurations
# ==========================================
MISSION_CONFIGS = {
    580001: {
        "type": "BATTLE",
        "start_spot": 78122,
        "route": [78126, 78130, 78134, 78135, 78136, 78137, 78133, 78129,
                  78125, 78124, 78128, 78132, 78131, 78127, 78123],
        "on_battle": [78134, 78137, 78125, 78128],
        "building_missionskills_on_death_k": [2, 3, 0, 1],
        "has_ally_move": True
    },
    580002: {
        "type": "MOVE",
        "start_spot": 78138,
        "route": [78139, 78140, 78141, 78145, 78149, 78153, 78152, 78148, 
                  78147, 78151, 78150, 78146, 78142, 78143, 78144],
        "has_ally_move": True
    },
    580003: {
        "type": "MOVE",
        "start_spot": 78154,
        "route": [78155, 78156, 78157, 78161, 78165, 78169, 78168, 78164, 
                  78160, 78159, 78158, 78162, 78166, 78167, 78163, 78164, 78160],
        "has_ally_move": True
    },
    580004: {
        "type": "MOVE",
        "start_spot": 78170,
        "route": [78171, 78172, 78173, 78177, 78181, 78185, 78184, 78180, 
                  78176, 78175, 78174, 78178, 78182, 78183, 78179, 78175, 78174],
        "has_ally_move": True
    },
    580005: {
        "type": "MOVE",
        "start_spot": 78587,
        "route": [78588, 78592, 78591, 78595, 78599, 78600, 78601,
                  78602, 78598, 78594, 78590, 78589, 78593, 78597, 78596],
        "has_ally_move": True
    },
    580006: {
        "type": "BATTLE",
        "start_spot": 78603,
        "route": [78604, 78605, 78606, 78610, 78614, 78618, 78617, 
                  78616, 78615, 78611, 78607, 78608, 78609, 78613, 78612],
        "on_battle": [78605, 78614, 78616, 78607],
        "building_missionskills_on_death_k": [0, 2, 3, 1],
        "has_ally_move": True
    }
}

# ==========================================
# Global State
# ==========================================
current_worker_thread = None
worker_mode = None
proxy_instance = None
stop_macro_flag = False

total_halloween_points = 0

def check_step_error(resp: dict, step_name: str) -> bool:
    if not isinstance(resp, dict):
        print("[-] %s Error: Server returned invalid format." % step_name)
        return True
    if "error_local" in resp:
        print("[-] %s Local Error: %s" % (step_name, resp['error_local']))
        return True
    if "error" in resp:
        print("[-] %s Server Error: %s" % (step_name, resp['error']))
        return True
    return False

def on_traffic(event_type: str, url: str, data: dict):
    if event_type == "SYS_KEY_UPGRADE":
        CONFIG["USER_UID"] = data.get("uid")
        CONFIG["SIGN_KEY"] = data.get("sign")
        print("\n[+] SUCCESS! Keys Auto-Configured:")
        print("    UID  : %s" % CONFIG['USER_UID'])
        print("    SIGN : %s" % CONFIG['SIGN_KEY'])
        print("\n[!] CRITICAL: Please wait for the game to fully load into the Commander Screen!")
        print("[!] Then type '-f' to auto-farm Halloween GreyZone.")

# ==========================================
# Class: MapParser
# ==========================================
class MapParser:
    SPAWN_MAP = {
        "63": ["64", "56"],
        "70": ["62", "69"],
        "64": ["2", "10"], 
        "8": ["16", "7"]
    }

    @classmethod
    def parse(cls, resp: dict) -> list:
        status = resp.get("daily_status_with_user_info", {})
        map_list = resp.get("daily_map_with_user_info", [])
        
        respawn_spot = str(status.get("spot_id"))
        spots = {str(spot.get("spot_id")): spot.get("mission", "") for spot in map_list}
        
        results = []
        
        if respawn_spot in cls.SPAWN_MAP:
            adjacents = cls.SPAWN_MAP[respawn_spot]
            for adj in adjacents:
                mission_str = spots.get(adj, "")
                if not mission_str:
                    continue
                
                # mission_str usually looks like "1:580005,2:12345"
                mission_parts = mission_str.split(",")
                for part in mission_parts:
                    if part.startswith("1:58"):
                        try:
                            m_id = int(part.split(":")[1])
                            results.append({
                                "spot_id": int(adj),
                                "mission_id": m_id
                            })
                        except ValueError:
                            pass
        return results


# ==========================================
# Class Hierarchy: MissionRunner
# ==========================================
class MissionRunner:
    def __init__(self, client: GFLClient, mission_id: int, map_spot_id: int):
        self.client = client
        self.mission_id = mission_id
        self.map_spot_id = map_spot_id
        
        cfg = MISSION_CONFIGS.get(mission_id, {})
        self.start_spot = cfg.get("start_spot", 0)
        self.route = cfg.get("route", [])
        self.has_ally_move = cfg.get("has_ally_move", False)

    def run(self):
        raise NotImplementedError("Base run() method must be overridden.")

    def process_win_result(self, resp: dict):
        win_result = resp.get("mission_win_result", {})
        dropped_guns = []
        points = 0
        
        if win_result:
            # Extract Guns
            rg = win_result.get("reward_gun", [])
            for gun in rg:
                gun_uid = int(gun.get("gun_with_user_id"))
                dropped_guns.append(gun_uid)
                print("    [+] Dropped Gun UID: %d" % gun_uid)
            
            # Extract Halloween Points (Item ID: 10736)
            type5_drop = win_result.get("mission_type5_drop", {})
            item_dict = type5_drop.get("item", {})
            points = int(item_dict.get("10736", 0))
            
        return dropped_guns, points

class MissionRunnerMove(MissionRunner):
    def run(self):
        print("[>] Starting Mission %d on Map Spot %d..." % (self.mission_id, self.map_spot_id))
        start_payload = {
            "mission_id": self.mission_id,
            "spots": [],
            "squad_spots": [], 
            "sangvis_spots": [], 
            "vehicle_spots": [],
            "ally_spots": [], 
            "mission_ally_spots": [
                {
                    "spot_id": self.start_spot,
                    "ally_team_id": 78001,
                    "mission_myside_data": {
                        "sangvis": [],
                        "gun": {
                            "1": {"position": 8},
                            "2": {"position": 9},
                            "3": {"position": 7},
                            "4": {"position": 14},
                            "5": {"position": 13}
                        }
                    }
                }
            ],
            "ally_id": int(time.time()),
            "daily_param": {
                "spot_id": self.map_spot_id,
                "ticket_type": CONFIG["TICKET_TYPE"]
            },
            "fight_environment_skill_info": {}
        }
        
        print(start_payload)

        if check_step_error(self.client.send_request(API_MISSION_START, start_payload), "startMission"):
            return None, 0

        # Execute Moves
        curr_spot = self.start_spot
        for step, next_spot in enumerate(self.route, 1):
            print("[>] Step %d: Moving %d -> %d..." % (step, curr_spot, next_spot))
            move_payload = {
                "person_type": 3, "person_id": 1,
                "from_spot_id": curr_spot, "to_spot_id": next_spot, "move_type": 1
            }
            if check_step_error(self.client.send_request(API_MISSION_TEAM_MOVE, move_payload), "teamMove"):
                return None, 0
            curr_spot = next_spot
            time.sleep(0.1)

        # Optional Ally Move
        if self.has_ally_move:
            print("[>] Triggering Ally Move...")
            if check_step_error(self.client.send_request(API_MISSION_ALLY_MYSIDE_MOVE, {}), "allyMove"):
                return None, 0
            time.sleep(0.3)

        # End Sequence
        print("[>] Ending Turn sequence...")
        if check_step_error(self.client.send_request(API_MISSION_END_TURN, {}), "endTurn"): return None, 0
        time.sleep(0.2)
        if check_step_error(self.client.send_request(API_MISSION_START_ENEMY_TURN, {}), "startEnemyTurn"): return None, 0
        time.sleep(0.2)
        if check_step_error(self.client.send_request(API_MISSION_END_ENEMY_TURN, {}), "endEnemyTurn"): return None, 0
        time.sleep(0.2)

        win_resp = self.client.send_request(API_MISSION_START_TURN, {})
        if check_step_error(win_resp, "startTurn"): return None, 0
        
        return self.process_win_result(win_resp)

class MissionRunnerBattle(MissionRunner):
    def run(self):
        # Dictionary to keep track of random seeds for battle validation
        current_spots_state = {}

        def update_seeds(resp_data):
            if isinstance(resp_data, dict) and "spot_act_info" in resp_data:
                for s in resp_data["spot_act_info"]:
                    current_spots_state[str(s.get("spot_id"))] = int(s.get("seed", 0))

        print("[>] Starting BATTLE Mission %d on Map Spot %d..." % (self.mission_id, self.map_spot_id))
        start_payload = {
            "mission_id": self.mission_id,
            "spots": [],
            "squad_spots": [], 
            "sangvis_spots": [], 
            "vehicle_spots": [],
            "ally_spots": [], 
            "mission_ally_spots": [
                {
                    "spot_id": self.start_spot,
                    "ally_team_id": 78001,
                    "mission_myside_data": {
                        "sangvis": [],
                        "gun": {
                            "1": {"position": 8},
                            "2": {"position": 9},
                            "3": {"position": 7},
                            "4": {"position": 14},
                            "5": {"position": 13}
                        }
                    }
                }
            ],
            "ally_id": int(time.time()),
            "daily_param": {
                "spot_id": self.map_spot_id,
                "ticket_type": CONFIG["TICKET_TYPE"]
            },
            "fight_environment_skill_info": {}
        }

        start_resp = self.client.send_request(API_MISSION_START, start_payload)
        if check_step_error(start_resp, "startMission"):
            return None, 0
            
        update_seeds(start_resp)

        # Retrieve battle configs
        cfg = MISSION_CONFIGS.get(self.mission_id, {})
        on_battle_list = cfg.get("on_battle", [])
        death_k_list = cfg.get("building_missionskills_on_death_k", [])

        # Execute Moves and Battles
        curr_spot = self.start_spot
        for step, next_spot in enumerate(self.route, 1):
            print("[>] Step %d: Moving %d -> %d..." % (step, curr_spot, next_spot))
            move_payload = {
                "person_type": 3, "person_id": 1,
                "from_spot_id": curr_spot, "to_spot_id": next_spot, "move_type": 1
            }
            move_resp = self.client.send_request(API_MISSION_TEAM_MOVE, move_payload)
            if check_step_error(move_resp, "teamMove"):
                return None, 0
                
            update_seeds(move_resp)
            curr_spot = next_spot
            time.sleep(0.1)

            # --- Check if current spot is a BATTLE spot ---
            if curr_spot in on_battle_list:
                battle_idx = on_battle_list.index(curr_spot)
                # Fail-safe to avoid index out of bounds
                k_val = death_k_list[battle_idx] if battle_idx < len(death_k_list) else 0
                seed = current_spots_state.get(str(curr_spot), 0)

                print("    [!] Battle Triggered at spot %d | Seed: %d | k_val: %d" % (curr_spot, seed, k_val))
                
                # --- Step 1: send battleFinish ---
                battle_payload = {
                    "spot_id": curr_spot,
                    "if_enemy_die": True,
                    "current_time": int(time.time()),
                    "boss_hp": 0,
                    "mvp": 1084,
                    "last_battle_info": "",
                    "use_skill_squads": [],
                    "use_skill_ally_spots": [],
                    "use_skill_vehicle_spots": [],
                    "guns": [ 
                        { "id": 1084, "life": 565 }, 
                        { "id": 1085, "life": 540 }, 
                        { "id": 1086, "life": 565 }, 
                        { "id": 1087, "life": 605 }, 
                        { "id": 1088, "life": 1040 } 
                    ],
                    "user_rec": '{"seed":%d,"record":[]}' % seed,
                    "1000": { "10": 32089, "11": 32089, "12": 32089, "13": 32089, "15": 531, "16": 0, "17": 43, "33": 10001, "40": 9, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 811, "25": 0, "26": 811, "27": 4, "34": 5, "35": 5, "41": 90, "42": 0, "43": 0, "44": 0 },
                    "1001": {},
                    "1002": { "1084": { "47": 0 }, "1085": { "47": 0 }, "1086": { "47": 0 }, "1087": { "47": 0 }, "1088": { "47": 0 } },
                    "1003": {},
                    "1005": {},
                    "1007": {},
                    "1008": {},
                    "1009": {},
                    "battle_damage": {},
                    "micalog": {
                        "user_device": CONFIG["USER_DEVICE"],
                        "user_ip": ""
                    }
                }
                
                if check_step_error(self.client.send_request(API_MISSION_BATTLE_FINISH, battle_payload), "battleFinish"):
                    return None, 0
                time.sleep(0.1)

                # --- Step 2: send buildingSkillPerformOnDeath ---
                print("    [!] BuildingSkillPerformOnDeath for target %d" % self.start_spot)
                building_payload = {
                    "building_missionskills_on_death_k": {
                        str(self.start_spot): [k_val]
                    }
                }
                
                if check_step_error(self.client.send_request(API_MISSION_BUILDING_SKILL_PERFORM_ON_DEATH, building_payload), "buildingSkillPerformOnDeath"):
                    return None, 0
                time.sleep(0.1)

        # Optional Ally Move
        if self.has_ally_move:
            print("[>] Triggering Ally Move...")
            if check_step_error(self.client.send_request(API_MISSION_ALLY_MYSIDE_MOVE, {}), "allyMove"):
                return None, 0
            time.sleep(0.3)

        # End Sequence
        print("[>] Ending Turn sequence...")
        if check_step_error(self.client.send_request(API_MISSION_END_TURN, {}), "endTurn"): return None, 0
        time.sleep(0.2)
        if check_step_error(self.client.send_request(API_MISSION_START_ENEMY_TURN, {}), "startEnemyTurn"): return None, 0
        time.sleep(0.2)
        if check_step_error(self.client.send_request(API_MISSION_END_ENEMY_TURN, {}), "endEnemyTurn"): return None, 0
        time.sleep(0.2)

        win_resp = self.client.send_request(API_MISSION_START_TURN, {})
        if check_step_error(win_resp, "startTurn"): return None, 0
        
        return self.process_win_result(win_resp)


# ==========================================
# Worker Logic
# ==========================================
def retire_guns(client: GFLClient, gun_uids: list):
    if not gun_uids: 
        return
    print("[*] Submitting %d T-Dolls for Auto-Retire..." % len(gun_uids))
    resp = client.send_request(API_GUN_RETIRE, gun_uids)
    if resp.get("success"): 
        print("[+] Auto-Retire Successful!")
    else: 
        print("[-] Retire Failed: %s" % str(resp))


def halloween_farm_worker():
    global stop_macro_flag, worker_mode, current_worker_thread, total_halloween_points
    
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] SIGN_KEY is default. Run Capture (-c) first!")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    print("=== GFL Halloween GreyZone Auto-Farm Started ===")
    
    attempts = 0
    while not stop_macro_flag:
        attempts += 1
        print("\n[*] Reset Map Attempt %d..." % attempts)
        
        resp = client.send_request(API_DAILY_RESET_MAP, {"difficulty": 3})
        if check_step_error(resp, "resetMap"):
            time.sleep(3)
            continue
            
        targets = MapParser.parse(resp)
        if not targets:
            print("    [-] No valid Halloween found. Retrying...")
            time.sleep(0.1)
            continue
            
        for target in targets:
            m_id = target["mission_id"]
            s_id = target["spot_id"]
            print("\n[+] FOUND HALLOWEEN MISSION! Spot: %d | Mission ID: %d" % (s_id, m_id))
            
            if m_id not in MISSION_CONFIGS:
                print("[!] Mission %d is not configured in MISSION_CONFIGS!" % m_id)
                print("[!] Worker Paused.")
                stop_macro_flag = True
                break
                
            m_type = MISSION_CONFIGS[m_id].get("type")
            if m_type == "MOVE":
                runner = MissionRunnerMove(client, m_id, s_id)
            elif m_type == "BATTLE":
                runner = MissionRunnerBattle(client, m_id, s_id)
            else:
                print("[!] Unknown mission type for %d" % m_id)
                stop_macro_flag = True
                break
                
            dropped_guns, points = runner.run()
            
            if dropped_guns is None:
                print("[-] Run failed or aborted. Worker Paused.")
                stop_macro_flag = True
                break
                
            retire_guns(client, dropped_guns)
            
            total_halloween_points += points
            r_num = total_halloween_points // 6000
            r_rem = total_halloween_points % 6000
            
            print("\n========================================")
            print("[+] Mission Completed! Points Gained: %d" % points)
            print("[+] TOTAL HALLOWEEN POINTS: %d" % total_halloween_points)
            print("[+] Progress: %d/6000 (Completed %d Rounds)" % (r_rem, r_num))
            print("========================================\n")
            
            time.sleep(1)

        if stop_macro_flag:
            break
        
    print("\n[*] Halloween Farm Worker ended.")
    worker_mode, current_worker_thread = None, None


def print_menu():
    print("\n================= MENU =================")
    print(" -c : Start Capture Proxy")
    print(" -f : Run Halloween Auto-Farm")
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
            cmd = input("GFL-HW-GZ> ").strip()
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
                
            elif cmd_prefix == '-f':
                shutdown_proxy_if_running()
                stop_macro_flag = False
                worker_mode = 'f'
                current_worker_thread = threading.Thread(target=halloween_farm_worker)
                current_worker_thread.daemon = True
                current_worker_thread.start()
                
            elif cmd_prefix == '-q':
                stop_macro_flag = True
                print("[*] Will stop loop after current execution...")
                
            elif cmd_prefix == '-E':
                if proxy_instance: proxy_instance.stop()
                set_windows_proxy(False)
                stop_macro_flag = True
                print("[*] Exited cleanly. Windows proxy restored.")
                sys.exit(0)
                
        except KeyboardInterrupt:
            print("\n[!] Use '-E' to exit safely!")