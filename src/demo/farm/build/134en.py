import sys
import re
import time
import threading
import copy
import json
import os
from gflzirc import (
    GFLClient, GFLProxy, set_windows_proxy,
    SERVERS, STATIC_KEY, DEFAULT_SIGN,
    API_MISSION_COMBINFO, API_MISSION_START,
    API_MISSION_TEAM_MOVE, API_MISSION_END_TURN,
    API_MISSION_START_ENEMY_TURN, API_MISSION_END_ENEMY_TURN,
    API_MISSION_START_TURN, API_MISSION_ABORT, API_GUN_RETIRE,
    API_MISSION_BATTLE_FINISH,
)

try:
    from gflzirc import API_INDEX_INDEX
except ImportError:
    API_INDEX_INDEX = "Index/index"

# EN 服务器兜底配置
EN_FALLBACK_BASE_URL = SERVERS.get("EN") or SERVERS.get("M4A1")
if "EN" not in SERVERS and EN_FALLBACK_BASE_URL:
    SERVERS["EN"] = EN_FALLBACK_BASE_URL

# ================= 13-4 练级与资源打捞配置 =================
TRAIN_STAGE_13_4 = {
    "difficulty": "练级",
    "stage": "13-4",
    "label": "13-4 五战练级",
    "mission_id": 128,
    "start_spot": 91263,
    "dummy_start_spot": 91297,
    "dummy_team_id": 1,
    "first_train_team_id": 2,
    "route": [91264, 91265, 91266, 91268, 91271],
}

RESOURCE_STAGE_13_4 = {
    "difficulty": "资源",
    "stage": "13-4",
    "label": "13-4 双单人五战四项基础资源打捞",
    "mission_id": 128,
    "start_spot": 91263,
    "support_start_spot": 91297,
    "route": [91264, 91265, 91266, 91268, 91271],
    "main_team_id": 1,
    "support_team_id": 2,
}

BASIC_RESOURCE_KEYS = ("mp", "ammo", "mre", "part")
BASIC_RESOURCE_LABELS = {
    "mp": "人力",
    "ammo": "弹药",
    "mre": "口粮",
    "part": "零件",
}

CONFIG = {
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "SERVER_NAME": "EN",
    "BASE_URL": SERVERS.get("EN", EN_FALLBACK_BASE_URL),
    "PROXY_PORT": 12335,
    "MACRO_LOOPS": 200,
    "MISSIONS_PER_RETIRE": 8,
    "MISSION_ID": 128,
    "START_SPOT": 91263,
    "ROUTE": [91264, 91265, 91266, 91268, 91271],
    "SELECTED_DIFFICULTY": None,
    "SELECTED_STAGE": None,
    "SELECTED_TARGET": None,
    "SELECTED_TARGET_LABEL": None,
    "SELECTED_BATTLE_TEMPLATE": None,
    "SINGLE_GUN_MODE": False,
    "MODE_SELECTED_EARLY": False,
    "MODE_NAME": "team",
    "RESOURCE_FARM_MODE": False,
    "TRAIN_13_4_MODE": False,
    "TRAIN_13_4_DUMMY_TEAM_ID": 1,
    "TRAIN_13_4_FIRST_TEAM_ID": 2,
    "TRAIN_13_4_DUMMY_START_SPOT": 91297,
    "RESOURCE_13_4_MAIN_TEAM_ID": 1,
    "RESOURCE_13_4_SUPPORT_TEAM_ID": 2,
    "RESOURCE_13_4_SUPPORT_START_SPOT": 91297,
    "RESOURCE_13_4_START_INVENTORY": {},
    "RESOURCE_13_4_END_INVENTORY": {},
    "TRAIN_TEAM_COUNT": 1,
    "TRAIN_SCHEDULE_MODE": "full",
    "CURRENT_TRAIN_TEAM_INDEX": 0,
    "STOP_ON_MAX_LEVEL": False,
    "STOP_AFTER_EACH_TARGET_DROPPED": False,
    "AUTO_MONITOR_MODE": False,
    "AUTO_CAPTURE_EXPECTED_COUNT": 1,
    "INDEX_FETCH_READY": False,
    "PROTECTED_DROP_GUN_IDS": [],
    "STOP_AFTER_RETIRE_NO_SPACE_TIMES": 2,
    "ENABLE_FILTER_PROTECTION": True,
    "USER_DEVICE": "1145141919810",
    "TEAM_ID": 1,
    "FAIRY_ID": 159357,
    "FAIRY": None,
    "GUNS": [],
}

# 13-4 战斗模板
TRAIN_13_4_BATTLE_1000_BY_SPOT = {
    91266: {"10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 34199, "16": 0, "17": 192, "33": 11004, "40": 37, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 49907, "25": 0, "26": 49907, "27": 7, "34": 11, "35": 11, "41": 1348, "42": 0, "43": 0, "44": 0},
    91268: {"10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 32109, "16": 0, "17": 154, "33": 11005, "40": 30, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 45321, "25": 0, "26": 45321, "27": 3, "34": 19, "35": 19, "41": 1510, "42": 0, "43": 0, "44": 0},
    91271: {"10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 49202, "16": 0, "17": 182, "33": 11016, "40": 69, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 68135, "25": 0, "26": 68135, "27": 4, "34": 41, "35": 41, "41": 987, "42": 0, "43": 0, "44": 0},
}

# ================= 全局状态 =================
MENU_STATE = {
    "selection_unlocked": False,
    "awaiting_stop_on_max": False,
    "awaiting_run_confirm": False,
    "awaiting_filter_protection": False,
}

current_worker_thread = None
worker_mode = None
proxy_instance = None
stop_macro_flag = False
stop_micro_flag = False

AUTO_CAPTURE_STATE = {"team_id": None, "fairy_id": None, "guns": [], "completed": False}
CAPTURED_TEAM_CONFIGS = []
TEAM_SWITCH_PENDING = False
TRAIN_COMPLETED_TEAM_INDICES = set()
DROPPED_UID_TO_GUN_ID = {}
RETIRE_NO_SPACE_COUNT = 0

RUN_STATS = {
    "start_time": None, "end_time": None, "target_counts": {},
    "current_macro": 0, "current_micro": 0, "current_step": 0,
    "current_team_no": 1, "macro_drop_names": [], "last_micro_exp_lines": [],
    "panel_enabled": True, "recent_logs": [],
    "resource_start_inventory": {}, "resource_end_inventory": {},
    "resource_gained": {}, "resource_efficiency_per_hour": {},
    "completed_resource_runs": 0,
}

TEAM_PROGRESS_STATE = {"current_active_team_id": None, "current_active_started_at": None}

GUN_CATALOG_CACHE = None
GUN_NAME_ALIAS = {
    "格洛克17": "Glock17", "56式半": "56-1", "谢尔久科夫": "Serdyukov",
    "S-SASS": "SSGSSASS", "芭莉斯塔": "Ballista", "59式": "59type",
    "雷电": "Thunder", "蜜獾": "HoneyBadger", "Cx4 风暴": "Cx4Storm",
    "八一式马": "Type81R", "蟒蛇": "Python", "猎豹M1": "Gepard M1",
    "62式": "Type62", "刘易斯": "Lewis", "03式": "Type03",
    "马盖尔": "Magal", "沙漠之鹰": "Desert Eagle", "侦察者": "Scout",
    "隼": "Falcon", "防卫者": "Defender", "蒙德拉贡M1908": "Mondragon M1908",
    "高标10型": "General Liu", "卢萨": "Lusa", "英萨斯": "INSAS",
    "刘氏步枪": "Liu", "德林加": "Derringer", "菲德洛夫": "Fedorov",
    "沙维奇99型": "Savage99", "芮诺": "Reno", "斯特林": "Sterling",
    "韦伯利": "Webley", "DP-12": "DP12", "CPS-12": "Six12",
    "CF05": "CF-05", "FN-57": "Five-seveN", "AK 5": "Ak 5",
    "AUG SMG": "AUG Para", "TF-Q": "TF Q", "6P62": "6P62",
    "STG-940": "StG-940",
}
GUN_ID_OVERRIDE = {
    "6P62": 138, "Ak 5": 187, "AK 5": 187, "雷电": 202, "SCW": 169,
    "DP-12": 282, "DP12": 282, "CPS-12": 278, "Six12": 278,
    "德林加": 332, "Derringer": 332, "StG-940": 314, "STG-940": 314,
    "StG940": 314, "03式": 239, "Type03": 239, "猎豹M1": 201, "Gepard M1": 201,
}

# ================= 辅助函数 =================
def load_gun_catalog():
    global GUN_CATALOG_CACHE
    if GUN_CATALOG_CACHE is not None:
        return GUN_CATALOG_CACHE
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = ["gun.json", "gun1(1).json", "gun1.json"]
    for name in candidates:
        fp = os.path.join(script_dir, name)
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    GUN_CATALOG_CACHE = json.load(f)
                    return GUN_CATALOG_CACHE
            except Exception:
                pass
    GUN_CATALOG_CACHE = []
    return GUN_CATALOG_CACHE

def normalize_gun_name(name: str) -> str:
    if not name:
        return ""
    return str(name).lower().replace(" ", "").replace("-", "").replace(".", "")

def resolve_gun_id_by_name(name: str):
    candidates = [name]
    alias = GUN_NAME_ALIAS.get(name)
    if alias:
        candidates.append(alias)
    for cand in candidates:
        if cand in GUN_ID_OVERRIDE:
            return int(GUN_ID_OVERRIDE[cand])
    catalog = load_gun_catalog()
    if not catalog:
        return None
    for cand in candidates:
        n = normalize_gun_name(cand)
        for gun in catalog:
            for field in ("en_name", "code", "name"):
                if n == normalize_gun_name(gun.get(field, "")):
                    return int(gun["id"])
    return None

def get_selected_protected_gun_ids():
    if not CONFIG.get("ENABLE_FILTER_PROTECTION", True):
        return set()
    protected_ids = set(CONFIG.get("PROTECTED_DROP_GUN_IDS", []))
    label = CONFIG.get("SELECTED_TARGET_LABEL")
    if label:
        for name in label.split("&"):
            gun_id = resolve_gun_id_by_name(name.strip())
            if gun_id:
                protected_ids.add(gun_id)
    return protected_ids

def is_no_space_retire_failure(resp):
    text = str(resp).lower()
    keywords = ["full", "space", "capacity", "inventory", "仓库", "满", "空间", "容量", "上限", "空位"]
    return any(k in text for k in keywords)

def get_basic_resource_inventory_from_index_payload(payload):
    user_info = payload.get("user_info", {}) if isinstance(payload, dict) else {}
    return {k: int(user_info.get(k, 0)) for k in BASIC_RESOURCE_KEYS}

def format_resource_inventory(inv):
    if not inv:
        return "未记录"
    return " / ".join(f"{BASIC_RESOURCE_LABELS.get(k,k)} {inv.get(k,0)}" for k in BASIC_RESOURCE_KEYS)

def check_step_error(resp, step_name):
    if "error_local" in resp:
        print(f"[-] {step_name} 本地错误: {resp['error_local']}")
        return True
    if "error" in resp:
        print(f"[-] {step_name} 服务器错误: {resp['error']}")
        return True
    return False

def split_target_label(label):
    return [part.strip() for part in str(label).split("&") if part.strip()]

def record_target_drop(item_id, drop_type="gun"):
    try:
        item_id = int(item_id)
    except Exception:
        return
    if RUN_STATS.get("target_type") != drop_type:
        return
    for name, item in RUN_STATS["target_counts"].items():
        if item["item_id"] == item_id:
            item["count"] += 1
            break

def get_target_drop_progress_text():
    if not RUN_STATS.get("target_counts"):
        return "未配置"
    return "，".join(f"{name}×{item['count']}" for name, item in RUN_STATS["target_counts"].items())

def has_each_target_dropped_once():
    if not RUN_STATS.get("target_counts"):
        return False
    return all(item["count"] >= 1 for item in RUN_STATS["target_counts"].values())

def should_stop_after_each_target_dropped():
    if not CONFIG.get("STOP_AFTER_EACH_TARGET_DROPPED"):
        return False
    if CONFIG.get("MODE_NAME") != "single":
        return False
    return has_each_target_dropped_once()

def get_terminal_width(default=120):
    try:
        import shutil
        return max(60, shutil.get_terminal_size(fallback=(default, 30)).columns)
    except Exception:
        return default

def strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", str(text))

def trim_ansi_line(text, max_width):
    s = str(text)
    plain = strip_ansi(s)
    if len(plain) <= max_width:
        return s
    keep = max(10, max_width - 3)
    return plain[:keep] + "..."

def colorize(text, color_key=None):
    ANSI = {
        "reset": "\033[0m", "panel_border": "\033[96m", "panel_label": "\033[97m",
        "target": "\033[93m", "success": "\033[92m", "warn": "\033[91m", "dim": "\033[90m",
    }
    if not color_key or color_key not in ANSI:
        return str(text)
    return ANSI[color_key] + str(text) + ANSI["reset"]

def format_duration(seconds):
    seconds = int(max(0, seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h: return f"{h}小时{m}分{s}秒"
    if m: return f"{m}分{s}秒"
    return f"{s}秒"

def format_percent(value):
    return f"{float(value):.2f}%"

def get_gun_id_name_map():
    mapping = {}
    catalog = load_gun_catalog()
    if catalog:
        for gun in catalog:
            try:
                gid = int(gun.get("id"))
                name = gun.get("en_name") or gun.get("code") or gun.get("name") or str(gid)
                mapping[gid] = str(name)
            except Exception:
                pass
    return mapping

def resolve_gun_name_by_id(gun_id):
    try:
        gun_id = int(gun_id)
    except Exception:
        return str(gun_id)
    return get_gun_id_name_map().get(gun_id, str(gun_id))

def is_target_gun_name(name):
    try:
        drop_id = resolve_gun_id_by_name(name)
    except Exception:
        drop_id = None
    target_ids = set()
    for item in RUN_STATS.get("target_counts", {}).values():
        target_ids.add(item.get("item_id"))
    if drop_id is not None and drop_id in target_ids:
        return True
    n = normalize_gun_name(name)
    for target in split_target_label(CONFIG.get("SELECTED_TARGET_LABEL", "")):
        if n == normalize_gun_name(target):
            return True
        alias = GUN_NAME_ALIAS.get(target)
        if alias and n == normalize_gun_name(alias):
            return True
    return False

def format_drop_name_for_display(name):
    if is_target_gun_name(name):
        return colorize(name, "target")
    return str(name)

def build_drop_marquee_segment(items, visible_width):
    if not items:
        return "无"
    parts = [format_drop_name_for_display(x) for x in items]
    plain_parts = [strip_ansi(x) for x in parts]
    joined_plain = "   ".join(plain_parts)
    if len(joined_plain) <= visible_width:
        return "   ".join(parts)
    shown = []
    used = 0
    for part in parts:
        plain = strip_ansi(part)
        sep = "   " if shown else ""
        if used + len(sep) + len(plain) > visible_width:
            break
        if sep:
            shown.append(sep)
            used += len(sep)
        shown.append(part)
        used += len(plain)
    if not shown:
        return trim_ansi_line(parts[0], visible_width)
    return "".join(shown)

def is_13_4_training_stage():
    return CONFIG.get("MISSION_ID") == 128 and CONFIG.get("START_SPOT") == 91263

def is_13_4_resource_farm_stage():
    return CONFIG.get("RESOURCE_FARM_MODE") and CONFIG.get("MISSION_ID") == 128

def get_current_team_config():
    if CAPTURED_TEAM_CONFIGS:
        if CONFIG.get("MODE_NAME") == "team":
            idx = CONFIG.get("CURRENT_TRAIN_TEAM_INDEX", 0)
            idx = max(0, min(idx, len(CAPTURED_TEAM_CONFIGS)-1))
            return CAPTURED_TEAM_CONFIGS[idx]
        return CAPTURED_TEAM_CONFIGS[0]
    return {"team_id": CONFIG["TEAM_ID"], "fairy_id": CONFIG["FAIRY_ID"], "fairy": CONFIG.get("FAIRY"), "guns": CONFIG["GUNS"]}

def get_current_team_id():
    return get_current_team_config()["team_id"]

def get_current_fairy_id():
    return get_current_team_config()["fairy_id"]

def get_team_config_by_team_id(team_id):
    for cfg in CAPTURED_TEAM_CONFIGS:
        if int(cfg.get("team_id",0)) == int(team_id):
            return cfg
    return None

def get_13_4_training_dummy_team_id():
    return int(CONFIG.get("TRAIN_13_4_DUMMY_TEAM_ID", 1))

def get_13_4_training_dummy_start_spot():
    return int(CONFIG.get("TRAIN_13_4_DUMMY_START_SPOT", 91297))

def is_13_4_training_independent_mode():
    return CONFIG.get("TRAIN_13_4_MODE") and is_13_4_training_stage()

def get_active_guns():
    if is_13_4_resource_farm_stage():
        team_cfg = get_team_config_by_team_id(CONFIG.get("RESOURCE_13_4_MAIN_TEAM_ID",1))
        if not team_cfg:
            team_cfg = get_current_team_config()
        return list(team_cfg.get("guns", []))
    guns = get_current_team_config()["guns"]
    if CONFIG.get("SINGLE_GUN_MODE"):
        idx = CONFIG.get("SINGLE_GUN_INDEX",0)
        if 0 <= idx < len(guns):
            return [guns[idx]]
        return []
    return guns

def build_battle_guns():
    return [{"id": g["id"], "life": g["life"]} for g in get_active_guns()]

def build_battle_1002():
    result = {}
    guns = get_active_guns()
    if len(guns) == 1:
        result[str(guns[0]["id"])] = {"47": 1}
    else:
        for gun in guns:
            result[str(gun["id"])] = {"47": 0}
    return result

def get_mvp_generator():
    idx = 0
    while True:
        guns = get_active_guns()
        if not guns:
            yield 0
            continue
        yield guns[idx % len(guns)]["id"]
        idx = (idx + 1) % len(guns)

def check_battle_drop(resp_data, spot_id):
    collected = []
    for gun in resp_data.get("battle_get_gun", []):
        gun_id = int(gun["gun_id"])
        gun_uid = int(gun["gun_with_user_id"])
        DROPPED_UID_TO_GUN_ID[gun_uid] = gun_id
        record_target_drop(gun_id, "gun")
        RUN_STATS["macro_drop_names"].append(resolve_gun_name_by_id(gun_id))
        collected.append(gun_uid)
    return collected

def check_battle_equip_drop(resp_data, spot_id):
    collected = []
    for equip in resp_data.get("battle_get_equip", []):
        equip_id = int(equip["equip_id"])
        equip_uid = int(equip["id"])
        record_target_drop(equip_id, "equip")
        collected.append({"equip_id": equip_id, "equip_uid": equip_uid})
    return collected

def check_win_drop(resp_data):
    collected = []
    for gun in resp_data.get("mission_win_result", {}).get("reward_gun", []):
        gun_id = int(gun["gun_id"])
        gun_uid = int(gun["gun_with_user_id"])
        DROPPED_UID_TO_GUN_ID[gun_uid] = gun_id
        record_target_drop(gun_id, "gun")
        RUN_STATS["macro_drop_names"].append(resolve_gun_name_by_id(gun_id))
        collected.append(gun_uid)
    return collected

def check_win_equip_drop(resp_data):
    collected = []
    for equip in resp_data.get("mission_win_result", {}).get("reward_equip", []):
        equip_id = int(equip["equip_id"])
        equip_uid = int(equip["id"])
        record_target_drop(equip_id, "equip")
        collected.append({"equip_id": equip_id, "equip_uid": equip_uid})
    return collected

def build_runtime_panel_lines():
    if not RUN_STATS.get("panel_enabled", True):
        return []
    term_width = get_terminal_width(120)
    inner_width = max(40, term_width-2)
    if is_13_4_resource_farm_stage():
        mode_label = "13-4双单人资源打捞"
    else:
        mode_label = "练级五人模式" if CONFIG.get("MODE_NAME") == "team" else "打捞单人模式"
    stage_label = f"{CONFIG.get('SELECTED_DIFFICULTY') or '-'} {CONFIG.get('SELECTED_STAGE') or '-'} -> {CONFIG.get('SELECTED_TARGET_LABEL') or '-'}"
    elapsed = 0
    if RUN_STATS.get("start_time"):
        elapsed = time.time() - RUN_STATS["start_time"]
    drop_text = "无"
    if RUN_STATS.get("macro_drop_names"):
        drop_text = build_drop_marquee_segment(RUN_STATS["macro_drop_names"], max(20, inner_width-12))
    exp_text = " | ".join(RUN_STATS.get("last_micro_exp_lines", [])) or "无"
    member_pct = 0
    fairy_pct = 0
    team_runtime = 0
    eta_text = "-"
    eta_clock = "-"
    if CONFIG.get("MODE_NAME") == "team":
        team_label = f"{CONFIG.get('CURRENT_TRAIN_TEAM_INDEX',0)+1} / {max(1,len(CAPTURED_TEAM_CONFIGS))}"
        macro_text = f"当前 MACRO：{RUN_STATS.get('current_macro',0)} / 直到全部梯队满级"
    elif is_13_4_resource_farm_stage():
        team_label = "梯队1+梯队2（移动梯队1）"
        macro_text = f"当前 MACRO：{RUN_STATS.get('current_macro',0)} / 直到手动停止"
    else:
        team_label = "1"
        macro_text = f"当前 MACRO：{RUN_STATS.get('current_macro',0)} / 直到手动停止"
    lines = [
        colorize("============= EN 13-4 运行状态 =============", "panel_border"),
        f"{colorize('服务器：','panel_label')}{CONFIG.get('SERVER_NAME','SOP')}    {colorize('模式：','panel_label')}{mode_label}",
        f"{colorize('关卡：','panel_label')}{stage_label}",
        f"{colorize('当前梯队：','panel_label')}{team_label}",
        colorize(macro_text, "panel_label"),
        f"{colorize('当前 MICRO：','panel_label')}{RUN_STATS.get('current_micro',0)} / {CONFIG.get('MISSIONS_PER_RETIRE',8)} | {colorize('当前 Step：','panel_label')}{RUN_STATS.get('current_step',0)} / {len(CONFIG.get('ROUTE',[]))}",
        f"{colorize('本轮掉落：','panel_label')}{drop_text}",
        f"{colorize('目标统计：','panel_label')}{get_target_drop_progress_text()}",
        f"{colorize('最近一轮经验：','panel_label')}{exp_text}",
        f"{colorize('人形进度：','panel_label')}{format_percent(member_pct)}",
        f"{colorize('妖精进度：','panel_label')}{format_percent(fairy_pct)}",
        f"{colorize('本梯队已运行：','panel_label')}{format_duration(team_runtime)}",
        f"{colorize('预计完成：','panel_label')}{eta_text} 后（{eta_clock}）",
        f"{colorize('总运行时间：','panel_label')}{format_duration(elapsed)}",
        colorize("停止：-q 当前 Macro 后停 / -Q 当前 Micro 后停", "dim"),
        colorize("=" * min(inner_width, 37), "panel_border"),
    ]
    return [trim_ansi_line(line, inner_width) for line in lines]

def clear_runtime_panel():
    try:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    except Exception:
        os.system("cls" if os.name == "nt" else "clear")

def refresh_runtime_panel():
    lines = build_runtime_panel_lines()
    if not lines:
        return
    clear_runtime_panel()
    recent_logs = RUN_STATS.get("recent_logs", [])[-22:]
    if recent_logs:
        for line in recent_logs:
            print(line)
        print()
    for line in lines:
        print(line)

def panel_safe_print(*args, **kwargs):
    if not RUN_STATS.get("panel_enabled", True):
        print(*args, **kwargs)
        return
    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\n")
    msg = sep.join(str(a) for a in args)
    if end != "\n":
        msg = msg + end
    lines = msg.splitlines() or [msg]
    buf = RUN_STATS.setdefault("recent_logs", [])
    buf.extend(lines)
    if len(buf) > 10:
        RUN_STATS["recent_logs"] = buf[-10:]

def print_exit_summary():
    if RUN_STATS.get("start_time") is None:
        print("[*] 尚未运行，无统计数据。")
        return
    duration = time.time() - RUN_STATS["start_time"]
    print("\n=========== 本次运行统计 ===========")
    print(f"运行总时长：{format_duration(duration)}")
    hours = duration / 3600 if duration > 0 else 0.001

    if is_13_4_resource_farm_stage():
        start_inv = CONFIG.get("RESOURCE_13_4_START_INVENTORY", {})
        end_inv = RUN_STATS.get("resource_end_inventory") or CONFIG.get("RESOURCE_13_4_END_INVENTORY", {})
        if end_inv:
            gained = {k: end_inv.get(k, 0) - start_inv.get(k, 0) for k in BASIC_RESOURCE_KEYS}
            print("13-4 四项基础资源统计：")
            print(f"  起始库存：{format_resource_inventory(start_inv)}")
            print(f"  结束库存：{format_resource_inventory(end_inv)}")
            print(f"  本次获得：{format_resource_inventory(gained)}")
            eff = {k: int(gained[k] / hours) for k in BASIC_RESOURCE_KEYS}
            print(f"  每小时效率：{format_resource_inventory(eff)}")
        else:
            print("  资源收益：未记录结束库存（可能未完整运行）。")
        print(f"  完成轮数：{RUN_STATS.get('completed_resource_runs', 0)}")
    else:
        total_drops = 0
        if RUN_STATS.get("target_counts"):
            for item in RUN_STATS["target_counts"].values():
                total_drops += item.get("count", 0)
            print("目标人形掉落统计：")
            for name, item in RUN_STATS["target_counts"].items():
                print(f"  {name}：{item['count']}")
            if hours > 0:
                print(f"  每小时平均掉落：{total_drops / hours:.2f} 个")
        else:
            print("未配置目标或尚无掉落。")
        completed_macros = max(0, RUN_STATS.get("current_macro", 0) - 1)
        print(f"  完成轮次（Macro）：{completed_macros}")
    print("================================\n")

def print_main_menu():
    print("\n================= EN 13-4 专用菜单 =================")
    print(" -a        : 抓 UID/SIGN；再次 -a 请求 Index/index 并解析编队")
    print(" -134train : 预选 13-4 五战练级（梯队1单人占位，从梯队2开始）")
    print(" -134      : 预选 13-4 五战四项基础资源打捞（梯队1+梯队2双单人）")
    print(" -r        : 按当前 13-4 配置开始运行")
    print(" -q        : 当前 Macro 结束后安全停止")
    print(" -Q        : 当前 Micro 结束后安全停止")
    print(" -s        : 仅停止代理")
    print(" -E        : 退出程序")
    print("====================================================\n")

def apply_13_4_resource_farm_config():
    CONFIG["MODE_NAME"] = "resource134"
    CONFIG["SINGLE_GUN_MODE"] = False
    CONFIG["RESOURCE_FARM_MODE"] = True
    CONFIG["TRAIN_13_4_MODE"] = False
    CONFIG["SELECTED_DIFFICULTY"] = RESOURCE_STAGE_13_4["difficulty"]
    CONFIG["SELECTED_STAGE"] = RESOURCE_STAGE_13_4["stage"]
    CONFIG["SELECTED_TARGET"] = "13-4-resource"
    CONFIG["SELECTED_TARGET_LABEL"] = RESOURCE_STAGE_13_4["label"]
    CONFIG["MISSION_ID"] = RESOURCE_STAGE_13_4["mission_id"]
    CONFIG["START_SPOT"] = RESOURCE_STAGE_13_4["start_spot"]
    CONFIG["RESOURCE_13_4_SUPPORT_START_SPOT"] = RESOURCE_STAGE_13_4["support_start_spot"]
    CONFIG["RESOURCE_13_4_MAIN_TEAM_ID"] = RESOURCE_STAGE_13_4["main_team_id"]
    CONFIG["RESOURCE_13_4_SUPPORT_TEAM_ID"] = RESOURCE_STAGE_13_4["support_team_id"]
    CONFIG["ROUTE"] = list(RESOURCE_STAGE_13_4["route"])
    CONFIG["ENABLE_FILTER_PROTECTION"] = False
    CONFIG["PROTECTED_DROP_GUN_IDS"] = []

def apply_13_4_training_config():
    CONFIG["MODE_NAME"] = "team"
    CONFIG["SINGLE_GUN_MODE"] = False
    CONFIG["RESOURCE_FARM_MODE"] = False
    CONFIG["TRAIN_13_4_MODE"] = True
    CONFIG["SELECTED_DIFFICULTY"] = TRAIN_STAGE_13_4["difficulty"]
    CONFIG["SELECTED_STAGE"] = TRAIN_STAGE_13_4["stage"]
    CONFIG["SELECTED_TARGET"] = "13-4"
    CONFIG["SELECTED_TARGET_LABEL"] = TRAIN_STAGE_13_4["label"]
    CONFIG["MISSION_ID"] = TRAIN_STAGE_13_4["mission_id"]
    CONFIG["START_SPOT"] = TRAIN_STAGE_13_4["start_spot"]
    CONFIG["TRAIN_13_4_DUMMY_START_SPOT"] = TRAIN_STAGE_13_4.get("dummy_start_spot", 91297)
    CONFIG["TRAIN_13_4_DUMMY_TEAM_ID"] = TRAIN_STAGE_13_4.get("dummy_team_id", 1)
    CONFIG["TRAIN_13_4_FIRST_TEAM_ID"] = TRAIN_STAGE_13_4.get("first_train_team_id", 2)
    CONFIG["ROUTE"] = list(TRAIN_STAGE_13_4["route"])
    CONFIG["ENABLE_FILTER_PROTECTION"] = False
    CONFIG["PROTECTED_DROP_GUN_IDS"] = []

def preset_resource134_mode():
    apply_13_4_resource_farm_config()
    CONFIG["MODE_SELECTED_EARLY"] = True
    CONFIG["TRAIN_TEAM_COUNT"] = 2
    CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 2
    CAPTURED_TEAM_CONFIGS.clear()
    print("[*] 已预选 13-4 双单人五战资源打捞模式。")
    print("[*] 现在请输入 -a，程序会保留该模式并进入服务器选择 / UID-SIGN 抓取流程。")

def preset_train134_mode():
    apply_13_4_training_config()
    CONFIG["MODE_SELECTED_EARLY"] = True
    CONFIG["TRAIN_TEAM_COUNT"] = 1
    CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 2
    CAPTURED_TEAM_CONFIGS.clear()
    print("[*] 已预选 13-4 五战练级模式。")
    print("[*] 现在请输入 -a，程序会保留该模式并进入服务器选择 / UID-SIGN 抓取流程。")

def reset_selection_menu():
    MENU_STATE["awaiting_stop_on_max"] = False
    MENU_STATE["awaiting_run_confirm"] = False
    MENU_STATE["awaiting_filter_protection"] = False

def reopen_stage_selection_menu():
    MENU_STATE["selection_unlocked"] = True
    reset_selection_menu()
    print_main_menu()
    print("\n当前仅支持 13-4 练级或资源打捞，请使用 -134train 或 -134 预选模式后再执行 -a。")

def stop_proxy_instance():
    global proxy_instance, worker_mode
    if proxy_instance:
        proxy_instance.stop()
        set_windows_proxy(False)
        proxy_instance = None
    worker_mode = None

def reset_captured_team_configs():
    CAPTURED_TEAM_CONFIGS.clear()
    CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = 0

def init_team_progress_runtime_fields(team_cfg):
    for gun in team_cfg.get("guns", []):
        gun.setdefault("runtime_gained_exp", 0)
    team_cfg.setdefault("runtime_seconds", 0.0)
    team_cfg.setdefault("completed", False)
    team_cfg.setdefault("maxed_member_uids", set())

def initialize_all_team_progress():
    for team_cfg in CAPTURED_TEAM_CONFIGS:
        init_team_progress_runtime_fields(team_cfg)

def activate_team_runtime(team_id):
    TEAM_PROGRESS_STATE["current_active_team_id"] = team_id
    TEAM_PROGRESS_STATE["current_active_started_at"] = time.time()

def pause_current_team_runtime():
    team_id = TEAM_PROGRESS_STATE.get("current_active_team_id")
    started = TEAM_PROGRESS_STATE.get("current_active_started_at")
    if team_id and started:
        cfg = get_team_config_by_team_id(team_id)
        if cfg:
            cfg["runtime_seconds"] = cfg.get("runtime_seconds",0) + (time.time() - started)
        TEAM_PROGRESS_STATE["current_active_started_at"] = None
        TEAM_PROGRESS_STATE["current_active_team_id"] = None

def reset_training_progress():
    TRAIN_COMPLETED_TEAM_INDICES.clear()
    CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = 0
    TEAM_PROGRESS_STATE["current_active_team_id"] = None
    TEAM_PROGRESS_STATE["current_active_started_at"] = None
    for team_cfg in CAPTURED_TEAM_CONFIGS:
        team_cfg["runtime_seconds"] = 0.0
        team_cfg["completed"] = False
        team_cfg["maxed_member_uids"] = set()

def advance_to_next_training_team():
    global TEAM_SWITCH_PENDING
    if CONFIG.get("MODE_NAME") != "team":
        return
    switch_to_next_available_training_team("当前练级梯队已全部满级")

def get_active_training_team_indices():
    return [i for i in range(len(CAPTURED_TEAM_CONFIGS)) if i not in TRAIN_COMPLETED_TEAM_INDICES]

def switch_to_next_available_training_team(reason=""):
    global TEAM_SWITCH_PENDING, stop_macro_flag, stop_micro_flag
    if CONFIG.get("MODE_NAME") != "team":
        return
    pause_current_team_runtime()
    active = get_active_training_team_indices()
    if not active:
        stop_macro_flag = True
        stop_micro_flag = True
        panel_safe_print(colorize("[全部完成] 所有梯队已满级，程序停止。", "success"))
        return
    current_idx = CONFIG.get("CURRENT_TRAIN_TEAM_INDEX",0)
    if current_idx not in active:
        CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = active[0]
        TEAM_SWITCH_PENDING = False
        activate_team_runtime(CAPTURED_TEAM_CONFIGS[CONFIG["CURRENT_TRAIN_TEAM_INDEX"]]["team_id"])
        if reason:
            panel_safe_print(f"[梯队切换] {reason}，当前梯队：{CONFIG['CURRENT_TRAIN_TEAM_INDEX']+1}/{len(CAPTURED_TEAM_CONFIGS)}")
        return
    pos = active.index(current_idx)
    next_idx = active[(pos+1)%len(active)]
    CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = next_idx
    TEAM_SWITCH_PENDING = False
    activate_team_runtime(CAPTURED_TEAM_CONFIGS[next_idx]["team_id"])
    if reason:
        panel_safe_print(f"[梯队切换] {reason}，当前梯队：{next_idx+1}/{len(CAPTURED_TEAM_CONFIGS)}")

def build_team_configs_from_index(payload):
    if not isinstance(payload, dict):
        return []
    gun_list = payload.get("gun_with_user_info", [])
    team_map = {}
    for gun in gun_list:
        if not isinstance(gun, dict):
            continue
        team_id = int(gun.get("team_id", 0))
        if team_id < 1 or team_id > 14:
            continue
        gun_uid = gun.get("id") or gun.get("gun_with_user_id")
        gun_type_id = gun.get("gun_id", 0)
        life = gun.get("life")
        try:
            gun_uid = int(gun_uid)
            gun_type_id = int(gun_type_id or 0)
            life = int(life)
        except Exception:
            continue
        team_map.setdefault(team_id, {"team_id": team_id, "fairy_id": 0, "guns": []})
        team_map[team_id]["guns"].append({
            "id": gun_uid, "gun_id": gun_type_id, "life": life,
            "level": int(gun.get("level",1)), "exp": int(gun.get("exp",0)),
            "team_id": team_id,
        })
    teams = []
    for team_id in sorted(team_map.keys()):
        if team_map[team_id]["guns"]:
            teams.append(team_map[team_id])
    return teams

def try_update_auto_capture_from_index_payload(payload):
    if not isinstance(payload, dict):
        return False
    teams = build_team_configs_from_index(payload)
    if not teams:
        return False
    reset_captured_team_configs()
    mode = CONFIG.get("MODE_NAME")
    if mode == "resource134":
        required_ids = [int(CONFIG.get("RESOURCE_13_4_MAIN_TEAM_ID",1)), int(CONFIG.get("RESOURCE_13_4_SUPPORT_TEAM_ID",2))]
        team_by_id = {t["team_id"]: t for t in teams}
        missing = [tid for tid in required_ids if tid not in team_by_id]
        invalid = [tid for tid in required_ids if tid in team_by_id and len(team_by_id[tid]["guns"]) != 1]
        if missing or invalid:
            print("[AUTO] 13-4 资源打捞梯队校验失败：要求梯队1、梯队2均为单人编队。")
            return False
        for tid in required_ids:
            cfg = team_by_id[tid]
            CAPTURED_TEAM_CONFIGS.append({
                "team_id": cfg["team_id"], "fairy_id": cfg.get("fairy_id",0),
                "fairy": None, "guns": copy.deepcopy(cfg["guns"]),
                "runtime_seconds": 0, "completed": False,
            })
        CONFIG["TEAM_ID"] = CAPTURED_TEAM_CONFIGS[0]["team_id"]
        CONFIG["GUNS"] = copy.deepcopy(CAPTURED_TEAM_CONFIGS[0]["guns"])
    elif mode == "team" and CONFIG.get("TRAIN_13_4_MODE"):
        dummy_id = int(CONFIG.get("TRAIN_13_4_DUMMY_TEAM_ID",1))
        first_train = int(CONFIG.get("TRAIN_13_4_FIRST_TEAM_ID",2))
        expected = max(1, min(9, CONFIG.get("TRAIN_TEAM_COUNT",1)))
        train_ids = list(range(first_train, first_train+expected))
        team_by_id = {t["team_id"]: t for t in teams}
        if dummy_id not in team_by_id:
            print("[AUTO] 未找到梯队1占位队，请确保梯队1为单人编队。")
            return False
        if not all(tid in team_by_id for tid in train_ids):
            print("[AUTO] 缺少练级梯队，请确保梯队2起连续配置了实际练级队。")
            return False
        for tid in train_ids:
            cfg = team_by_id[tid]
            CAPTURED_TEAM_CONFIGS.append({
                "team_id": cfg["team_id"], "fairy_id": cfg.get("fairy_id",0),
                "fairy": None, "guns": copy.deepcopy(cfg["guns"]),
                "runtime_seconds": 0, "completed": False,
            })
        CONFIG["TEAM_ID"] = CAPTURED_TEAM_CONFIGS[0]["team_id"]
        CONFIG["GUNS"] = copy.deepcopy(CAPTURED_TEAM_CONFIGS[0]["guns"])
    else:
        first = teams[0]
        CAPTURED_TEAM_CONFIGS.append({
            "team_id": first["team_id"], "fairy_id": first.get("fairy_id",0),
            "fairy": None, "guns": copy.deepcopy(first["guns"]),
            "runtime_seconds": 0, "completed": False,
        })
        CONFIG["TEAM_ID"] = first["team_id"]
        CONFIG["GUNS"] = copy.deepcopy(first["guns"])
    CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = len(CAPTURED_TEAM_CONFIGS)
    return True

def request_index_and_prepare_configs():
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] 请先运行 -a 抓取 UID/SIGN。")
        return False
    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    print("[*] 请求 Index/index ...")
    resp = client.send_request(API_INDEX_INDEX, {"time": int(time.time()), "furniture_data": False})
    if not isinstance(resp, dict) or "error" in resp or "error_local" in resp:
        print("[-] Index/index 请求失败")
        return False

    try:
        with open("index_debug.json", "w", encoding="utf-8") as f:
            json.dump(resp, f, indent=4, ensure_ascii=False)
        print("[*] 已保存 Index/index 响应到 index_debug.json")
    except Exception as e:
        print(f"[!] 保存 index_debug.json 失败: {e}")

    if is_13_4_resource_farm_stage():
        inv = get_basic_resource_inventory_from_index_payload(resp)
        CONFIG["RESOURCE_13_4_START_INVENTORY"] = inv
        print(f"[资源统计] 起始库存：{format_resource_inventory(inv)}")
    if not try_update_auto_capture_from_index_payload(resp):
        print("[!] 解析梯队失败，请检查编队配置。")
        return False
    MENU_STATE["selection_unlocked"] = True
    reset_selection_menu()
    print_main_menu()
    print("\n[*] 已加载梯队配置。")
    return True

def farm_mission_epa(client, team_id, mvp_gen):
    global stop_macro_flag, stop_micro_flag, TEAM_SWITCH_PENDING
    mission_id = CONFIG["MISSION_ID"]
    start_spot = CONFIG["START_SPOT"]
    route = CONFIG["ROUTE"]
    dropped_uids = []
    dropped_equip_uids = []
    current_spots_state = {}
    def update_seeds(resp):
        if isinstance(resp, dict) and "spot_act_info" in resp:
            for s in resp["spot_act_info"]:
                current_spots_state[str(s["spot_id"])] = int(s["seed"])
    if check_step_error(client.send_request(API_MISSION_COMBINFO, {"mission_id": mission_id}), "combInfo"):
        return None
    if is_13_4_resource_farm_stage():
        main_id = int(CONFIG.get("RESOURCE_13_4_MAIN_TEAM_ID",1))
        support_id = int(CONFIG.get("RESOURCE_13_4_SUPPORT_TEAM_ID",2))
        team_id = main_id
        start_spots = [
            {"spot_id": int(CONFIG.get("START_SPOT",91263)), "team_id": main_id},
            {"spot_id": int(CONFIG.get("RESOURCE_13_4_SUPPORT_START_SPOT",91297)), "team_id": support_id},
        ]
    elif is_13_4_training_independent_mode():
        dummy_team_id = get_13_4_training_dummy_team_id()
        start_spots = [
            {"spot_id": int(CONFIG.get("START_SPOT",91263)), "team_id": int(team_id)},
            {"spot_id": get_13_4_training_dummy_start_spot(), "team_id": dummy_team_id},
        ]
    else:
        start_spots = [{"spot_id": start_spot, "team_id": team_id}]
    start_resp = client.send_request(API_MISSION_START, {"mission_id": mission_id, "spots": start_spots, "squad_spots": [], "sangvis_spots": [], "vehicle_spots": [], "ally_spots": [], "mission_ally_spots": [], "ally_id": int(time.time())})
    if check_step_error(start_resp, "startMission"):
        return None
    update_seeds(start_resp)
    curr_spot = start_spot
    for step, next_spot in enumerate(route, 1):
        RUN_STATS["current_step"] = step
        move_resp = client.send_request(API_MISSION_TEAM_MOVE, {
            "person_type": 1, "person_id": team_id,
            "from_spot_id": curr_spot, "to_spot_id": next_spot, "move_type": 1
        })
        if check_step_error(move_resp, f"teamMove({curr_spot}->{next_spot})"):
            return None
        update_seeds(move_resp)
        client.send_request(API_MISSION_COMBINFO, {"mission_id": mission_id})
        seed = current_spots_state.get(str(next_spot), 0)
        current_mvp = next(mvp_gen)
        fairy_dict = {}
        current_fairy_id = get_current_fairy_id()
        if current_fairy_id:
            fairy_dict[str(current_fairy_id)] = {"9": 1, "68": 0}
        battle_payload = {
            "spot_id": next_spot, "if_enemy_die": True, "current_time": int(time.time()),
            "boss_hp": 0, "mvp": current_mvp, "last_battle_info": "",
            "use_skill_squads": [], "use_skill_ally_spots": [], "use_skill_vehicle_spots": [],
            "guns": build_battle_guns(),
            "user_rec": f'{{"seed":{seed},"record":[]}}',
            "1000": TRAIN_13_4_BATTLE_1000_BY_SPOT.get(int(next_spot), {"10":18473,"11":18473,"12":18473,"13":18473,"15":27550,"16":0,"17":98,"33":10017,"40":50,"18":0,"19":0,"20":0,"21":0,"22":0,"23":0,"24":25975,"25":0,"26":25975,"27":4,"34":63,"35":63,"41":519,"42":0,"43":0,"44":0}),
            "1001": {}, "1002": build_battle_1002(), "1003": fairy_dict,
            "1005": {}, "1007": {}, "1008": {}, "1009": {},
            "battle_damage": {},
            "micalog": {"user_device": CONFIG["USER_DEVICE"], "user_ip": ""}
        }
        battle_resp = client.send_request(API_MISSION_BATTLE_FINISH, battle_payload)
        if check_step_error(battle_resp, f"battleFinish({next_spot})"):
            return None
        dropped_uids.extend(check_battle_drop(battle_resp, next_spot))
        dropped_equip_uids.extend([x["equip_uid"] for x in check_battle_equip_drop(battle_resp, next_spot)])
        curr_spot = next_spot
        time.sleep(0.05)
    end_turn_resp = client.send_request(API_MISSION_END_TURN, {})
    if check_step_error(end_turn_resp, "endTurn"):
        return None
    if is_13_4_training_stage():
        dropped_uids.extend(check_win_drop(end_turn_resp))
        dropped_equip_uids.extend([x["equip_uid"] for x in check_win_equip_drop(end_turn_resp)])
        return {"guns": dropped_uids, "equips": dropped_equip_uids}
    time.sleep(0.01)
    if check_step_error(client.send_request(API_MISSION_START_ENEMY_TURN, {}), "startEnemyTurn"):
        return None
    time.sleep(0.01)
    if check_step_error(client.send_request(API_MISSION_END_ENEMY_TURN, {}), "endEnemyTurn"):
        return None
    time.sleep(0.01)
    win_resp = client.send_request(API_MISSION_START_TURN, {})
    if check_step_error(win_resp, "startTurn"):
        return None
    dropped_uids.extend(check_win_drop(win_resp))
    dropped_equip_uids.extend([x["equip_uid"] for x in check_win_equip_drop(win_resp)])
    return {"guns": dropped_uids, "equips": dropped_equip_uids}

def retire_guns(client, gun_uids):
    global stop_macro_flag, stop_micro_flag, RETIRE_NO_SPACE_COUNT
    if not gun_uids:
        return
    protected = get_selected_protected_gun_ids()
    filtered = []
    for uid in gun_uids:
        gid = DROPPED_UID_TO_GUN_ID.get(uid)
        if gid in protected:
            print(f"[*] 保留受保护掉落 gun_id={gid}")
            continue
        filtered.append(uid)
    if not filtered:
        print("[*] 无需要拆解的人形")
        return
    print(f"[*] 拆解 {len(filtered)} 名人形...")
    resp = client.send_request(API_GUN_RETIRE, filtered)
    if resp.get("success"):
        RETIRE_NO_SPACE_COUNT = 0
        print("[+] 拆解成功")
    else:
        print(f"[-] 拆解失败: {resp}")
        if is_no_space_retire_failure(resp):
            RETIRE_NO_SPACE_COUNT += 1
            if RETIRE_NO_SPACE_COUNT >= CONFIG.get("STOP_AFTER_RETIRE_NO_SPACE_TIMES", 2):
                stop_macro_flag = True
                stop_micro_flag = True
                print("[!] 多次拆解失败（仓库满），自动停止。")
        else:
            RETIRE_NO_SPACE_COUNT = 0
    for uid in filtered:
        DROPPED_UID_TO_GUN_ID.pop(uid, None)

def farm_worker():
    global stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread, TEAM_SWITCH_PENDING
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] 请先通过 -a 获取 UID/SIGN。")
        worker_mode = None
        return
    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    mvp_gen = get_mvp_generator()
    RUN_STATS["start_time"] = time.time()
    RUN_STATS["target_counts"] = {}
    RUN_STATS["macro_drop_names"] = []
    RUN_STATS["last_micro_exp_lines"] = []
    RUN_STATS["current_macro"] = 0
    RUN_STATS["current_micro"] = 0
    RUN_STATS["panel_enabled"] = True
    RUN_STATS["recent_logs"] = []
    initialize_all_team_progress()
    if CONFIG.get("MODE_NAME") == "team":
        print(f"[*] 练级模式已启用，共 {len(CAPTURED_TEAM_CONFIGS)} 个梯队参与轮转。")
        reset_training_progress()
        if CAPTURED_TEAM_CONFIGS:
            activate_team_runtime(CAPTURED_TEAM_CONFIGS[0]["team_id"])
    else:
        print("[*] 资源打捞模式已启用。")
        activate_team_runtime(get_current_team_id())
    panel_safe_print(colorize("[*] 开始运行...", "success"))
    macro = 1
    while not stop_macro_flag:
        panel_safe_print(f"=== MACRO {macro} ===")
        RUN_STATS["current_macro"] = macro
        RUN_STATS["macro_drop_names"] = []
        RUN_STATS["last_micro_exp_lines"] = []
        batch_guns = []
        for micro in range(1, CONFIG["MISSIONS_PER_RETIRE"]+1):
            if stop_micro_flag or stop_macro_flag:
                break
            RUN_STATS["current_micro"] = micro
            RUN_STATS["current_step"] = 0
            dropped = farm_mission_epa(client, get_current_team_id(), mvp_gen)
            if dropped is None:
                print("[-] 本轮失败，放弃关卡...")
                client.send_request(API_MISSION_ABORT, {"mission_id": CONFIG["MISSION_ID"]})
                time.sleep(3)
                continue
            refresh_runtime_panel()
            if is_13_4_resource_farm_stage():
                RUN_STATS["completed_resource_runs"] += 1
            if should_stop_after_each_target_dropped():
                stop_macro_flag = True
                stop_micro_flag = True
                panel_safe_print(colorize(f"[目标达成] {get_target_drop_progress_text()}，停止。", "success"))
                break
            batch_guns.extend(dropped.get("guns", []))
            time.sleep(0.1)
            if CONFIG.get("MODE_NAME") == "team" and TEAM_SWITCH_PENDING:
                advance_to_next_training_team()
                break
            if CONFIG.get("MODE_NAME") == "team" and CONFIG.get("TRAIN_SCHEDULE_MODE") == "equal":
                switch_to_next_available_training_team("当前梯队已练级一轮")
                break
        retire_guns(client, batch_guns)
        if stop_micro_flag:
            break
        macro += 1
    RUN_STATS["end_time"] = time.time()
    panel_safe_print(colorize("\n[*] 运行结束。", "success"))
    if is_13_4_resource_farm_stage():
        client2 = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
        resp = client2.send_request(API_INDEX_INDEX, {"time": int(time.time()), "furniture_data": False})
        if isinstance(resp, dict) and "error" not in resp:
            end_inv = get_basic_resource_inventory_from_index_payload(resp)
            CONFIG["RESOURCE_13_4_END_INVENTORY"] = end_inv
            RUN_STATS["resource_end_inventory"] = end_inv
            start_inv = CONFIG.get("RESOURCE_13_4_START_INVENTORY", {})
            gained = {k: end_inv.get(k,0) - start_inv.get(k,0) for k in BASIC_RESOURCE_KEYS}
            RUN_STATS["resource_gained"] = gained
            print(f"起始库存: {format_resource_inventory(start_inv)}")
            print(f"结束库存: {format_resource_inventory(end_inv)}")
            print(f"本次获得: {format_resource_inventory(gained)}")
    print_exit_summary()
    worker_mode = None
    reopen_stage_selection_menu()

def on_traffic(event_type, url, data):
    if str(event_type).upper() == "SYS_KEY_UPGRADE":
        CONFIG["USER_UID"] = data.get("uid")
        CONFIG["SIGN_KEY"] = data.get("sign")
        CONFIG["INDEX_FETCH_READY"] = True
        print(f"\n[+] 密钥已获取: UID={CONFIG['USER_UID']}, SIGN={CONFIG['SIGN_KEY']}")
        if CONFIG.get("AUTO_MONITOR_MODE"):
            print("[AUTO] 请等待游戏完全进入主界面，再次输入 -a 以请求 Index/index。")

def enable_console_ansi():
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass

if __name__ == '__main__':
    enable_console_ansi()
    print_main_menu()
    while True:
        try:
            cmd = input("GFL-EN13> ").strip()
            if not cmd:
                continue
            if cmd in ('-134train', '-train134', '134train', 'train134'):
                preset_train134_mode()
                continue
            if cmd in ('-134', '134'):
                preset_resource134_mode()
                continue
            if cmd == '-a':
                if not CONFIG.get("INDEX_FETCH_READY") and not proxy_instance and CONFIG.get("MODE_SELECTED_EARLY") and CONFIG["SIGN_KEY"] != DEFAULT_SIGN:
                    print("[*] 复用已有密钥请求 Index/index...")
                    if request_index_and_prepare_configs():
                        continue
                    else:
                        print("[!] 请求失败，回退到代理抓取流程。")
                if not CONFIG.get("INDEX_FETCH_READY") and not proxy_instance:
                    print("\n默认服务器 EN，直接启动代理...")
                    CONFIG["SERVER_NAME"] = "EN"
                    CONFIG["BASE_URL"] = SERVERS.get("EN", EN_FALLBACK_BASE_URL)
                    print("[*] 已预选模式，现在启动代理抓取 UID/SIGN...")
                    reset_captured_team_configs()
                    CONFIG["AUTO_MONITOR_MODE"] = True
                    CONFIG["INDEX_FETCH_READY"] = False
                    proxy_instance = GFLProxy(CONFIG["PROXY_PORT"], STATIC_KEY, on_traffic)
                    proxy_instance.start()
                    set_windows_proxy(True, f"127.0.0.1:{CONFIG['PROXY_PORT']}")
                    worker_mode = 'a'
                    print(f"[*] 代理已启动，端口 {CONFIG['PROXY_PORT']}。请登录游戏进入主界面，然后再次输入 -a。")
                    continue
                if CONFIG.get("INDEX_FETCH_READY"):
                    if proxy_instance:
                        stop_proxy_instance()
                        time.sleep(1)
                    CONFIG["AUTO_MONITOR_MODE"] = False
                    CONFIG["INDEX_FETCH_READY"] = False
                    request_index_and_prepare_configs()
                    continue
                if proxy_instance:
                    print("[!] 代理已在运行，请先登录游戏。")
                else:
                    print("[!] 尚未抓取到有效密钥，请先执行 -a 启动代理。")
            elif cmd == '-r':
                if MENU_STATE["selection_unlocked"]:
                    if CONFIG["SELECTED_DIFFICULTY"] is None:
                        print("[!] 请先使用 -134train 或 -134 预选模式并执行 -a。")
                        continue
                    if MENU_STATE["awaiting_run_confirm"]:
                        print("[!] 请先完成运行前确认（输入 -y）或 -back 返回。")
                        continue
                    if CONFIG.get("MODE_NAME") == "team" and not CAPTURED_TEAM_CONFIGS:
                        print("[!] 请先执行 -a 抓取梯队配置。")
                        continue
                if worker_mode == 'c' and proxy_instance:
                    proxy_instance.stop()
                    set_windows_proxy(False)
                    proxy_instance = None
                    time.sleep(1)
                stop_macro_flag = False
                stop_micro_flag = False
                worker_mode = 'r'
                current_worker_thread = threading.Thread(target=farm_worker)
                current_worker_thread.daemon = True
                current_worker_thread.start()
            elif cmd == '-q':
                stop_macro_flag = True
                print("[*] 将在当前 MACRO 结束后停止...")
            elif cmd == '-Q':
                stop_micro_flag = True
                print("[*] 将在当前 MICRO 结束后停止...")
            elif cmd == '-s':
                if proxy_instance:
                    CONFIG["AUTO_MONITOR_MODE"] = False
                    stop_proxy_instance()
                    print("[*] 代理已停止。")
                else:
                    print("[!] 代理未运行。")
            elif cmd == '-E':
                if proxy_instance:
                    proxy_instance.stop()
                set_windows_proxy(False)
                stop_macro_flag = True
                stop_micro_flag = True
                print_exit_summary()
                print("[*] 已安全退出，Windows 代理已恢复。")
                sys.exit(0)
            else:
                print("[!] 未知命令。可用命令：-134train, -134, -a, -r, -q, -Q, -s, -E")
        except KeyboardInterrupt:
            print("\n[!] 请使用 -E 安全退出。")