# src/gha/missions/epa_134_resource.py

"""
13-4 Dual Single-Doll (5 Battles) Resource Farming Mission
Applicable to EN server, echelon 1 and 2 must be single-doll formations.
"""

import time
from .base import BaseMission

from gflzirc import (
    API_MISSION_COMBINFO,
    API_MISSION_START,
    API_MISSION_TEAM_MOVE,
    API_MISSION_END_TURN,
    API_MISSION_START_ENEMY_TURN,
    API_MISSION_END_ENEMY_TURN,
    API_MISSION_START_TURN,
    API_MISSION_ABORT,
    API_MISSION_BATTLE_FINISH,
    API_INDEX_INDEX,
)

# 13-4 route (5 battles)
ROUTE = [91264, 91265, 91266, 91268, 91271]

# 13-4 battle templates (1000 block)
BATTLE_1000_BY_SPOT = {
    91266: {
        "10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 34199,
        "16": 0, "17": 192, "33": 11004, "40": 37, "18": 0, "19": 0,
        "20": 0, "21": 0, "22": 0, "23": 0, "24": 49907, "25": 0,
        "26": 49907, "27": 7, "34": 11, "35": 11, "41": 1348, "42": 0,
        "43": 0, "44": 0
    },
    91268: {
        "10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 32109,
        "16": 0, "17": 154, "33": 11005, "40": 30, "18": 0, "19": 0,
        "20": 0, "21": 0, "22": 0, "23": 0, "24": 45321, "25": 0,
        "26": 45321, "27": 3, "34": 19, "35": 19, "41": 1510, "42": 0,
        "43": 0, "44": 0
    },
    91271: {
        "10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 49202,
        "16": 0, "17": 182, "33": 11016, "40": 69, "18": 0, "19": 0,
        "20": 0, "21": 0, "22": 0, "23": 0, "24": 68135, "25": 0,
        "26": 68135, "27": 4, "34": 41, "35": 41, "41": 987, "42": 0,
        "43": 0, "44": 0
    },
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
        self.user_device = agent.user_device  # 直接使用 agent 提取好的设备指纹

        # 梯队数据会在 prepare() 后填充
        self.teams = []
        # MVP 生成器会在 prepare() 后初始化
        self.mvp_gen = None

    def prepare(self):
        """拉取 Index 数据并校验梯队 1、2 均为单人编队"""
        client = self.agent.client
        print("[*] Requesting Index/index ...")
        resp = self.agent.safe_request(API_INDEX_INDEX,
                                       {"time": int(time.time()), "furniture_data": False},
                                       "Index/index")
        if resp is None or self.agent.check_step_error(resp, "Index/index"):
            raise RuntimeError("Index/index request failed, cannot proceed")

        # 解析所有梯队
        gun_list = resp.get("gun_with_user_info", [])
        team_map = {}
        for gun in gun_list:
            # 梯队 ID 可能在 "team_id" 或 "team" 字段，统一尝试
            tid = gun.get("team_id") or gun.get("team")
            try:
                tid = int(tid)
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

        # 检查所需梯队是否均为单人
        for tid in (self.main_team_id, self.support_team_id):
            if tid not in team_map or len(team_map[tid]["guns"]) != 1:
                raise RuntimeError(
                    f"Echelon {tid} must be a single-doll formation. "
                    "Please check your in-game setup."
                )

        # 保存梯队信息（仅保存所需数据）
        self.teams = [
            {
                "team_id": self.main_team_id,
                "fairy_id": 0,
                "guns": team_map[self.main_team_id]["guns"]
            },
            {
                "team_id": self.support_team_id,
                "fairy_id": 0,
                "guns": team_map[self.support_team_id]["guns"]
            },
        ]

        # 创建 MVP 生成器（主梯队 1）
        self.mvp_gen = self._get_mvp_gen(self.teams[0]["guns"])

        print("[+] Echelon 1 and 2 validation passed: both are single-doll formations.")

    def farm(self) -> list:
        """
        执行一次 13‑4 五战资源打捞。
        返回本次获得的枪娘 UID 列表，拆解操作由 Agent 在 Macro 结束后统一完成。
        """
        if not self.teams or self.mvp_gen is None:
            print("[-] Mission not prepared, cannot farm.")
            return []

        # 执行单次五战流程
        drops = self._run_mission(self.mvp_gen)

        if drops is None:
            print("[-] Mission failed this run, aborting...")
            self.agent.safe_request(API_MISSION_ABORT, {"mission_id": self.mission_id}, "abortMission")
            # 返回空列表让 Agent 继续重试，而非直接返回 None 导致停止
            return []
        return drops

    # ---------- 内部实现 ----------
    def _run_mission(self, mvp_gen):
        """单次 13‑4 五战流程，返回获得的枪娘 UID 列表，失败返回 None"""
        current_spots_state = {}

        def update_seeds(resp):
            for s in resp.get("spot_act_info", []):
                current_spots_state[str(s.get("spot_id"))] = int(s.get("seed", 0))

        # 1. 获取战场信息
        resp = self.agent.safe_request(API_MISSION_COMBINFO,
                                       {"mission_id": self.mission_id},
                                       "combInfo")
        if resp is None or self.agent.check_step_error(resp, "combInfo"):
            return None

        # 2. 部署两个梯队
        start_spots = [
            {"spot_id": self.start_spot, "team_id": self.main_team_id},
            {"spot_id": self.support_start_spot, "team_id": self.support_team_id},
        ]
        start_payload = {
            "mission_id": self.mission_id,
            "spots": start_spots,
            "squad_spots": [],
            "sangvis_spots": [],
            "vehicle_spots": [],
            "ally_spots": [],
            "mission_ally_spots": [],
            "ally_id": int(time.time()),
        }
        start_resp = self.agent.safe_request(API_MISSION_START, start_payload, "startMission")
        if start_resp is None or self.agent.check_step_error(start_resp, "startMission"):
            return None
        update_seeds(start_resp)

        curr_spot = self.start_spot
        dropped_gun_uids = []

        # 3. 沿路线移动并战斗
        for step, next_spot in enumerate(self.route, 1):
            # 3.1 移动
            move_payload = {
                "person_type": 1,
                "person_id": self.main_team_id,
                "from_spot_id": curr_spot,
                "to_spot_id": next_spot,
                "move_type": 1,
            }
            move_resp = self.agent.safe_request(API_MISSION_TEAM_MOVE, move_payload,
                                                f"teamMove {curr_spot}->{next_spot}")
            if move_resp is None or self.agent.check_step_error(move_resp, "teamMove"):
                return None
            update_seeds(move_resp)

            # 更新战场信息以获取最新 seed
            comb_mid = self.agent.safe_request(API_MISSION_COMBINFO,
                                               {"mission_id": self.mission_id},
                                               "combInfoMid")
            if comb_mid is None:
                print("[-] combInfoMid failed, but may continue")

            seed = current_spots_state.get(str(next_spot), 0)

            # 3.2 战斗
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
                "micalog": {
                    "user_device": self.user_device,
                    "user_ip": "",
                },
            }

            battle_resp = self.agent.safe_request(API_MISSION_BATTLE_FINISH, battle_payload,
                                                  f"battleFinish {next_spot}")
            if battle_resp is None or self.agent.check_step_error(battle_resp, "battleFinish"):
                return None

            # 收集战斗中掉落的枪
            for gun in battle_resp.get("battle_get_gun", []):
                try:
                    dropped_gun_uids.append(int(gun["gun_with_user_id"]))
                except (ValueError, KeyError):
                    pass

            curr_spot = next_spot
            time.sleep(0.05)

        # 4. 结束回合并获取胜利奖励
        end_turn = self.agent.safe_request(API_MISSION_END_TURN, {}, "endTurn")
        if end_turn is None or self.agent.check_step_error(end_turn, "endTurn"):
            return None

        time.sleep(0.01)
        self.agent.safe_request(API_MISSION_START_ENEMY_TURN, {}, "startEnemyTurn")
        time.sleep(0.01)
        self.agent.safe_request(API_MISSION_END_ENEMY_TURN, {}, "endEnemyTurn")
        time.sleep(0.01)

        win_resp = self.agent.safe_request(API_MISSION_START_TURN, {}, "startTurn")
        if win_resp is None or self.agent.check_step_error(win_resp, "startTurn"):
            return None

        # 收集胜利奖励中的枪
        for gun in win_resp.get("mission_win_result", {}).get("reward_gun", []):
            try:
                dropped_gun_uids.append(int(gun["gun_with_user_id"]))
            except (ValueError, KeyError):
                pass

        return dropped_gun_uids

    @staticmethod
    def _build_1002(guns):
        """构造 1002 字段（战斗结算数据）"""
        if len(guns) == 1:
            return {str(guns[0]["id"]): {"47": 1}}
        return {str(g["id"]): {"47": 0} for g in guns}

    @staticmethod
    def _get_mvp_gen(guns):
        """MVP 轮流分配生成器"""
        idx = 0
        while True:
            yield guns[idx % len(guns)]["id"]
            idx = (idx + 1) % len(guns)