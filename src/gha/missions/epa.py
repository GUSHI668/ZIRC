# src/gha/missions/epa.py

import time
import json
import sys
from .base import BaseMission

from gflzirc import (
    API_MISSION_COMBINFO, API_MISSION_START,
    API_MISSION_TEAM_MOVE, API_MISSION_END_TURN,
    API_MISSION_START_ENEMY_TURN, API_MISSION_END_ENEMY_TURN,
    API_MISSION_START_TURN, API_MISSION_BATTLE_FINISH, API_MISSION_ABORT
)

class BaseEPAMission(BaseMission):
    def __init__(self, agent, mode="fifo"):
        super().__init__(agent)
        self.mode = mode
        self.mission_id = 145
        self.start_spot = 97061
        self.route = [97039, 97040, 97041, 97036, 97031]
        self.user_device = agent.user_device
        
        self.teams = self.config.get("TEAMS", [])
        if not self.teams:
            print("[-] FATAL: No TEAMS configured in GFL_EPA_CONFIG.")
            sys.exit(1)
            
        self.active_team_indices = list(range(len(self.teams)))
        self.current_rr_ptr = 0
        
        # Create MVP Generators for each team
        self.mvp_gens = {i: self._get_mvp_gen(self.teams[i]) for i in range(len(self.teams))}

    def get_mission_id(self) -> int:
        return self.mission_id

    def _get_mvp_gen(self, team_config):
        guns = team_config.get("GUNS", [])
        if not guns:
            while True: yield 0
        idx = 0
        while True:
            yield guns[idx]["id"]
            idx = (idx + 1) % len(guns)

    def prepare(self):
        print("\n[>] === Pre-flight Check for EPA Echelons ===")
        drops_to_retire = []
        maxed_teams = []
        
        for idx in self.active_team_indices:
            team_id = self.teams[idx].get("TEAM_ID")
            print(f"[>] Testing Team Index {idx} (Echelon ID: {team_id})...")
            
            drops, all_maxed = self._run_mission(idx)
            
            if drops is None:
                print(f"[-] FATAL: Pre-flight check failed on Team Index {idx}. Aborting Workflow.")
                self.agent.safe_request(API_MISSION_ABORT, {"mission_id": self.mission_id}, "missionAbort", max_retries=1)
                sys.exit(1)
                
            drops_to_retire.extend(drops)
            if all_maxed:
                print(f"[!] WARNING: Team Index {idx} is already fully MAX level. Will be excluded.")
                maxed_teams.append(idx)
                
            time.sleep(2)
            
        # Retire pre-flight drops
        self.agent.retire_guns(drops_to_retire)
        
        # Remove teams that are already maxed
        for mt in maxed_teams:
            if mt in self.active_team_indices:
                self.active_team_indices.remove(mt)
                
        if not self.active_team_indices:
            print("[*] All configured echelons are fully maxed. Nothing to do.")
            sys.exit(0)
            
        print("[>] === Pre-flight Check Successful ===\n")

    def farm(self) -> list:
        if not self.active_team_indices:
            print("\n[*] SUCCESS: All configured teams have reached MAX level. Terminating gracefully.")
            # Normal completion, no respawn required
            sys.exit(0)

        # Determine which team to use based on mode
        if self.mode == "fifo":
            target_idx = self.active_team_indices[0]
        else: # rr
            self.current_rr_ptr = self.current_rr_ptr % len(self.active_team_indices)
            target_idx = self.active_team_indices[self.current_rr_ptr]

        team_id = self.teams[target_idx].get("TEAM_ID")
        print(f"    [EPA] Using Mode: {self.mode.upper()} | Active Echelon: {team_id}")
        
        drops, all_maxed = self._run_mission(target_idx)
        
        if drops is None:
            return None # Agent will abort and retry
            
        if all_maxed:
            print(f"    [*] Echelon {team_id} is fully maxed out! Removing from active pool.")
            self.active_team_indices.remove(target_idx)
            # In RR mode, if we remove current element, ptr naturally points to the next logical element
            # But we must boundary wrap it on the next loop
        else:
            if self.mode == "rr":
                self.current_rr_ptr += 1

        return drops

    def _check_battle_exp(self, resp_data: dict, team_config: dict, spot_id: int) -> bool:
        """Parses gun_exp. Returns True ONLY IF ALL deployed dolls in this echelon hit MAX level (0 EXP)."""
        gun_exp_list = resp_data.get("gun_exp", [])
        if not gun_exp_list:
            return False
            
        maxed_count = 0
        exp_details = []
        
        for item in gun_exp_list:
            gun_uid = str(item.get("gun_with_user_id", "unknown"))
            exp_val = str(item.get("exp", "0"))
            exp_details.append(f"{gun_uid[-4:]}: +{exp_val}")
            
            if exp_val == "0":
                maxed_count += 1
                
        print(f"    [+] Node {spot_id} EXP | {' | '.join(exp_details)}")
        
        target_count = len(team_config.get("GUNS", []))
        return maxed_count >= target_count and target_count > 0

    def _run_mission(self, team_idx: int) -> tuple[list, bool]:
        team_config = self.teams[team_idx]
        team_id = team_config.get("TEAM_ID")
        guns_config = team_config.get("GUNS", [])
        fairy_id = team_config.get("FAIRY_ID", 0)
        
        dropped_uids = []
        current_spots_state = {}
        all_maxed_flag = False

        def update_seeds(resp):
            if isinstance(resp, dict) and "spot_act_info" in resp:
                for s in resp["spot_act_info"]:
                    current_spots_state[str(s.get("spot_id"))] = int(s.get("seed", 0))

        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_COMBINFO, {"mission_id": self.mission_id}, "combInfo"), "combInfo"): 
            return None, False

        start_payload = {
            "mission_id": self.mission_id,
            "spots": [{"spot_id": self.start_spot, "team_id": team_id}],
            "squad_spots": [], "sangvis_spots": [], "vehicle_spots": [],
            "ally_spots": [], "mission_ally_spots": [],
            "ally_id": int(time.time())
        }
        
        start_resp = self.agent.safe_request(API_MISSION_START, start_payload, "startMission")
        if self.agent.check_step_error(start_resp, "startMission"): return None, False
        update_seeds(start_resp)

        curr_spot = self.start_spot
        for step, next_spot in enumerate(self.route, 1):
            move_payload = {
                "person_type": 1, "person_id": team_id,
                "from_spot_id": curr_spot, "to_spot_id": next_spot, "move_type": 1
            }
            move_resp = self.agent.safe_request(API_MISSION_TEAM_MOVE, move_payload, f"teamMove({curr_spot}->{next_spot})")
            if self.agent.check_step_error(move_resp, "teamMove"): return None, False
            update_seeds(move_resp)

            self.agent.safe_request(API_MISSION_COMBINFO, {"mission_id": self.mission_id}, "combInfoMid")

            seed = current_spots_state.get(str(next_spot), 0)
            current_mvp = next(self.mvp_gens[team_idx])
            
            fairy_dict = {}
            if fairy_id:
                fairy_dict = {str(fairy_id): {"9": 1, "68": 0}}

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
                "guns": guns_config,
                "user_rec": '{"seed":%d,"record":[]}' % seed,
                "1000": {"10": 18473, "11": 18473, "12": 18473, "13": 18473, "15": 27550, "16": 0, "17": 98, "33": 10017, "40": 50, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 25975, "25": 0, "26": 25975, "27": 4, "34": 63, "35": 63, "41": 519, "42": 0, "43": 0, "44": 0},
                "1001": {},
                "1002": {str(g["id"]): {"47": 0} for g in guns_config},
                "1003": fairy_dict,
                "1005": {}, "1007": {}, "1008": {}, "1009": {},
                "battle_damage": {},
                "micalog": {
                    "user_device": self.user_device,
                    "user_ip": ""
                }
            }

            battle_resp = self.agent.safe_request(API_MISSION_BATTLE_FINISH, battle_payload, f"battleFinish({next_spot})")
            if self.agent.check_step_error(battle_resp, "battleFinish"): return None, False
            
            # Record Battle Drops
            bg = battle_resp.get("battle_get_gun", [])
            for gun in bg:
                gun_uid = int(gun.get("gun_with_user_id"))
                dropped_uids.append(gun_uid)
                print(f"    [+] Node {next_spot} Drop! UID: {gun_uid}")
            
            # Check EXP (Logical AND for the whole echelon)
            if self._check_battle_exp(battle_resp, team_config, next_spot):
                all_maxed_flag = True

            curr_spot = next_spot
            time.sleep(0.5)

        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_END_TURN, {}, "endTurn"), "endTurn"): return None, False
        time.sleep(0.2)
        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_START_ENEMY_TURN, {}, "startEnemyTurn"), "startEnemyTurn"): return None, False
        time.sleep(0.2)
        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_END_ENEMY_TURN, {}, "endEnemyTurn"), "endEnemyTurn"): return None, False
        time.sleep(0.2)

        win_resp = self.agent.safe_request(API_MISSION_START_TURN, {}, "startTurn")
        if self.agent.check_step_error(win_resp, "startTurn"): return None, False
        
        dropped_uids.extend(self.agent.check_drop_result(win_resp))

        return dropped_uids, all_maxed_flag

class EPAFifoMission(BaseEPAMission):
    def __init__(self, agent):
        super().__init__(agent, mode="fifo")

class EPARRMission(BaseEPAMission):
    def __init__(self, agent):
        super().__init__(agent, mode="rr")