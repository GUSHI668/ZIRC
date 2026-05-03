# src/gha/missions/pick_and_train.py

import time
import json
import sys
from .base import BaseMission

from gflzirc import (
    API_MISSION_COMBINFO, API_MISSION_START, API_INDEX_GUIDE,
    API_MISSION_TEAM_MOVE, API_MISSION_ABORT, API_GUN_SKILL_UPGRADE,
    GUIDE_COURSE_10352
)

from request import IndexRequest
from parser import CoinParser, SkillTrainParser

class PickAndTrainMission(BaseMission):
    def __init__(self, agent):
        super().__init__(agent)
        self.mission_id = 10352
        self.train_queue = []

    def get_mission_id(self) -> int:
        return self.mission_id

    def prepare(self):
        print("\n[>] === Pre-flight Check: Validating Echelon & Building Train Queue ===")
        team_id = int(self.config.get("TEAM_ID", 1))
        
        index_data = IndexRequest(self.agent).fetch()
        if not index_data:
            print("[-] FATAL: Failed to fetch Index data during prepare().")
            sys.exit(1)
            
        # 1. Validate Echelon for 10352
        guns = index_data.get("gun_with_user_info", [])
        if not isinstance(guns, list): guns = []
        team_guns = [g for g in guns if int(g.get("team_id", 0)) == team_id]
        
        if len(team_guns) != 1:
            print(f"[-] FATAL: Mission 10352 requires EXACTLY 1 doll in Team {team_id}.")
            sys.exit(1)
            
        print(f"[+] Echelon validation passed. Team {team_id} is ready.")
        
        # 2. Build the Training Queue
        self.train_queue = SkillTrainParser().parse(index_data)
        print("[>] === Pre-flight Check Successful ===\n")

    def farm(self) -> list:
        team_id = self.config.get("TEAM_ID", 1)

        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_COMBINFO, {"mission_id": self.mission_id}, "combInfo"), "combInfo"): return None
        
        start_payload = {
            "mission_id": self.mission_id, 
            "spots": [{"spot_id": 13280, "team_id": team_id}],
            "squad_spots": [], "sangvis_spots": [], "vehicle_spots": [], 
            "ally_spots": [], "mission_ally_spots": [],
            "ally_id": int(time.time())
        }
        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_START, start_payload, "startMission"), "startMission"): return None
        if self.agent.check_step_error(self.agent.safe_request(API_INDEX_GUIDE, {"guide": json.dumps({"course": GUIDE_COURSE_10352}, separators=(',', ':'))}, "guide"), "guide"): return None
        time.sleep(0.2)

        move1_payload = {
            "person_type": 1, "person_id": team_id,
            "from_spot_id": 13280, "to_spot_id": 13277, "move_type": 1
        }
        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_TEAM_MOVE, move1_payload, "teamMove1"), "teamMove1"): return None
        time.sleep(0.2)

        move2_payload = {
            "person_type": 1, "person_id": team_id,
            "from_spot_id": 13277, "to_spot_id": 13278, "move_type": 1
        }
        move2_resp = self.agent.safe_request(API_MISSION_TEAM_MOVE, move2_payload, "teamMove2")
        if self.agent.check_step_error(move2_resp, "teamMove2"): return None
        
        # Extract coin2 amount
        coin2_amount = CoinParser().parse(move2_resp)
        self.agent.parse_random_node_drop(move2_resp)
        
        time.sleep(0.2)
        self.agent.safe_request(API_MISSION_ABORT, {"mission_id": self.mission_id}, "missionAbort", max_retries=1)
        time.sleep(0.5)
        
        # Trigger Auto Train if coin2 reached cap (+0 detected)
        if coin2_amount is not None and coin2_amount <= 0:
            print("[!] Medium Training Data (coin2) cap reached (+0 detected). Triggering Skill Upgrade.")
            self._train_skill()
        
        return []

    def _train_skill(self):
        if not self.train_queue:
            print("[*] Training queue is empty. Skipping auto train.")
            return

        # Pop the first candidate from the queue
        cand = self.train_queue.pop(0)
        # Default to max
        target_lv = 10

        print(f"[>] Training UID: {cand['gun_uid']} | Skill: {cand['skill_no']} | Lv.{cand['current_lv']} -> Lv.{target_lv} ...")
        
        payload = {
            "skill": cand["skill_no"],
            "if_quick": 1,
            "gun_with_user_id": cand["gun_uid"],
            "upgrade_slot": 1,
            "to_level": target_lv
        }
        
        # Attempt to upgrade directly to level 10. 
        # Using max_retries=1 because a failure almost certainly means insufficient resources or busy status.
        resp = self.agent.safe_request(API_GUN_SKILL_UPGRADE, payload, "skillUpgrade", max_retries=1)
        
        if self.agent.check_step_error(resp, "skillUpgrade"):
            print("[-] Skill upgrade to Lv.10 failed (likely insufficient resources or doll busy). Candidate discarded.")
            return
        print("[+] Skill upgraded to Lv.10 successfully!")