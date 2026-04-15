# src/gha/missions/f2p_pr.py

import time
from .base import BaseMission

from gflzirc import (
    API_MISSION_COMBINFO, API_MISSION_START,
    API_MISSION_TEAM_MOVE, API_MISSION_ALLY_MYSIDE_MOVE,
    API_MISSION_END_TURN, API_MISSION_START_ENEMY_TURN,
    API_MISSION_END_ENEMY_TURN, API_MISSION_START_TURN
)

class F2PPRMission(BaseMission):
    def __init__(self, agent):
        super().__init__(agent)
        self.mission_id = 10801

    def get_mission_id(self) -> int:
        return self.mission_id

    def _move_ally(self, from_spot: int, to_spot: int, step_name: str):
        """Helper to construct ally movement payloads"""
        payload = {
            "person_type": 3,
            "person_id": 1,
            "from_spot_id": from_spot,
            "to_spot_id": to_spot,
            "move_type": 1
        }
        return self.agent.safe_request(API_MISSION_TEAM_MOVE, payload, step_name)

    def farm(self) -> list:
        # 1. Init Mission
        if self.agent.check_step_error(
            self.agent.safe_request(API_MISSION_COMBINFO, {"mission_id": self.mission_id}, "combinationInfo"), 
            "combinationInfo"
        ): 
            return None
        
        # 2. Start Mission with System Echelon (Ally)
        start_payload = {
            "mission_id": self.mission_id,
            "spots": [],
            "squad_spots": [],
            "sangvis_spots": [],
            "vehicle_spots": [],
            "ally_spots": [],
            "mission_ally_spots": [
                {
                    "spot_id": 64318,
                    "ally_team_id": 6480101,
                    "mission_myside_data": {
                        "sangvis": [],
                        "gun": {
                            "1": {"position": 8}
                        }
                    }
                }
            ],
            "ally_id": int(time.time())
        }
        
        if self.agent.check_step_error(
            self.agent.safe_request(API_MISSION_START, start_payload, "startMission"), 
            "startMission"
        ): 
            return None
        
        time.sleep(0.5)

        # 3. Turn 1 Actions
        if self.agent.check_step_error(self._move_ally(64318, 64307, "teamMove_1"), "teamMove1"): return None
        time.sleep(0.2)
        
        if self.agent.check_step_error(self._move_ally(64307, 64308, "teamMove_2"), "teamMove2"): return None
        time.sleep(0.2)
        
        if self.agent.check_step_error(
            self.agent.safe_request(API_MISSION_ALLY_MYSIDE_MOVE, {}, "allyMySideMove"), 
            "allyMySideMove"
        ): 
            return None
        time.sleep(0.2)
        
        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_END_TURN, {}, "endTurn"), "endTurn"): return None
        time.sleep(0.2)
        
        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_START_ENEMY_TURN, {}, "startEnemyTurn"), "startEnemyTurn"): return None
        time.sleep(0.2)
        
        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_END_ENEMY_TURN, {}, "endEnemyTurn"), "endEnemyTurn"): return None
        time.sleep(0.2)
        
        if self.agent.check_step_error(self.agent.safe_request(API_MISSION_START_TURN, {}, "startTurn"), "startTurn"): return None
        time.sleep(0.5)
        
        # 4. Turn 2 Actions
        if self.agent.check_step_error(self._move_ally(64308, 64302, "teamMove_3"), "teamMove3"): return None
        time.sleep(0.2)
        
        # Final move triggers mission complete
        final_resp = self._move_ally(64302, 64319, "teamMove_Final")
        if self.agent.check_step_error(final_resp, "teamMoveFinal"): return None
        
        # 5. Extract drops from the final win response
        return self.agent.check_drop_result(final_resp)