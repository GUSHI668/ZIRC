"""
13-4 Dual Single-Doll (5 Battles) Resource Farming Mission
Applicable to EN server, echelon 1 and 2 must be single-doll formations.
"""
import time
from gflzirc import (
    API_MISSION_COMBINFO,
    API_MISSION_START,
    API_MISSION_TEAM_MOVE,
    API_MISSION_END_TURN,
    API_MISSION_START_ENEMY_TURN,
    API_MISSION_END_ENEMY_TURN,
    API_MISSION_START_TURN,
    API_MISSION_ABORT,
    API_GUN_RETIRE,
    API_MISSION_BATTLE_FINISH,
    API_INDEX_INDEX,
)
from .base import BaseMission

# 13-4 route (5 battles)
ROUTE = [91264, 91265, 91266, 91268, 91271]

# 13-4 battle templates
BATTLE_1000_BY_SPOT = {
    91266: {"10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 34199, "16": 0, "17": 192,
            "33": 11004, "40": 37, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0,
            "24": 49907, "25": 0, "26": 49907, "27": 7, "34": 11, "35": 11, "41": 1348,
            "42": 0, "43": 0, "44": 0},
    91268: {"10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 32109, "16": 0, "17": 154,
            "33": 11005, "40": 30, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0,
            "24": 45321, "25": 0, "26": 45321, "27": 3, "34": 19, "35": 19, "41": 1510,
            "42": 0, "43": 0, "44": 0},
    91271: {"10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 49202, "16": 0, "17": 182,
            "33": 11016, "40": 69, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0,
            "24": 68135, "25": 0, "26": 68135, "27": 4, "34": 41, "35": 41, "41": 987,
            "42": 0, "43": 0, "44": 0},
}


class EPA134ResourceMission(BaseMission):
    def __init__(self, agent):
        super().__init__(agent)
        self.mission_id = 128
        self.start_spot = 91263
        self.support_start_spot = 91297
        self.main_team_id = 1
        self.support_team_id = 2
        self.route = list(ROUTE)
        self.user_device = self.agent.config.get("USER_DEVICE", "1145141919810")
        self.missions_per_retire = self.agent.config.get("EPA_PER_RETIRE", 8)
        self.teams = []  # will be filled in prepare()

    def prepare(self):
        """Fetch Index data and validate that echelon 1 and 2 are single-doll."""
        client = self.agent.client
        print("[*] Requesting Index/index ...")
        resp = client.send_request(API_INDEX_INDEX,
                                   {"time": int(time.time()), "furniture_data": False})
        if "error" in resp or "error_local" in resp:
            raise RuntimeError("Index/index request failed, cannot proceed")

        # parse all echelons
        gun_list = resp.get("gun_with_user_info", [])
        team_map = {}
        for gun in gun_list:
            try:
                tid = int(gun.get("team_id", 0))
            except (ValueError, TypeError):
                continue
            if tid < 1 or tid > 14:
                continue
            team_map.setdefault(tid, {"team_id": tid, "guns": []})
            gun_uid = gun.get("id") or gun.get("gun_with_user_id")
            try:
                gun_uid = int(gun_uid)
            except (ValueError, TypeError):
                continue
            team_map[tid]["guns"].append({
                "id": gun_uid,
                "life": int(gun.get("life", 100)),
                "gun_id": int(gun.get("gun_id", 0)),
            })

        # validate required echelons
        for tid in (self.main_team_id, self.support_team_id):
            if tid not in team_map or len(team_map[tid]["guns"]) != 1:
                raise RuntimeError(f"Echelon {tid} must be a single-doll formation. Please check your in-game setup.")

        self.teams = [
            {"team_id": self.main_team_id, "fairy_id": 0, "guns": team_map[self.main_team_id]["guns"]},
            {"team_id": self.support_team_id, "fairy_id": 0, "guns": team_map[self.support_team_id]["guns"]},
        ]
        print("[+] Echelon 1 and 2 validation passed: both are single-doll formations.")

    def farm(self) -> list:
        """Execute one Macro (multiple battles + retire), return list of obtained gun UIDs."""
        client = self.agent.client
        batch_gun_uids = []
        mvp_iter = self._get_mvp_gen(self.teams[0]["guns"])

        for _ in range(self.missions_per_retire):
            dropped = self._run_mission(client, mvp_iter)
            if dropped is None:
                print("[-] Mission failed this run, aborting and retrying ...")
                client.send_request(API_MISSION_ABORT, {"mission_id": self.mission_id})
                time.sleep(3)
                continue
            batch_gun_uids.extend(dropped.get("guns", []))
            time.sleep(0.1)

        # retire all obtained guns
        self._retire_guns(client, batch_gun_uids)
        return batch_gun_uids

    def _run_mission(self, client, mvp_gen):
        """Single 13-4 five-battle run, returns {'guns': [uid, ...]} or None."""
        current_spots_state = {}

        def update_seeds(resp):
            for s in resp.get("spot_act_info", []):
                current_spots_state[str(s["spot_id"])] = int(s["seed"])

        # 1. get battlefield info
        if self._check_step_error(client.send_request(API_MISSION_COMBINFO,
                                                       {"mission_id": self.mission_id}),
                                  "combInfo"):
            return None

        # 2. deploy both echelons
        start_spots = [
            {"spot_id": self.start_spot, "team_id": self.main_team_id},
            {"spot_id": self.support_start_spot, "team_id": self.support_team_id},
        ]
        start_resp = client.send_request(API_MISSION_START, {
            "mission_id": self.mission_id,
            "spots": start_spots,
            "squad_spots": [],
            "sangvis_spots": [],
            "vehicle_spots": [],
            "ally_spots": [],
            "mission_ally_spots": [],
            "ally_id": int(time.time()),
        })
        if self._check_step_error(start_resp, "startMission"):
            return None
        update_seeds(start_resp)

        curr_spot = self.start_spot
        dropped_gun_uids = []

        # 3. move and battle along the route
        for step, next_spot in enumerate(self.route, 1):
            # 3.1 move
            move_resp = client.send_request(API_MISSION_TEAM_MOVE, {
                "person_type": 1,
                "person_id": self.main_team_id,
                "from_spot_id": curr_spot,
                "to_spot_id": next_spot,
                "move_type": 1,
            })
            if self._check_step_error(move_resp, f"teamMove {curr_spot}->{next_spot}"):
                return None
            update_seeds(move_resp)
            client.send_request(API_MISSION_COMBINFO, {"mission_id": self.mission_id})
            seed = current_spots_state.get(str(next_spot), 0)

            # 3.2 battle
            mvp = next(mvp_gen)
            fairy_dict = {}
            battle_payload = {
                "spot_id": next_spot,
                "if_enemy_die": True,
                "current_time": int(time.time()),
                "boss_hp": 0,
                "mvp": mvp,
                "last_battle_info": "",
                "use_skill_squads": [],
                "use_skill_ally_spots": [],
                "use_skill_vehicle_spots": [],
                "guns": [{"id": g["id"], "life": g["life"]} for g in self.teams[0]["guns"]],
                "user_rec": f'{{"seed":{seed},"record":[]}}',
                "1000": BATTLE_1000_BY_SPOT.get(next_spot, {}),
                "1001": {},
                "1002": self._build_1002(self.teams[0]["guns"]),
                "1003": fairy_dict,
                "1005": {},
                "1007": {},
                "1008": {},
                "1009": {},
                "battle_damage": {},
                "micalog": {"user_device": self.user_device, "user_ip": ""},
            }
            battle_resp = client.send_request(API_MISSION_BATTLE_FINISH, battle_payload)
            if self._check_step_error(battle_resp, f"battleFinish {next_spot}"):
                return None

            # collect drops during battle
            for gun in battle_resp.get("battle_get_gun", []):
                dropped_gun_uids.append(int(gun["gun_with_user_id"]))
            curr_spot = next_spot
            time.sleep(0.05)

        # 4. end turn and get victory rewards
        end_turn_resp = client.send_request(API_MISSION_END_TURN, {})
        if self._check_step_error(end_turn_resp, "endTurn"):
            return None

        time.sleep(0.01)
        client.send_request(API_MISSION_START_ENEMY_TURN, {})
        time.sleep(0.01)
        client.send_request(API_MISSION_END_ENEMY_TURN, {})
        time.sleep(0.01)
        win_resp = client.send_request(API_MISSION_START_TURN, {})
        if self._check_step_error(win_resp, "startTurn"):
            return None

        for gun in win_resp.get("mission_win_result", {}).get("reward_gun", []):
            dropped_gun_uids.append(int(gun["gun_with_user_id"]))

        return {"guns": dropped_gun_uids}

    def _retire_guns(self, client, gun_uids):
        """Retire obtained guns and handle full inventory."""
        if not gun_uids:
            return
        print(f"[*] Retiring {len(gun_uids)} dolls ...")
        resp = client.send_request(API_GUN_RETIRE, gun_uids)
        if resp.get("success"):
            print("[+] Retirement successful")
        else:
            print(f"[-] Retirement failed, server response: {resp}")
            # Full inventory handling can be managed at the agent level

    @staticmethod
    def _check_step_error(resp, step_name):
        if "error_local" in resp:
            print(f"[-] {step_name} local error: {resp['error_local']}")
            return True
        if "error" in resp:
            print(f"[-] {step_name} server error: {resp['error']}")
            return True
        return False

    @staticmethod
    def _build_1002(guns):
        """Build the 1002 field (battle settlement data)."""
        if len(guns) == 1:
            return {str(guns[0]["id"]): {"47": 1}}
        return {str(g["id"]): {"47": 0} for g in guns}

    @staticmethod
    def _get_mvp_gen(guns):
        """Rotating MVP generator."""
        idx = 0
        while True:
            yield guns[idx % len(guns)]["id"]
            idx = (idx + 1) % len(guns)