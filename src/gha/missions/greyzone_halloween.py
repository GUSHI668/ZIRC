# src/gha/missions/greyzone_halloween.py

import time
from .base import BaseMission

from gflzirc import (
    API_DAILY_RESET_MAP, API_MISSION_START,
    API_MISSION_TEAM_MOVE, API_MISSION_ALLY_MYSIDE_MOVE,
    API_MISSION_END_TURN, API_MISSION_START_ENEMY_TURN,
    API_MISSION_END_ENEMY_TURN, API_MISSION_START_TURN,
    API_MISSION_BATTLE_FINISH, API_MISSION_BUILDING_SKILL_PERFORM_ON_DEATH
)

MISSION_CONFIGS = {
    580001: {
        "type": "BATTLE", "start_spot": 78122,
        "route": [78126, 78130, 78134, 78135, 78136, 78137, 78133, 78129,
                  78125, 78124, 78128, 78132, 78131, 78127, 78123],
        "on_battle": [78134, 78137, 78125, 78128],
        "building_missionskills_on_death_k": [2, 3, 0, 1],
        "has_ally_move": True
    },
    580002: {
        "type": "MOVE", "start_spot": 78138,
        "route": [78139, 78140, 78141, 78145, 78149, 78153, 78152, 78148, 
                  78147, 78151, 78150, 78146, 78142, 78143, 78144],
        "has_ally_move": True
    },
    580003: {
        "type": "MOVE", "start_spot": 78154,
        "route": [78155, 78156, 78157, 78161, 78165, 78169, 78168, 78164, 
                  78160, 78159, 78158, 78162, 78166, 78167, 78163, 78164, 78160],
        "has_ally_move": True
    },
    580004: {
        "type": "MOVE", "start_spot": 78170,
        "route": [78171, 78172, 78173, 78177, 78181, 78185, 78184, 78180, 
                  78176, 78175, 78174, 78178, 78182, 78183, 78179, 78175, 78174],
        "has_ally_move": True
    },
    580005: {
        "type": "MOVE", "start_spot": 78587,
        "route": [78588, 78592, 78591, 78595, 78599, 78600, 78601,
                  78602, 78598, 78594, 78590, 78589, 78593, 78597, 78596],
        "has_ally_move": True
    },
    580006: {
        "type": "BATTLE", "start_spot": 78603,
        "route": [78604, 78605, 78606, 78610, 78614, 78618, 78617, 
                  78616, 78615, 78611, 78607, 78608, 78609, 78613, 78612],
        "on_battle": [78605, 78614, 78616, 78607],
        "building_missionskills_on_death_k": [0, 2, 3, 1],
        "has_ally_move": True
    }
}

SPAWN_MAP = {
    "63": ["64", "56"],
    "70": ["62", "69"],
    "64": ["2", "10"], 
    "8": ["16", "7"]
}

class GreyZoneHalloweenMission(BaseMission):
    def __init__(self, agent):
        super().__init__(agent)
        self.ticket_type = int(self.config.get("TICKET_TYPE", 2))
        self.user_device = self.agent.user_device
        self.total_points = 0
        self.current_mission_id = 580001

    def get_mission_id(self) -> int:
        return self.current_mission_id

    def prepare(self):
        print("\n[>] === Pre-flight Check: GreyZone Halloween Initialization ===")
        print(f"[*] TICKET_TYPE configured as: {self.ticket_type}")
        print("[>] === Pre-flight Check Successful ===\n")

    def _parse_map(self, resp: dict) -> list:
        status = resp.get("daily_status_with_user_info", {})
        map_list = resp.get("daily_map_with_user_info", [])
        
        respawn_spot = str(status.get("spot_id"))
        spots = {str(spot.get("spot_id")): spot.get("mission", "") for spot in map_list}
        
        results = []
        if respawn_spot in SPAWN_MAP:
            adjacents = SPAWN_MAP[respawn_spot]
            for adj in adjacents:
                mission_str = spots.get(adj, "")
                if not mission_str: continue
                
                mission_parts = mission_str.split(",")
                for part in mission_parts:
                    if part.startswith("1:58"):
                        try:
                            m_id = int(part.split(":")[1])
                            results.append({"spot_id": int(adj), "mission_id": m_id})
                        except ValueError: pass
        return results

    def farm(self) -> list:
        # 1. Reset Map until a valid Halloween mission is found (max 100 retries to avoid infinite loop)
        target = None
        for attempt in range(1, 101):
            print(f"[>] Reset Map Attempt {attempt}...")
            resp = self.agent.safe_request(API_DAILY_RESET_MAP, {"difficulty": 3}, "resetMap")
            if self.agent.check_step_error(resp, "resetMap"):
                time.sleep(3)
                continue
                
            targets = self._parse_map(resp)
            if targets:
                target = targets[0]
                break
            
            print("    [-] No valid Halloween mission found. Retrying...")
            time.sleep(1)

        if not target:
            print("[-] Failed to find a valid Halloween mission after 10 resets.")
            return None

        m_id = target["mission_id"]
        s_id = target["spot_id"]
        self.current_mission_id = m_id
        
        print(f"\n[+] FOUND HALLOWEEN MISSION! Spot: {s_id} | Mission ID: {m_id}")

        cfg = MISSION_CONFIGS.get(m_id)
        if not cfg:
            print(f"[-] Mission {m_id} is not configured.")
            return None

        # 2. Execute Mission
        drops = None
        if cfg["type"] == "MOVE":
            drops = self._run_move_mission(m_id, s_id, cfg)
        elif cfg["type"] == "BATTLE":
            drops = self._run_battle_mission(m_id, s_id, cfg)

        return drops

    def _extract_points(self, win_resp: dict):
        win_result = win_resp.get("mission_win_result", {})
        if not win_result: return
        
        type5_drop = win_result.get("mission_type5_drop", {})
        item_dict = type5_drop.get("item", {})
        points = int(item_dict.get("10736", 0))
        
        self.total_points += points
        r_num = self.total_points // 6000
        r_rem = self.total_points % 6000
        
        print("\n========================================")
        print(f"[+] Mission Completed! Points Gained: {points}")
        print(f"[+] TOTAL HALLOWEEN POINTS: {self.total_points}")
        print(f"[+] Progress: {r_rem}/6000 (Completed {r_num} Rounds)")
        print("========================================\n")

    def _run_move_mission(self, m_id: int, s_id: int, cfg: dict):
        print(f"[>] Starting MOVE Mission {m_id} on Spot {s_id}...")
        start_payload = {
            "mission_id": m_id, "spots": [], "squad_spots": [], "sangvis_spots": [], "vehicle_spots": [],
            "ally_spots": [], "ally_id": int(time.time()),
            "mission_ally_spots": [{
                "spot_id": cfg["start_spot"],
                "ally_team_id": 78001,
                "mission_myside_data": {
                    "sangvis": [],
                    "gun": {"1": {"position": 8}, "2": {"position": 9}, "3": {"position": 7}, "4": {"position": 14}, "5": {"position": 13}}
                }
            }],
            "daily_param": {"spot_id": s_id, "ticket_type": self.ticket_type},
            "fight_environment_skill_info": {}
        }

        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_START, start_payload, "startMission"), "startMission"): return None

        curr_spot = cfg["start_spot"]
        for step, next_spot in enumerate(cfg["route"], 1):
            move_payload = {
                "person_type": 3, "person_id": 1,
                "from_spot_id": curr_spot, "to_spot_id": next_spot, "move_type": 1
            }
            if self.agent.check_step_error(self.agent.safe_request(API_MISSION_TEAM_MOVE, move_payload, f"teamMove_{step}"), "teamMove"): return None
            curr_spot = next_spot
            time.sleep(0.1)

        if cfg["has_ally_move"]:
            if self.agent.check_step_error(self.agent.safe_request(API_MISSION_ALLY_MYSIDE_MOVE, {}, "allyMove"), "allyMove"): return None
            time.sleep(0.3)

        return self._execute_end_sequence()

    def _run_battle_mission(self, m_id: int, s_id: int, cfg: dict):
        current_spots_state = {}
        def update_seeds(resp_data):
            if isinstance(resp_data, dict) and "spot_act_info" in resp_data:
                for s in resp_data["spot_act_info"]:
                    current_spots_state[str(s.get("spot_id"))] = int(s.get("seed", 0))

        print(f"[>] Starting BATTLE Mission {m_id} on Spot {s_id}...")
        start_payload = {
            "mission_id": m_id, "spots": [], "squad_spots": [], "sangvis_spots": [], "vehicle_spots": [],
            "ally_spots": [], "ally_id": int(time.time()),
            "mission_ally_spots": [{
                "spot_id": cfg["start_spot"],
                "ally_team_id": 78001,
                "mission_myside_data": {
                    "sangvis": [],
                    "gun": {"1": {"position": 8}, "2": {"position": 9}, "3": {"position": 7}, "4": {"position": 14}, "5": {"position": 13}}
                }
            }],
            "daily_param": {"spot_id": s_id, "ticket_type": self.ticket_type},
            "fight_environment_skill_info": {}
        }

        start_resp = self.agent.safe_request(API_MISSION_START, start_payload, "startMission")
        if self.agent.check_step_error(start_resp, "startMission"): return None
        update_seeds(start_resp)

        on_battle_list = cfg.get("on_battle", [])
        death_k_list = cfg.get("building_missionskills_on_death_k", [])

        curr_spot = cfg["start_spot"]
        for step, next_spot in enumerate(cfg["route"], 1):
            move_payload = {
                "person_type": 3, "person_id": 1,
                "from_spot_id": curr_spot, "to_spot_id": next_spot, "move_type": 1
            }
            move_resp = self.agent.safe_request(API_MISSION_TEAM_MOVE, move_payload, f"teamMove_{step}")
            if self.agent.check_step_error(move_resp, "teamMove"): return None
            update_seeds(move_resp)
            curr_spot = next_spot
            time.sleep(0.1)

            if curr_spot in on_battle_list:
                battle_idx = on_battle_list.index(curr_spot)
                k_val = death_k_list[battle_idx] if battle_idx < len(death_k_list) else 0
                seed = current_spots_state.get(str(curr_spot), 0)
                
                print(f"    [!] Battle Triggered at spot {curr_spot} | Seed: {seed} | k_val: {k_val}")
                
                battle_payload = {
                    "spot_id": curr_spot, "if_enemy_die": True, "current_time": int(time.time()),
                    "boss_hp": 0, "mvp": 1084, "last_battle_info": "", "use_skill_squads": [], 
                    "use_skill_ally_spots": [], "use_skill_vehicle_spots": [],
                    "guns": [ {"id": 1084, "life": 565}, {"id": 1085, "life": 540}, {"id": 1086, "life": 565}, {"id": 1087, "life": 605}, {"id": 1088, "life": 1040} ],
                    "user_rec": '{"seed":%d,"record":[]}' % seed,
                    "1000": { "10": 32089, "11": 32089, "12": 32089, "13": 32089, "15": 531, "16": 0, "17": 43, "33": 10001, "40": 9, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 811, "25": 0, "26": 811, "27": 4, "34": 5, "35": 5, "41": 90, "42": 0, "43": 0, "44": 0 },
                    "1001": {},
                    "1002": { "1084": {"47": 0}, "1085": {"47": 0}, "1086": {"47": 0}, "1087": {"47": 0}, "1088": {"47": 0} },
                    "1003": {}, "1005": {}, "1007": {}, "1008": {}, "1009": {}, "battle_damage": {},
                    "micalog": {"user_device": self.user_device, "user_ip": ""}
                }
                
                if self.agent.check_step_error(self.agent.safe_request(API_MISSION_BATTLE_FINISH, battle_payload, f"battleFinish_{curr_spot}"), "battleFinish"): return None
                time.sleep(0.1)

                building_payload = {"building_missionskills_on_death_k": {str(cfg["start_spot"]): [k_val]}}
                if self.agent.check_step_error(self.agent.safe_request(API_MISSION_BUILDING_SKILL_PERFORM_ON_DEATH, building_payload, "buildingSkill"), "buildingSkillPerformOnDeath"): return None
                time.sleep(0.1)

        if cfg["has_ally_move"]:
            if self.agent.check_step_error(self.agent.safe_request(API_MISSION_ALLY_MYSIDE_MOVE, {}, "allyMove"), "allyMove"): return None
            time.sleep(0.3)

        return self._execute_end_sequence()

    def _execute_end_sequence(self):
        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_END_TURN, {}, "endTurn"), "endTurn"): return None
        time.sleep(0.2)
        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_START_ENEMY_TURN, {}, "startEnemyTurn"), "startEnemyTurn"): return None
        time.sleep(0.2)
        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_END_ENEMY_TURN, {}, "endEnemyTurn"), "endEnemyTurn"): return None
        time.sleep(0.2)

        win_resp = self.agent.safe_request(API_MISSION_START_TURN, {}, "startTurn")
        if self.agent.check_step_error(win_resp, "startTurn"): return None
        
        self._extract_points(win_resp)
        return self.agent.check_drop_result(win_resp)