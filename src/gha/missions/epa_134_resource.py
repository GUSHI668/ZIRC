"""
13-4 双单人五战资源打捞任务
适用于 EN 服，梯队1和梯队2均为单人编队
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

# 13-4 五战路线
ROUTE = [91264, 91265, 91266, 91268, 91271]

# 13-4 战斗模板
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
        self.teams = []  # 梯队1和梯队2的枪娘列表，在prepare()中填充

    def prepare(self):
        """拉取Index数据并校验梯队1、2均为单人编队"""
        client = self.agent.client
        print("[*] 正在请求 Index/index …")
        resp = client.send_request(API_INDEX_INDEX,
                                   {"time": int(time.time()), "furniture_data": False})
        if "error" in resp or "error_local" in resp:
            raise RuntimeError("Index/index 请求失败，无法继续")

        # 解析所有梯队
        gun_list = resp.get("gun_with_user_info", [])
        team_map = {}
        for gun in gun_list:
            tid = gun.get("team_id", 0)
            if tid < 1 or tid > 14:
                continue
            team_map.setdefault(tid, {"team_id": tid, "guns": []})
            # 兼容两种枪娘ID字段
            gun_uid = gun.get("id") or gun.get("gun_with_user_id")
            team_map[tid]["guns"].append({
                "id": gun_uid,
                "life": gun.get("life", 100),
                "gun_id": gun.get("gun_id", 0),
            })

        # 检查必须的梯队
        for tid in (self.main_team_id, self.support_team_id):
            if tid not in team_map or len(team_map[tid]["guns"]) != 1:
                raise RuntimeError(f"梯队{tid} 必须为单人编队，当前不符合要求，请检查游戏内编队。")

        # 保存梯队信息
        self.teams = [
            {"team_id": self.main_team_id, "fairy_id": 0, "guns": team_map[self.main_team_id]["guns"]},
            {"team_id": self.support_team_id, "fairy_id": 0, "guns": team_map[self.support_team_id]["guns"]},
        ]
        print("[+] 梯队1、2校验通过，均为单人编队。")

    def farm(self) -> list:
        """执行一轮 Macro（多次战斗 + 拆解），返回本轮获得的枪娘UID列表"""
        client = self.agent.client
        batch_gun_uids = []
        mvp_iter = self._get_mvp_gen(self.teams[0]["guns"])

        for _ in range(self.missions_per_retire):
            dropped = self._run_mission(client, mvp_iter)
            if dropped is None:
                print("[-] 本轮战斗失败，放弃关卡并稍后重试…")
                client.send_request(API_MISSION_ABORT, {"mission_id": self.mission_id})
                time.sleep(3)
                continue
            batch_gun_uids.extend(dropped.get("guns", []))
            time.sleep(0.1)

        # 拆解所有本次获得的枪娘
        self._retire_guns(client, batch_gun_uids)
        return batch_gun_uids

    def _run_mission(self, client, mvp_gen):
        """单次 13-4 五战流程，返回 {'guns': [uid, ...]} 或 None"""
        current_spots_state = {}

        def update_seeds(resp):
            for s in resp.get("spot_act_info", []):
                current_spots_state[str(s["spot_id"])] = int(s["seed"])

        # 1. 获取战场信息
        if self._check_step_error(client.send_request(API_MISSION_COMBINFO,
                                                       {"mission_id": self.mission_id}),
                                  "combInfo"):
            return None

        # 2. 部署两个梯队
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

        # 3. 沿着路线移动并战斗
        for step, next_spot in enumerate(self.route, 1):
            # 3.1 移动
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
                "micalog": {"user_device": self.user_device, "user_ip": ""},
            }
            battle_resp = client.send_request(API_MISSION_BATTLE_FINISH, battle_payload)
            if self._check_step_error(battle_resp, f"battleFinish {next_spot}"):
                return None

            # 收集战斗中掉落的枪娘
            for gun in battle_resp.get("battle_get_gun", []):
                dropped_gun_uids.append(int(gun["gun_with_user_id"]))
            curr_spot = next_spot
            time.sleep(0.05)

        # 4. 结束回合并获取胜利奖励
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
        """拆解枪娘，并处理仓库满的情况"""
        if not gun_uids:
            return
        print(f"[*] 正在拆解 {len(gun_uids)} 名人形…")
        resp = client.send_request(API_GUN_RETIRE, gun_uids)
        if resp.get("success"):
            print("[+] 拆解成功")
        else:
            print(f"[-] 拆解失败，服务器返回：{resp}")
            # 如果因仓库满导致拆解失败，可以在 agent 层面统一处理停止逻辑

    @staticmethod
    def _check_step_error(resp, step_name):
        if "error_local" in resp:
            print(f"[-] {step_name} 本地错误: {resp['error_local']}")
            return True
        if "error" in resp:
            print(f"[-] {step_name} 服务器错误: {resp['error']}")
            return True
        return False

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