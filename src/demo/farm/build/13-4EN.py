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
    API_MISSION_SUPPLY, API_MISSION_BATTLE_FINISH,
)

try:
    from gflzirc import API_INDEX_INDEX
except ImportError:
    API_INDEX_INDEX = "Index/index"

# 强制覆盖装备拆解接口。
# 不再信任 gflzirc 内置常量，避免其仍然指向错误的 "3000/Equip_retire"。
API_EQUIP_RETIRE = "3000/Equip/retire"

try:
    from gflzirc import API_INDEX_HOME
except ImportError:
    API_INDEX_HOME = "3000/Index/home"

try:
    from gflzirc import API_SANGVIS_GASHA
except ImportError:
    API_SANGVIS_GASHA = "3000/Sangvis_gasha"

# ================= EN 服务器兜底配置 =================
# EN 特供版：默认只使用 EN。若当前 gflzirc 没有内置 EN，
# 请把 EN_FALLBACK_BASE_URL 改为你实际抓包使用的 EN BASE_URL。
EN_FALLBACK_BASE_URL = SERVERS.get("EN") or SERVERS.get("SOP")
if "EN" not in SERVERS and EN_FALLBACK_BASE_URL:
    SERVERS["EN"] = EN_FALLBACK_BASE_URL

# ================= 13-4 练级关卡配置 =================
# 说明：该配置从 EN 13-4 特供版迁移而来，但此文件仍保留原 epa_plus 的服务器/打捞功能。
# 13-4 与 EPA 关卡保持一致：不主动调用 API_MISSION_SUPPLY，避免每轮补给造成资源浪费。
# farm_mission_epa 会先部署在 START_SPOT，再按 ROUTE 逐点移动；
# 13-4 练级改为独立双部署五战模式：梯队1为单人占位队，不参与练级；从梯队2开始作为练级队。
TRAIN_STAGE_13_4 = {
    "difficulty": "练级",
    "stage": "13-4",
    "label": "13-4 五战练级",
    "mission_id": 128,
    # 练级队部署在 91263，梯队1单人占位队部署在 91297。
    # 只移动当前练级队，路线共5战：91263 -> 91264 -> 91265 -> 91266 -> 91268 -> 91271。
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
    # 13-4 资源打捞固定双单人部署：梯队1=91263，梯队2=91297。
    # 只移动梯队1，路线共5战：91263 -> 91264 -> 91265 -> 91266 -> 91268 -> 91271。
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
# === Authentication & Connection ===
    "USER_UID": "_InputYourID_",
    "SIGN_KEY": DEFAULT_SIGN,
    "SERVER_NAME": "EN",
    "BASE_URL": SERVERS.get("EN", EN_FALLBACK_BASE_URL),
    "PROXY_PORT": 12335,

# === Farm Loop Settings ===
    "MACRO_LOOPS": 200,
    # 5个掉落（一关）*10次循环，拆一次（大概50-60个左右）
    "MISSIONS_PER_RETIRE": 8,

# === Mission Specific Config ===
    # EPA: EX1
    "MISSION_ID": 145,
    "START_SPOT": 97061,
    "ROUTE": [97039, 97040, 97041, 97036, 97031],

    # 当前菜单选择（后续可继续扩展为真正的关卡配置）
    "SELECTED_DIFFICULTY": None,
    "SELECTED_STAGE": None,
    "SELECTED_TARGET": None,
    "SELECTED_TARGET_LABEL": None,
    "SELECTED_BATTLE_TEMPLATE": None,
    "SINGLE_GUN_MODE": False,
    "SINGLE_GUN_INDEX": 0,
    "MODE_SELECTED_EARLY": False,
    "MODE_NAME": "single",   # single=打捞, team=练级
    "RESOURCE_FARM_MODE": False,  # True=13-4 四项基础资源打捞（不保护人形掉落，全部拆解）
    "TRAIN_13_4_MODE": False,     # True=13-4 独立练级：梯队1单人占位，从梯队2开始练级
    "TRAIN_13_4_DUMMY_TEAM_ID": 1,
    "TRAIN_13_4_FIRST_TEAM_ID": 2,
    "TRAIN_13_4_DUMMY_START_SPOT": 91297,
    "RESOURCE_13_4_MAIN_TEAM_ID": 1,
    "RESOURCE_13_4_SUPPORT_TEAM_ID": 2,
    "RESOURCE_13_4_SUPPORT_START_SPOT": 91297,
    # 13-4 资源打捞：起始资源使用 -a 主动请求 Index/index 时的库存；结束时再请求一次 Index/index 计算收益。
    "RESOURCE_13_4_START_INVENTORY": {},
    "RESOURCE_13_4_END_INVENTORY": {},
    "TRAIN_TEAM_COUNT": 1,
    "TRAIN_SCHEDULE_MODE": "full",   # full=当前梯队练到全满再切下一个, equal=均等练级轮转
    "CURRENT_TRAIN_TEAM_INDEX": 0,
    "STOP_ON_MAX_LEVEL": True,
    # single 打捞模式：当当前目标人形至少各掉落 1 个后自动停止。
    "STOP_AFTER_EACH_TARGET_DROPPED": False,
    "AUTO_MONITOR_MODE": False,
    "AUTO_CAPTURE_EXPECTED_COUNT": 1,
    "INDEX_FETCH_READY": False,

    # 自动拆解保护：
    # 1) 会自动保护当前关卡菜单里“已选择目标”的配置 ID
    # 2) 也会额外保护下面手动填写的 gun_id
    "PROTECTED_DROP_GUN_IDS": [],

    # 当连续两次自动拆解后仍然提示仓库空间不足时，自动停机
    "STOP_AFTER_RETIRE_NO_SPACE_TIMES": 2,
    "ENABLE_FILTER_PROTECTION": True,

    # 实际运行时无需使用此config，仅作占位作用，如果需要获取请自行运行monitor.py来获取并输入。
    "USER_DEVICE": "1145141919810",

    # === Team Config ===
    # Echelon ID
    # 梯队ID
    "TEAM_ID": 1,

    # Target Fairy UID (Set to 0 or None if no fairy is equipped)
    "FAIRY_ID": 159357,
    "FAIRY": None,

      "GUNS": [
        {"id": 115599, "life": 444},
        {"id": 335577, "life": 1130},
        {"id": 225588, "life": 420},
        {"id": 336699, "life": 300},
        {"id": 114477, "life": 248}
    ]
}

NORMAL_STAGE_OPTIONS = [f"A-{i}" for i in range(1, 11)]
EMERGENCY_STAGE_OPTIONS = [f"A-{i}" for i in range(1, 7)]
NIGHT_STAGE_OPTIONS = [f"A-{i}" for i in range(1, 7)]

NORMAL_STAGE_DATA = {
    "A-1": {
        "MISSION_ID": 135,
        "DEFAULT_START_SPOT": 89761,
        "OPTIONS": {
            "-1": {"label": "M1887&M1A1", "start_spot": 89761, "route": [89755, 89756, 89757, 89758, 89759]},
            "-2": {"label": "FN-57&FMG-9", "start_spot": 89761, "route": [89750, 89751, 89752, 89753, 89754]},
            "-3": {"label": "OTs-14&格洛克17", "start_spot": 89761, "route": [89745, 89746, 89747, 89748, 89749]},
            "-4": {"label": "PP-19&56式半", "start_spot": 89761, "route": [89740, 89741, 89742, 89743, 89744]},
            "-5": {"label": "SPP-1&M21", "start_spot": 89761, "route": [89735, 89736, 89737, 89738, 89739]},
        },
    },
    "A-2": {
        "MISSION_ID": 136,
        "DEFAULT_START_SPOT": 89790,
        "OPTIONS": {
            "-1": {"label": "UMP40&谢尔久科夫", "start_spot": 89790, "route": [89764, 89765, 89766, 89767, 89768]},
            "-2": {"label": "KLIN&S-SASS", "start_spot": 89790, "route": [89769, 89770, 89771, 89772, 89773]},
            "-3": {"label": "CZ75&M249 SAW", "start_spot": 89790, "route": [89774, 89775, 89776, 89777, 89778]},
            "-4": {"label": "ART556&RPD", "start_spot": 89790, "route": [89779, 89780, 89781, 89782, 89783]},
            "-5": {"label": "DSR-50&CZ-805", "start_spot": 89790, "route": [89784, 89785, 89786, 89787, 89788]},
        },
    },
    "A-3": {
        "MISSION_ID": 137,
        "DEFAULT_START_SPOT": 89819,
        "OPTIONS": {
            "-1": {"label": "Ak 5&6P62", "start_spot": 89819, "route": [89793, 89794, 89795, 89796, 89797]},
            "-2": {"label": "XM3&PSM", "start_spot": 89819, "route": [89798, 89799, 89800, 89801, 89802]},
            "-3": {"label": "JS05&EVO 3", "start_spot": 89819, "route": [89803, 89804, 89805, 89806, 89807]},
            "-4": {"label": "芭莉斯塔&59式", "start_spot": 89819, "route": [89808, 89809, 89810, 89811, 89812]},
            "-5": {"label": "HK21&AR70", "start_spot": 89819, "route": [89813, 89814, 89815, 89816, 89817]},
        },
    },
    "A-4": {
        "MISSION_ID": 138,
        "DEFAULT_START_SPOT": 89848,
        "OPTIONS": {
            "-1": {"label": "雷电&SCW", "start_spot": 89848, "route": [89822, 89823, 89824, 89825, 89826]},
            "-2": {"label": "蜜獾&ASh-12.7", "start_spot": 89848, "route": [89827, 89828, 89829, 89830, 89831]},
            "-3": {"label": "SRS&MT-9", "start_spot": 89848, "route": [89832, 89833, 89834, 89835, 89836]},
            "-4": {"label": "AUG&SSG 69", "start_spot": 89848, "route": [89837, 89838, 89839, 89840, 89841]},
            "-5": {"label": "TAC-50&HK45", "start_spot": 89848, "route": [89842, 89843, 89844, 89845, 89846]},
        },
    },
    "A-5": {
        "MISSION_ID": 139,
        "DEFAULT_START_SPOT": 89877,
        "OPTIONS": {
            "-1": {"label": "CZ2000&P226", "start_spot": 89877, "route": [89851, 89852, 89853, 89854, 89855]},
            "-2": {"label": "Cx4 风暴&M12", "start_spot": 89877, "route": [89856, 89857, 89858, 89859, 89860]},
            "-3": {"label": "PM-06&八一式马", "start_spot": 89877, "route": [89861, 89862, 89863, 89864, 89865]},
            "-4": {"label": "蟒蛇&TMP", "start_spot": 89877, "route": [89866, 89867, 89868, 89869, 89870]},
            "-5": {"label": "AK-74U&wz.29", "start_spot": 89877, "route": [89871, 89872, 89873, 89874, 89875]},
        },
    },
    "A-6": {
        "MISSION_ID": 140,
        "DEFAULT_START_SPOT": 89906,
        "OPTIONS": {
            "-1": {"label": "Mk 12&CZ52", "start_spot": 89906, "route": [89880, 89881, 89882, 89883, 89884]},
            "-2": {"label": "A-91&OTs-39", "start_spot": 89906, "route": [89885, 89886, 89887, 89888, 89889]},
            "-3": {"label": "M870&T65", "start_spot": 89906, "route": [89890, 89891, 89892, 89893, 89894]},
            "-4": {"label": "M82A1&HK23", "start_spot": 89906, "route": [89895, 89896, 89897, 89898, 89899]},
            "-5": {"label": "JS 9&猎豹M1", "start_spot": 89906, "route": [89900, 89901, 89902, 89903, 89904]},
        },
    },
    "A-7": {
        "MISSION_ID": 141,
        "DEFAULT_START_SPOT": 89935,
        "OPTIONS": {
            "-1": {"label": "Mk46&GSh-18", "start_spot": 89935, "route": [89909, 89910, 89911, 89912, 89913]},
            "-2": {"label": "KSVK&Model L", "start_spot": 89935, "route": [89914, 89915, 89916, 89917, 89918]},
            "-3": {"label": "P22&SM-1", "start_spot": 89935, "route": [89919, 89920, 89921, 89922, 89923]},
            "-4": {"label": "HS2000&T77", "start_spot": 89935, "route": [89924, 89925, 89926, 89927, 89928]},
            "-5": {"label": "X95&MP-443", "start_spot": 89935, "route": [89929, 89930, 89931, 89932, 89933]},
        },
    },
    "A-8": {
        "MISSION_ID": 142,
        "DEFAULT_START_SPOT": 89964,
        "OPTIONS": {
            "-1": {"label": "UKM-2000&RT-20", "start_spot": 89964, "route": [89938, 89939, 89940, 89941, 89942]},
            "-2": {"label": "SSG3000&62式", "start_spot": 89964, "route": [89943, 89944, 89945, 89946, 89947]},
            "-3": {"label": "刘易斯&OBR", "start_spot": 89964, "route": [89948, 89949, 89950, 89951, 89952]},
            "-4": {"label": "PM-9&MP-448", "start_spot": 89964, "route": [89953, 89954, 89955, 89956, 89957]},
            "-5": {"label": "R93&03式", "start_spot": 89964, "route": [89958, 89959, 89960, 89961, 89962]},
        },
    },
    "A-9": {
        "MISSION_ID": 143,
        "DEFAULT_START_SPOT": 89993,
        "OPTIONS": {
            "-1": {"label": "M1895 CB&马盖尔", "start_spot": 89993, "route": [89967, 89968, 89969, 89970, 89971]},
            "-2": {"label": "MAT-49&HK33", "start_spot": 89993, "route": [89972, 89973, 89974, 89975, 89976]},
            "-3": {"label": "沙漠之鹰&TEC-9", "start_spot": 89993, "route": [89977, 89978, 89979, 89980, 89981]},
            "-4": {"label": "ACR&侦察者", "start_spot": 89993, "route": [89982, 89983, 89984, 89985, 89986]},
            "-5": {"label": "Kord&隼", "start_spot": 89993, "route": [89987, 89988, 89989, 89990, 89991]},
        },
    },
    "A-10": {
        "MISSION_ID": 144,
        "DEFAULT_START_SPOT": 97026,
        "OPTIONS": {
            "-1": {"label": "SL8&K3", "start_spot": 97026, "route": [97020, 97021, 97022, 97023, 97024]},
            "-2": {"label": "韦伯利&T-CMS", "start_spot": 97026, "route": [97015, 97016, 97017, 97018, 97019]},
            "-3": {"label": "R5&MP41", "start_spot": 97026, "route": [97010, 97011, 97012, 97013, 97014]},
            "-4": {"label": "M82&CPS-12", "start_spot": 97026, "route": [97005, 97006, 97007, 97008, 97009]},
            "-5": {"label": "CF05&VP70", "start_spot": 97026, "route": [97000, 97001, 97002, 97003, 97004]},
        },
    },
}

EMERGENCY_STAGE_DATA = {
    "A-1": {
        "MISSION_ID": 145,
        "START_SPOTS": {"-1": 97061, "-2": 97061, "-3": 97061, "-4": 97059, "-5": 97059, "-6": 97059},
        "OPTIONS": {
            "-1": {"label": "防卫者&Vepr", "route": [97029, 97030, 97031, 97032, 97033]},
            "-2": {"label": "蒙德拉贡M1908&高标10型", "route": [97034, 97035, 97036, 97037, 97038]},
            "-3": {"label": "PM1910&CAR", "route": [97039, 97040, 97041, 97042, 97043]},
            "-4": {"label": "卢萨&英萨斯", "route": [97044, 97045, 97046, 97047, 97048]},
            "-5": {"label": "AUG SMG&Zas M76", "route": [97049, 97050, 97051, 97052, 97053]},
            "-6": {"label": "刘氏步枪&43M", "route": [97054, 97055, 97056, 97057, 97058]},
        },
    },
    "A-2": {
        "MISSION_ID": 146,
        "START_SPOTS": {"-1": 97095, "-2": 97095, "-3": 97095, "-4": 97093, "-5": 97093, "-6": 97093},
        "OPTIONS": {
            "-1": {"label": "德林加&CAR", "route": [97063, 97064, 97065, 97066, 97067]},
            "-2": {"label": "菲德洛夫&MAS-38", "route": [97068, 97069, 97070, 97071, 97072]},
            "-3": {"label": "APC556&C14", "route": [97073, 97074, 97075, 97076, 97077]},
            "-4": {"label": "VHS&43M", "route": [97078, 97079, 97080, 97081, 97082]},
            "-5": {"label": "蜂鸟&Vepr", "route": [97083, 97084, 97085, 97086, 97087]},
            "-6": {"label": "VP1915&高标10型", "route": [97088, 97089, 97090, 97091, 97092]},
        },
    },
    "A-3": {
        "MISSION_ID": 147,
        "START_SPOTS": {"-1": 97129, "-2": 97129, "-3": 97129, "-4": 97127, "-5": 97127, "-6": 97127},
        "OPTIONS": {
            "-1": {"label": "FARA 83&WKp", "route": [97097, 97098, 97099, 97100, 97101]},
            "-2": {"label": "PPQ&StG-940", "route": [97102, 97103, 97104, 97105, 97106]},
            "-3": {"label": "沙维奇99型&高标10型", "route": [97107, 97108, 97109, 97110, 97111]},
            "-4": {"label": "TKB-408&CAR", "route": [97112, 97113, 97114, 97115, 97116]},
            "-5": {"label": "SP9&MAS-38", "route": [97117, 97118, 97119, 97120, 97121]},
            "-6": {"label": "KH2002&C14", "route": [97122, 97123, 97124, 97125, 97126]},
        },
    },
    "A-4": {
        "MISSION_ID": 148,
        "START_SPOTS": {"-1": 97163, "-2": 97163, "-3": 97163, "-4": 97161, "-5": 97161, "-6": 97161},
        "OPTIONS": {
            "-1": {"label": "TF-Q&GM6 Lynx", "route": [97131, 97132, 97133, 97134, 97135]},
            "-2": {"label": "LS26&TS12", "route": [97136, 97137, 97138, 97139, 97140]},
            "-3": {"label": "MG338&MAS-38", "route": [97141, 97142, 97143, 97144, 97145]},
            "-4": {"label": "芮诺&C14", "route": [97146, 97147, 97148, 97149, 97150]},
            "-5": {"label": "斯特林&WKp", "route": [97151, 97152, 97153, 97154, 97155]},
            "-6": {"label": "QBZ-191&StG-940", "route": [97156, 97157, 97158, 97159, 97160]},
        },
    },
    "A-5": {
        "MISSION_ID": 149,
        "START_SPOTS": {"-1": 97197, "-2": 97197, "-3": 97197, "-4": 97195, "-5": 97195, "-6": 97195},
        "OPTIONS": {
            "-1": {"label": "P290&QSB-91", "route": [97165, 97166, 97167, 97168, 97169]},
            "-2": {"label": "Saiga 308&SUB-2000", "route": [97170, 97171, 97172, 97173, 97174]},
            "-3": {"label": "M327&WKp", "route": [97175, 97176, 97177, 97178, 97179]},
            "-4": {"label": "AR-18&StG-940", "route": [97180, 97181, 97182, 97183, 97184]},
            "-5": {"label": "M240L&GM6 Lynx", "route": [97185, 97186, 97187, 97188, 97189]},
            "-6": {"label": "Jatimatic&TS12", "route": [97190, 97191, 97192, 97193, 97194]},
        },
    },
    "A-6": {
        "MISSION_ID": 150,
        # 紧急 A-6 的路线节点为 97199~97228。
        # 按前几个紧急关卡的编号规律，部署点应为路线后方的 97231 / 97229，
        # 不是路线内部节点 97221，也不是夜战/其他区域节点 97239。
        "START_SPOTS": {"-1": 97231, "-2": 97231, "-3": 97231, "-4": 97229, "-5": 97229, "-6": 97229},
        "OPTIONS": {
            "-1": {"label": "CMR-30&英萨斯", "route": [97199, 97200, 97201, 97202, 97203]},
            "-2": {"label": "VP9&Zas M76", "route": [97204, 97205, 97206, 97207, 97208]},
            "-3": {"label": "VRB&GM6 Lynx", "route": [97209, 97210, 97211, 97212, 97213]},
            "-4": {"label": "LAMG&TS12", "route": [97214, 97215, 97216, 97217, 97218]},
            "-5": {"label": "TPS&QSB-91", "route": [97219, 97220, 97221, 97222, 97223]},
            "-6": {"label": "P2000&SUB-2000", "route": [97224, 97225, 97226, 97227, 97228]},
        },
    },
}

NIGHT_STAGE_DATA = {
    "A-1": {
        "MISSION_ID": 151,
        "START_SPOTS": {
            "-1": 97255,
            "-2": 97255,
            "-3": 97253,
            "-4": 97253,
        },
        "OPTIONS": {
            "-1": {"label": "国家竞赛穿甲弹", "route": [97233, 97234, 97235, 97236, 97237]},
            "-2": {"label": ".300BLK高速弹", "route": [97238, 97239, 97240, 97241, 97242]},
            "-3": {"label": "Titan火控芯片", "route": [97243, 97244, 97245, 97246, 97247]},
            "-4": {"label": "GSG UX外骨骼", "route": [97248, 97249, 97250, 97251, 97252]},
        },
    },
    "A-2": {
        "MISSION_ID": 152,
        "START_SPOTS": {
            "-1": 97279,
            "-2": 97279,
            "-3": 97277,
            "-4": 97277,
        },
        "OPTIONS": {
            "-1": {"label": "Hayha记忆芯片", "route": [97257, 97258, 97259, 97260, 97261]},
            "-2": {"label": "特殊战机动护甲", "route": [97262, 97263, 97264, 97265, 97266]},
            "-3": {"label": "无限弹链箱", "route": [97267, 97268, 97269, 97270, 97271]},
            "-4": {"label": "FÉLIN系统瞄具", "route": [97272, 97273, 97274, 97275, 97276]},
        },
    },
    "A-3": {
        "MISSION_ID": 153,
        "START_SPOTS": {
            "-1": 97303,
            "-2": 97303,
            "-3": 97301,
            "-4": 97301,
        },
        "OPTIONS": {
            "-1": {"label": "APS专用枪托", "route": [97281, 97282, 97283, 97284, 97285]},
            "-2": {"label": "战术耳机", "route": [97286, 97287, 97288, 97289, 97290]},
            "-3": {"label": "星条领带", "route": [97291, 97292, 97293, 97294, 97295]},
            "-4": {"label": "7.62纳甘弹", "route": [97296, 97297, 97298, 97299, 97300]},
        },
    },
    "A-4": {
        "MISSION_ID": 154,
        "START_SPOTS": {
            "-1": 97327,
            "-2": 97327,
            "-3": 97325,
            "-4": 97325,
        },
        "OPTIONS": {
            "-1": {"label": "司登手枪弹", "route": [97305, 97306, 97307, 97308, 97309]},
            "-2": {"label": "7.63毛瑟弹", "route": [97310, 97311, 97312, 97313, 97314]},
            "-3": {"label": "pks-07瞄准镜", "route": [97315, 97316, 97317, 97318, 97319]},
            "-4": {"label": "StG瞄准镜", "route": [97320, 97321, 97322, 97323, 97324]},
        },
    },
    "A-5": {
        "MISSION_ID": 155,
        "START_SPOTS": {
            "-1": 97351,
            "-2": 97351,
            "-3": 97349,
            "-4": 97349,
        },
        "OPTIONS": {
            "-1": {"label": "G3特制弹", "route": [97329, 97330, 97331, 97332, 97333]},
            "-2": {"label": "SC特制弹", "route": [97334, 97335, 97336, 97337, 97338]},
            "-3": {"label": "牛仔帽", "route": [97339, 97340, 97341, 97342, 97343]},
            "-4": {"label": "8×42瞄准镜", "route": [97344, 97345, 97346, 97347, 97348]},
        },
    },
    "A-6": {
        "MISSION_ID": 156,
        "START_SPOTS": {
            "-1": 97368,
            "-2": 97368,
            "-3": 97368
        },
        "OPTIONS": {
            "-1": {"label": "皇家作战披风", "route": [97353, 97354, 97355, 97356, 97357]},
            "-2": {"label": "KR步枪弹", "route": [97358, 97359, 97360, 97361, 97362]},
            "-3": {"label": "PK-A内红点瞄准镜", "route": [97363, 97364, 97365, 97366, 97367]}
        }
    }
}

EQUIP_ID_OVERRIDE = {
    # 夜战专属装备 / 已确认或高置信度映射
    "国家竞赛穿甲弹": 59,
    ".300BLK高速弹": 60,
    "Titan火控芯片": 112,
    "GSG UX外骨骼": 62,

    "Hayha记忆芯片": 86,
    "特殊战机动护甲": 91,
    "无限弹链箱": 107,
    "FÉLIN系统瞄具": 119,

    # APS专用枪托 暂未最终确认，先留空
    "战术耳机": 165,
    "星条领带": 375,
    "7.62纳甘弹": 486,

    "司登手枪弹": 487,
    "7.63毛瑟弹": 488,
    "pks-07瞄准镜": 489,
    "StG瞄准镜": 490,

    "G3特制弹": 491,
    "SC特制弹": 492,
    "牛仔帽": 122,
    "8×42瞄准镜": 494,

    "皇家作战披风": 160,
    "KR步枪弹": 105,
    "PK-A内红点瞄准镜": 497,
}

def resolve_equip_id_by_name(name: str):
    if name in EQUIP_ID_OVERRIDE:
        return int(EQUIP_ID_OVERRIDE[name])
    return None


A10_SINGLE_BATTLE_TEMPLATE = {
    "1000": {
        "10": 1228,
        "11": 1228,
        "12": 1228,
        "13": 1228,
        "15": 12006,
        "16": 0,
        "17": 106,
        "33": 10018,
        "40": 15,
        "18": 0,
        "19": 0,
        "20": 0,
        "21": 0,
        "22": 0,
        "23": 0,
        "24": 3900,
        "25": 0,
        "26": 3900,
        "27": 4,
        "34": 84,
        "35": 84,
        "41": 260,
        "42": 0,
        "43": 0,
        "44": 0
    },
    "1001": {},
    "1005": {},
    "1007": {},
    "1008": {},
    "1009": {}
}

# 13-4 练级手动抓包模板：三个战斗点的 battleFinish 中 1000 字段不同。
# 这些数值来自从登录到手动完成 13-4 一轮的抓包。
TRAIN_13_4_BATTLE_1000_BY_SPOT = {
    91266: {"10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 34199, "16": 0, "17": 192, "33": 11004, "40": 37, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 49907, "25": 0, "26": 49907, "27": 7, "34": 11, "35": 11, "41": 1348, "42": 0, "43": 0, "44": 0},
    91268: {"10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 32109, "16": 0, "17": 154, "33": 11005, "40": 30, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 45321, "25": 0, "26": 45321, "27": 3, "34": 19, "35": 19, "41": 1510, "42": 0, "43": 0, "44": 0},
    91271: {"10": 22549, "11": 22549, "12": 22549, "13": 22549, "15": 49202, "16": 0, "17": 182, "33": 11016, "40": 69, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 68135, "25": 0, "26": 68135, "27": 4, "34": 41, "35": 41, "41": 987, "42": 0, "43": 0, "44": 0},
}

def is_13_4_training_stage():
    try:
        return int(CONFIG.get("MISSION_ID")) == 128 and int(CONFIG.get("START_SPOT")) == 91263
    except Exception:
        return False


def is_13_4_resource_farm_stage():
    try:
        return bool(CONFIG.get("RESOURCE_FARM_MODE")) and int(CONFIG.get("MISSION_ID")) == 128 and int(CONFIG.get("START_SPOT")) == 91263
    except Exception:
        return False


def get_team_config_by_team_id(team_id: int):
    for team_cfg in CAPTURED_TEAM_CONFIGS:
        try:
            if int(team_cfg.get("team_id", 0)) == int(team_id):
                return team_cfg
        except Exception:
            continue
    return None


def get_13_4_main_team_config():
    return get_team_config_by_team_id(CONFIG.get("RESOURCE_13_4_MAIN_TEAM_ID", 1)) or get_current_team_config()


def get_13_4_support_team_config():
    return get_team_config_by_team_id(CONFIG.get("RESOURCE_13_4_SUPPORT_TEAM_ID", 2))

def get_13_4_training_dummy_team_id():
    return int(CONFIG.get("TRAIN_13_4_DUMMY_TEAM_ID", 1))


def get_13_4_training_dummy_start_spot():
    return int(CONFIG.get("TRAIN_13_4_DUMMY_START_SPOT", 91297))


def is_13_4_training_independent_mode():
    return bool(CONFIG.get("TRAIN_13_4_MODE")) and is_13_4_training_stage()



def apply_13_4_resource_farm_config():
    """把当前菜单选择切换为 13-4 双单人五战资源打捞，并关闭人形过滤保护。"""
    # 13-4 资源打捞是独立模式，不再挂在 single 模式下。
    # 该模式固定捕获/使用梯队1与梯队2，且两队都必须为单人编队。
    CONFIG["MODE_NAME"] = "resource134"
    CONFIG["SINGLE_GUN_MODE"] = False
    CONFIG["RESOURCE_FARM_MODE"] = True
    CONFIG["TRAIN_13_4_MODE"] = False

    CONFIG["SELECTED_DIFFICULTY"] = RESOURCE_STAGE_13_4["difficulty"]
    CONFIG["SELECTED_STAGE"] = RESOURCE_STAGE_13_4["stage"]
    CONFIG["SELECTED_TARGET"] = "13-4-resource"
    CONFIG["SELECTED_TARGET_LABEL"] = RESOURCE_STAGE_13_4["label"]
    CONFIG["SELECTED_BATTLE_TEMPLATE"] = None

    CONFIG["MISSION_ID"] = RESOURCE_STAGE_13_4["mission_id"]
    CONFIG["START_SPOT"] = RESOURCE_STAGE_13_4["start_spot"]
    CONFIG["RESOURCE_13_4_SUPPORT_START_SPOT"] = RESOURCE_STAGE_13_4["support_start_spot"]
    CONFIG["RESOURCE_13_4_MAIN_TEAM_ID"] = RESOURCE_STAGE_13_4["main_team_id"]
    CONFIG["RESOURCE_13_4_SUPPORT_TEAM_ID"] = RESOURCE_STAGE_13_4["support_team_id"]
    CONFIG["ROUTE"] = list(RESOURCE_STAGE_13_4["route"])

    # 13-4 资源打捞目标是四项基础资源，不保护任何人形掉落。
    # 运行中的 T-Doll 掉落会全部进入自动拆解。
    CONFIG["ENABLE_FILTER_PROTECTION"] = False
    CONFIG["PROTECTED_DROP_GUN_IDS"] = []
    CONFIG["STOP_AFTER_EACH_TARGET_DROPPED"] = False


def apply_13_4_training_config():
    """把当前菜单选择切换为 13-4 五战练级关卡。

    13-4 练级是独立捕获逻辑：
    - 梯队1固定为单人占位队，部署到 91297，不参与练级；
    - 从梯队2开始作为练级队，当前练级队部署到 91263 并走五战路线。
    """
    CONFIG["MODE_NAME"] = "team"
    CONFIG["SINGLE_GUN_MODE"] = False
    CONFIG["RESOURCE_FARM_MODE"] = False
    CONFIG["TRAIN_13_4_MODE"] = True

    CONFIG["SELECTED_DIFFICULTY"] = TRAIN_STAGE_13_4["difficulty"]
    CONFIG["SELECTED_STAGE"] = TRAIN_STAGE_13_4["stage"]
    CONFIG["SELECTED_TARGET"] = "13-4"
    CONFIG["SELECTED_TARGET_LABEL"] = TRAIN_STAGE_13_4["label"]
    CONFIG["SELECTED_BATTLE_TEMPLATE"] = None

    CONFIG["MISSION_ID"] = TRAIN_STAGE_13_4["mission_id"]
    CONFIG["START_SPOT"] = TRAIN_STAGE_13_4["start_spot"]
    CONFIG["TRAIN_13_4_DUMMY_START_SPOT"] = TRAIN_STAGE_13_4.get("dummy_start_spot", 91297)
    CONFIG["TRAIN_13_4_DUMMY_TEAM_ID"] = TRAIN_STAGE_13_4.get("dummy_team_id", 1)
    CONFIG["TRAIN_13_4_FIRST_TEAM_ID"] = TRAIN_STAGE_13_4.get("first_train_team_id", 2)
    CONFIG["ROUTE"] = list(TRAIN_STAGE_13_4["route"])

    # 13-4 纯练级，不做目标掉落保护。
    CONFIG["ENABLE_FILTER_PROTECTION"] = False
    CONFIG["PROTECTED_DROP_GUN_IDS"] = []
    CONFIG["STOP_AFTER_EACH_TARGET_DROPPED"] = False



MENU_STATE = {
    "selection_unlocked": False,
    "difficulty": None,
    "stage": None,
    "awaiting_gun_mode": False,
    "awaiting_stop_on_max": False,
    "awaiting_target_drop_stop": False,
    "awaiting_filter_protection": False,
    "awaiting_run_confirm": False,
}

current_worker_thread = None
worker_mode = None
proxy_instance = None

stop_macro_flag = False
stop_micro_flag = False

AUTO_CAPTURE_STATE = {
    "team_id": None,
    "fairy_id": None,
    "guns": [],
    "completed": False,
}

CAPTURED_TEAM_CONFIGS = []
TEAM_SWITCH_PENDING = False
TRAIN_COMPLETED_TEAM_INDICES = set()

DROPPED_UID_TO_GUN_ID = {}
DROPPED_UID_TO_EQUIP_ID = {}
RETIRE_NO_SPACE_COUNT = 0

RUN_STATS = {
    "start_time": None,
    "end_time": None,
    "target_counts": {},
    "current_macro": 0,
    "current_micro": 0,
    "current_step": 0,
    "current_team_no": 1,
    "macro_drop_names": [],
    "last_micro_exp_lines": [],
    "panel_enabled": True,
    "recent_logs": [],
    "drop_marquee_offset": 0,
    "drop_marquee_last_key": "",
    "resource_start_inventory": {},
    "resource_end_inventory": {},
    "resource_gained": {},
    "resource_efficiency_per_hour": {},
    "completed_resource_runs": 0,
}

PANEL_LINES_LAST = 0
PANEL_ACTIVE = False

TEAM_PROGRESS_STATE = {
    "current_active_team_id": None,
    "current_active_started_at": None,
}




GUN_CATALOG_CACHE = None
GUN_NAME_ALIAS = {
    "格洛克17": "Glock17",
    "56式半": "56-1",
    "谢尔久科夫": "Serdyukov",
    "S-SASS": "SSGSSASS",
    "芭莉斯塔": "Ballista",
    "59式": "59type",
    "雷电": "Thunder",
    "蜜獾": "HoneyBadger",
    "Cx4 风暴": "Cx4Storm",
    "八一式马": "Type81R",
    "蟒蛇": "Python",
    "猎豹M1": "Gepard M1",
    "62式": "Type62",
    "刘易斯": "Lewis",
    "03式": "Type03",
    "马盖尔": "Magal",
    "沙漠之鹰": "Desert Eagle",
    "侦察者": "Scout",
    "隼": "Falcon",
    "防卫者": "Defender",
    "蒙德拉贡M1908": "Mondragon M1908",
    "高标10型": "General Liu",
    "卢萨": "Lusa",
    "英萨斯": "INSAS",
    "刘氏步枪": "Liu",
    "德林加": "Derringer",
    "菲德洛夫": "Fedorov",
    "沙维奇99型": "Savage99",
    "芮诺": "Reno",
    "斯特林": "Sterling",
    "韦伯利": "Webley",
    # DP-12 为 gun_id 282；CPS-12 也叫 Six12，gun_id 278。
    "DP-12": "DP12",
    "DP12": "DP12",
    "CPS-12": "Six12",
    "Six12": "Six12",
    "CF05": "CF-05",
    "FN-57": "Five-seveN",
    "AK 5": "Ak 5",
    "英萨斯": "INSAS",
    "防卫者": "Defender",
    "刘氏步枪": "Liu Rifle",
    "AUG SMG": "AUG Para",
    "高标10型": "General Liu",
    "TF-Q": "TF Q",
    "6P62": "6P62",
    "Ak 5": "AK 5",
    "STG-940": "StG-940",
    "StG940": "StG-940",
    "stg940": "StG-940",
}

GUN_ID_OVERRIDE = {
    "6P62": 138,
    "Ak 5": 187,
    "AK 5": 187,
    "雷电": 202,
    "SCW": 169,
    # DP-12 的 gun_id = 282。
    "DP-12": 282,
    "DP12": 282,
    # CPS-12 也叫 Six12，gun_id = 278。
    "CPS-12": 278,
    "Six12": 278,
    # 德林加在资料表中为 Derringer，gun_id = 332。
    "德林加": 332,
    "Derringer": 332,
    # StG-940 在资料表中 en_name=StG-940, code=stg940, gun_id=314。
    "StG-940": 314,
    "STG-940": 314,
    "StG940": 314,
    "stg940": 314,
    # 03式在资料表中为 Type03，gun_id = 239。
    "03式": 239,
    "Type03": 239,
    "03type": 239,
    # 猎豹M1在资料表中英文名为 Gepard M1，之前写成 CheetahM1 会导致目标保护失败。
    "猎豹M1": 201,
    "Gepard M1": 201,
    "GepardM1": 201,
    "CheetahM1": 201,
}

def load_gun_catalog():
    global GUN_CATALOG_CACHE
    if GUN_CATALOG_CACHE is not None:
        return GUN_CATALOG_CACHE

    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = ["gun.json", "gun1(1).json", "gun1.json"]

    search_paths = []
    for name in candidates:
        search_paths.append(name)
        search_paths.append(os.path.join(script_dir, name))

    seen = set()
    for fp in search_paths:
        if fp in seen:
            continue
        seen.add(fp)
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    GUN_CATALOG_CACHE = json.load(f)
                    print("[*] 已加载枪械目录：%s" % fp)
                    return GUN_CATALOG_CACHE
            except Exception as e:
                print("[!] 读取枪械目录失败：%s | %s" % (fp, e))

    print("[!] 未找到 gun.json / gun1(1).json / gun1.json，自动拆解保护将无法按目标名解析。")
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

    best_id = None
    for cand in candidates:
        n = normalize_gun_name(cand)
        for gun in catalog:
            for field in ("en_name", "code", "name"):
                value = normalize_gun_name(gun.get(field, ""))
                if not value:
                    continue
                if n == value:
                    return int(gun["id"])

        for gun in catalog:
            values = [normalize_gun_name(gun.get(field, "")) for field in ("en_name", "code", "name")]
            values = [v for v in values if v]
            if any(n in value or value in n for value in values):
                gid = int(gun["id"])
                if best_id is None or gid < best_id:
                    best_id = gid

    return best_id


def get_stage_data(difficulty: str, stage: str):
    if difficulty == "普通":
        return NORMAL_STAGE_DATA.get(stage)
    if difficulty == "紧急":
        return EMERGENCY_STAGE_DATA.get(stage)
    if difficulty == "夜战":
        return NIGHT_STAGE_DATA.get(stage)
    return None


def get_stage_options(difficulty: str, stage: str):
    stage_data = get_stage_data(difficulty, stage)
    if not stage_data:
        return {}
    return stage_data.get("OPTIONS", {})


def split_target_label(label: str):
    return [part.strip() for part in str(label).split("&") if part.strip()]

def reset_auto_capture_state():
    AUTO_CAPTURE_STATE["team_id"] = None
    AUTO_CAPTURE_STATE["fairy_id"] = None
    AUTO_CAPTURE_STATE["guns"] = []
    AUTO_CAPTURE_STATE["completed"] = False


def reset_captured_team_configs():
    CAPTURED_TEAM_CONFIGS.clear()
    CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = 0


def get_current_team_config():
    if CAPTURED_TEAM_CONFIGS:
        if CONFIG.get("MODE_NAME") == "team":
            idx = CONFIG.get("CURRENT_TRAIN_TEAM_INDEX", 0)
            idx = max(0, min(idx, len(CAPTURED_TEAM_CONFIGS) - 1))
            return CAPTURED_TEAM_CONFIGS[idx]
        return CAPTURED_TEAM_CONFIGS[0]
    return {
        "team_id": CONFIG["TEAM_ID"],
        "fairy_id": CONFIG["FAIRY_ID"],
        "fairy": CONFIG.get("FAIRY"),
        "guns": CONFIG["GUNS"],
    }


def get_current_team_id():
    return get_current_team_config()["team_id"]


def get_current_fairy_id():
    return get_current_team_config()["fairy_id"]


def advance_to_next_training_team():
    global TEAM_SWITCH_PENDING
    if CONFIG.get("MODE_NAME") != "team":
        return
    switch_to_next_available_training_team("当前练级梯队已全部满级")


def reset_training_progress():
    TRAIN_COMPLETED_TEAM_INDICES.clear()
    CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = 0
    TEAM_PROGRESS_STATE["current_active_team_id"] = None
    TEAM_PROGRESS_STATE["current_active_started_at"] = None
    for team_cfg in CAPTURED_TEAM_CONFIGS:
        team_cfg["runtime_seconds"] = 0.0
        team_cfg["completed"] = False
        team_cfg["maxed_member_uids"] = set()
        team_cfg["warned_max_member_uids"] = set()


def mark_current_training_team_completed():
    idx = CONFIG.get("CURRENT_TRAIN_TEAM_INDEX", 0)
    TRAIN_COMPLETED_TEAM_INDICES.add(idx)


def get_active_training_team_indices():
    return [i for i in range(len(CAPTURED_TEAM_CONFIGS)) if i not in TRAIN_COMPLETED_TEAM_INDICES]



def switch_to_next_available_training_team(reason: str = ""):
    global TEAM_SWITCH_PENDING, stop_macro_flag, stop_micro_flag
    if CONFIG.get("MODE_NAME") != "team":
        return

    current_idx = CONFIG.get("CURRENT_TRAIN_TEAM_INDEX", 0)
    current_cfg = CAPTURED_TEAM_CONFIGS[current_idx] if 0 <= current_idx < len(CAPTURED_TEAM_CONFIGS) else None
    pause_current_team_runtime()

    if current_cfg and current_idx in TRAIN_COMPLETED_TEAM_INDICES and not current_cfg.get("completed", False):
        current_cfg["completed"] = True
        elapsed = get_team_runtime_seconds(current_cfg)
        panel_safe_print(colorize("[梯队完成] 第 %d 队练级完成，用时：%s" % (current_idx + 1, format_duration(elapsed)), "success"))

    active_indices = get_active_training_team_indices()
    if not active_indices:
        stop_macro_flag = True
        stop_micro_flag = True
        TEAM_SWITCH_PENDING = False
        panel_safe_print(colorize("[全部完成] 所有已配置练级梯队已完成，程序将安全停止。", "success"))
        return

    if current_idx not in active_indices:
        CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = active_indices[0]
        TEAM_SWITCH_PENDING = False
        activate_team_runtime(CAPTURED_TEAM_CONFIGS[CONFIG["CURRENT_TRAIN_TEAM_INDEX"]]["team_id"])
        if reason:
            panel_safe_print("[梯队切换] %s，当前梯队：%d / %d" % (
                reason,
                CONFIG["CURRENT_TRAIN_TEAM_INDEX"] + 1,
                len(CAPTURED_TEAM_CONFIGS),
            ))
        return

    pos = active_indices.index(current_idx)
    next_idx = active_indices[(pos + 1) % len(active_indices)]
    CONFIG["CURRENT_TRAIN_TEAM_INDEX"] = next_idx
    TEAM_SWITCH_PENDING = False
    activate_team_runtime(CAPTURED_TEAM_CONFIGS[next_idx]["team_id"])
    if reason:
        panel_safe_print("[梯队切换] %s，当前梯队：%d / %d" % (
            reason,
            next_idx + 1,
            len(CAPTURED_TEAM_CONFIGS),
        ))


def build_team_configs_from_index(payload: dict):
    if not isinstance(payload, dict):
        return []

    gun_list = payload.get("gun_with_user_info", [])
    fairy_data = payload.get("fairy_with_user_info", {})

    team_map = {}

    if isinstance(fairy_data, dict):
        # 有的 Index/index 里 fairy_with_user_info 是“单个妖精对象”；
        # 也有的版本是 {uid: {...}} 这样的映射。
        if any(k in fairy_data for k in ("team_id", "fairy_id", "fairy_lv", "fairy_exp", "id", "fairy_with_user_id")):
            fairy_iter = [fairy_data]
        else:
            fairy_iter = [v for v in fairy_data.values() if isinstance(v, dict)]
    elif isinstance(fairy_data, list):
        fairy_iter = fairy_data
    else:
        fairy_iter = []

    for fairy in fairy_iter:
        if not isinstance(fairy, dict):
            continue
        team_id_raw = fairy.get("team_id", "0")
        try:
            team_id = int(team_id_raw)
        except Exception:
            continue
        if team_id < 1 or team_id > 14:
            continue
        fairy_uid = fairy.get("id") or fairy.get("fairy_with_user_id")
        fairy_type_id = fairy.get("fairy_id", 0)
        try:
            fairy_uid = int(fairy_uid)
        except Exception:
            fairy_uid = 0
        try:
            fairy_type_id = int(fairy_type_id)
        except Exception:
            fairy_type_id = 0

        team_map.setdefault(team_id, {"team_id": team_id, "fairy_id": 0, "guns": [], "fairy": None})
        if fairy_uid > 0:
            team_map[team_id]["fairy_id"] = fairy_uid
            team_map[team_id]["fairy"] = {
                "id": fairy_uid,
                "fairy_id": fairy_type_id,
                "level": int(
                    fairy.get("fairy_lv",
                    fairy.get("level",
                    fairy.get("lv", 1))) or 1
                ),
                "exp": int(
                    fairy.get("fairy_exp",
                    fairy.get("exp",
                    fairy.get("now_exp", 0))) or 0
                ),
                "team_id": team_id,
            }

    if not isinstance(gun_list, list):
        gun_list = []

    for gun in gun_list:
        if not isinstance(gun, dict):
            continue
        team_id_raw = gun.get("team_id", "0")
        try:
            team_id = int(team_id_raw)
        except Exception:
            continue
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

        team_map.setdefault(team_id, {"team_id": team_id, "fairy_id": 0, "guns": [], "fairy": None})
        team_map[team_id]["guns"].append({
            "id": gun_uid,
            "gun_id": gun_type_id,
            "life": life,
            "level": int(gun.get("gun_level", gun.get("level", 1)) or 1),
            "exp": int(gun.get("gun_exp", gun.get("exp", 0)) or 0),
            "team_id": team_id,
        })

    teams = []
    for team_id in sorted(team_map.keys()):
        team_cfg = team_map[team_id]
        # 练级模式不强制要求携带妖精；只要梯队有人形即可作为练级梯队。
        if team_cfg["guns"]:
            init_team_progress_runtime_fields(team_cfg)
            teams.append(team_cfg)

    return teams


def try_update_auto_capture_from_index_payload(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False

    if "gun_with_user_info" not in payload or "fairy_with_user_info" not in payload:
        return False

    teams = build_team_configs_from_index(payload)
    if not teams:
        return False

    reset_captured_team_configs()

    if CONFIG.get("MODE_NAME") == "resource134":
        team_by_id = {}
        for team_cfg in teams:
            try:
                team_by_id[int(team_cfg.get("team_id", 0))] = team_cfg
            except Exception:
                continue

        required_ids = [
            int(CONFIG.get("RESOURCE_13_4_MAIN_TEAM_ID", 1)),
            int(CONFIG.get("RESOURCE_13_4_SUPPORT_TEAM_ID", 2)),
        ]
        missing = [tid for tid in required_ids if tid not in team_by_id]
        invalid = [tid for tid in required_ids if tid in team_by_id and len(team_by_id[tid].get("guns", [])) != 1]
        if missing or invalid:
            print("[AUTO] 13-4 资源打捞梯队校验失败：固定要求梯队1、梯队2都为单人人形编队。")
            if missing:
                print("[AUTO] 未解析到梯队：%s" % missing)
            if invalid:
                for tid in invalid:
                    print("[AUTO] 梯队%s 当前人形数量：%s" % (tid, len(team_by_id[tid].get("guns", []))))
            print("[AUTO] 请在游戏内调整梯队1和梯队2后，重新输入 -a 抓取 Index/index。")
            return False

        for tid in required_ids:
            team_cfg = team_by_id[tid]
            CAPTURED_TEAM_CONFIGS.append({
                "team_id": team_cfg["team_id"],
                "fairy_id": team_cfg["fairy_id"],
                "fairy": copy.deepcopy(team_cfg.get("fairy")),
                "guns": copy.deepcopy(team_cfg["guns"]),
                "runtime_seconds": 0.0,
                "completed": False,
            })

        main_cfg = CAPTURED_TEAM_CONFIGS[0]
        CONFIG["TEAM_ID"] = main_cfg["team_id"]
        CONFIG["FAIRY_ID"] = main_cfg["fairy_id"]
        CONFIG["FAIRY"] = copy.deepcopy(main_cfg.get("fairy"))
        CONFIG["GUNS"] = copy.deepcopy(main_cfg["guns"])
        CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 2

    elif CONFIG.get("MODE_NAME") == "team":
        expected = max(1, min(10, int(CONFIG.get("TRAIN_TEAM_COUNT", 1))))

        if CONFIG.get("TRAIN_13_4_MODE"):
            team_by_id = {}
            for team_cfg in teams:
                try:
                    team_by_id[int(team_cfg.get("team_id", 0))] = team_cfg
                except Exception:
                    continue

            dummy_id = int(CONFIG.get("TRAIN_13_4_DUMMY_TEAM_ID", 1))
            first_train_id = int(CONFIG.get("TRAIN_13_4_FIRST_TEAM_ID", 2))
            train_ids = list(range(first_train_id, first_train_id + expected))

            if dummy_id not in team_by_id:
                print("[AUTO] 13-4 练级梯队校验失败：未解析到梯队%s。" % dummy_id)
                print("[AUTO] 13-4 练级要求梯队1为单人占位队，不参与练级。")
                return False

            dummy_guns = team_by_id[dummy_id].get("guns", [])
            if len(dummy_guns) != 1:
                print("[AUTO] 13-4 练级梯队校验失败：梯队%s 必须为单人人形占位队。" % dummy_id)
                print("[AUTO] 当前梯队%s 人形数量：%s" % (dummy_id, len(dummy_guns)))
                return False

            missing = [tid for tid in train_ids if tid not in team_by_id]
            empty = [tid for tid in train_ids if tid in team_by_id and not team_by_id[tid].get("guns")]
            if missing or empty:
                print("[AUTO] 13-4 练级梯队校验失败：从梯队2开始需要解析到指定数量的练级梯队。")
                if missing:
                    print("[AUTO] 未解析到练级梯队：%s" % missing)
                if empty:
                    print("[AUTO] 空练级梯队：%s" % empty)
                print("[AUTO] 请确认梯队1为单人占位队，梯队2起为实际练级队后，重新输入 -a。")
                return False

            for tid in train_ids:
                team_cfg = team_by_id[tid]
                CAPTURED_TEAM_CONFIGS.append({
                    "team_id": team_cfg["team_id"],
                    "fairy_id": team_cfg["fairy_id"],
                    "fairy": copy.deepcopy(team_cfg.get("fairy")),
                    "guns": copy.deepcopy(team_cfg["guns"]),
                    "runtime_seconds": 0.0,
                    "completed": False,
                    "dummy_team_id": dummy_id,
                })

            if CAPTURED_TEAM_CONFIGS:
                CONFIG["TEAM_ID"] = CAPTURED_TEAM_CONFIGS[0]["team_id"]
                CONFIG["FAIRY_ID"] = CAPTURED_TEAM_CONFIGS[0]["fairy_id"]
                CONFIG["FAIRY"] = copy.deepcopy(CAPTURED_TEAM_CONFIGS[0].get("fairy"))
                CONFIG["GUNS"] = copy.deepcopy(CAPTURED_TEAM_CONFIGS[0]["guns"])
            CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = len(CAPTURED_TEAM_CONFIGS) + 1
        else:
            selected = teams[:expected]
            for team_cfg in selected:
                CAPTURED_TEAM_CONFIGS.append({
                    "team_id": team_cfg["team_id"],
                    "fairy_id": team_cfg["fairy_id"],
                    "fairy": copy.deepcopy(team_cfg.get("fairy")),
                    "guns": copy.deepcopy(team_cfg["guns"]),
                    "runtime_seconds": 0.0,
                    "completed": False,
                })
            if CAPTURED_TEAM_CONFIGS:
                CONFIG["TEAM_ID"] = CAPTURED_TEAM_CONFIGS[0]["team_id"]
                CONFIG["FAIRY_ID"] = CAPTURED_TEAM_CONFIGS[0]["fairy_id"]
                CONFIG["FAIRY"] = copy.deepcopy(CAPTURED_TEAM_CONFIGS[0].get("fairy"))
                CONFIG["GUNS"] = copy.deepcopy(CAPTURED_TEAM_CONFIGS[0]["guns"])
            CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = len(CAPTURED_TEAM_CONFIGS)
    else:
        first_team = teams[0]
        CAPTURED_TEAM_CONFIGS.append({
            "team_id": first_team["team_id"],
            "fairy_id": first_team["fairy_id"],
            "fairy": copy.deepcopy(first_team.get("fairy")),
            "guns": copy.deepcopy(first_team["guns"]),
            "runtime_seconds": 0.0,
            "completed": False,
        })
        CONFIG["TEAM_ID"] = first_team["team_id"]
        CONFIG["FAIRY_ID"] = first_team["fairy_id"]
        CONFIG["FAIRY"] = copy.deepcopy(first_team.get("fairy"))
        CONFIG["GUNS"] = copy.deepcopy(first_team["guns"])
        CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 1

    user_info = payload.get("user_info", {})
    if isinstance(user_info, dict):
        user_id = user_info.get("user_id")
        try:
            user_id = str(int(user_id))
            if user_id:
                CONFIG["USER_UID"] = user_id
        except Exception:
            pass

    AUTO_CAPTURE_STATE["completed"] = True
    return True




def int_safe(value, default=0):
    """安全转 int，避免 Index/index 中字符串数字或空值导致异常。"""
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default

def get_basic_resource_inventory_from_index_payload(payload: dict):
    """从 Index/index 的 user_info 中读取四项基础资源库存。"""
    user_info = payload.get("user_info", {}) if isinstance(payload, dict) else {}
    return {
        "mp": int_safe(user_info.get("mp", 0), 0),
        "ammo": int_safe(user_info.get("ammo", 0), 0),
        "mre": int_safe(user_info.get("mre", 0), 0),
        "part": int_safe(user_info.get("part", 0), 0),
    }


def save_13_4_resource_start_inventory_from_index(payload: dict):
    """13-4 资源打捞使用 -a 阶段已有的 Index/index 作为起始库存，不额外请求。"""
    inv = get_basic_resource_inventory_from_index_payload(payload)
    CONFIG["RESOURCE_13_4_START_INVENTORY"] = dict(inv)
    RUN_STATS["resource_start_inventory"] = dict(inv)
    return inv


def format_resource_inventory(inv: dict):
    if not inv:
        return "未记录"
    return " / ".join("%s %s" % (BASIC_RESOURCE_LABELS.get(k, k), int_safe(inv.get(k), 0)) for k in BASIC_RESOURCE_KEYS)


def finalize_13_4_resource_summary_from_index(client: GFLClient):
    """
    13-4 资源打捞结束后只请求一次 Index/index，
    用结束库存 - 起始库存计算真实资源收益与效率。
    """
    if not is_13_4_resource_farm_stage():
        return False

    start_inv = dict(CONFIG.get("RESOURCE_13_4_START_INVENTORY") or RUN_STATS.get("resource_start_inventory") or {})
    if not start_inv:
        panel_safe_print("[资源统计] 未找到起始库存记录，无法准确计算资源收益。请确认运行前已经通过 -a 主动请求过 Index/index。")

    panel_safe_print("[资源统计] 正在请求一次 Index/index，用于计算本次 13-4 资源收益……")
    payload = {
        "time": int(time.time()),
        "furniture_data": False
    }
    resp = client.send_request(API_INDEX_INDEX, payload)
    if check_step_error(resp, "Index/index(资源结算)") or not isinstance(resp, dict):
        panel_safe_print("[资源统计] 结束库存同步失败，无法计算资源收益。")
        return False

    end_inv = get_basic_resource_inventory_from_index_payload(resp)
    CONFIG["RESOURCE_13_4_END_INVENTORY"] = dict(end_inv)
    RUN_STATS["resource_end_inventory"] = dict(end_inv)

    gained = {}
    for key in BASIC_RESOURCE_KEYS:
        if start_inv:
            gained[key] = int_safe(end_inv.get(key), 0) - int_safe(start_inv.get(key), 0)
        else:
            gained[key] = 0
    RUN_STATS["resource_gained"] = dict(gained)

    duration = 0
    if RUN_STATS.get("start_time") is not None:
        duration = max(0, time.time() - RUN_STATS.get("start_time"))
    hours = duration / 3600 if duration > 0 else 0
    efficiency = {}
    for key in BASIC_RESOURCE_KEYS:
        efficiency[key] = int(gained.get(key, 0) / hours) if hours > 0 else 0
    RUN_STATS["resource_efficiency_per_hour"] = efficiency

    panel_safe_print("[资源统计] 起始库存：%s" % format_resource_inventory(start_inv))
    panel_safe_print("[资源统计] 结束库存：%s" % format_resource_inventory(end_inv))
    panel_safe_print("[资源统计] 本次获得：%s" % format_resource_inventory(gained))
    panel_safe_print("[资源统计] 每小时效率：%s" % format_resource_inventory(efficiency))
    return True


def has_usable_dynamic_keys() -> bool:
    uid = str(CONFIG.get("USER_UID", "")).strip()
    sign = str(CONFIG.get("SIGN_KEY", "")).strip()
    if not uid or uid == "0":
        return False
    if not sign or sign == DEFAULT_SIGN:
        return False
    return True


def request_index_and_prepare_configs():
    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] SIGN_KEY 为默认值，请先运行 -a 抓取 UID/SIGN。")
        return False

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    print("[*] 正在主动请求 Index/index……")
    payload = {
        "time": int(time.time()),
        "furniture_data": False
    }

    response = client.send_request(API_INDEX_INDEX, payload)

    if isinstance(response, dict) and "error_local" in response:
        print("[-] Index/index 本地错误: %s" % response["error_local"])
        print("    原始响应：'%s'" % response.get("raw", "N/A"))
        return False

    if isinstance(response, dict) and "error" in response:
        print("[-] Index/index 服务器错误: %s" % response["error"])
        return False

    if not isinstance(response, dict):
        print("[!] Index/index 返回格式异常。")
        return False

    try:
        with open("index_debug.json", "w", encoding="utf-8") as f:
            json.dump(response, f, indent=4, ensure_ascii=False)
        print("[*] 已保存 Index/index 响应到 index_debug.json")
    except Exception as e:
        print("[!] 保存 index_debug.json 失败：%s" % e)

    if is_13_4_resource_farm_stage() or CONFIG.get("MODE_NAME") == "resource134":
        inv = save_13_4_resource_start_inventory_from_index(response)
        print("[资源统计] 已记录 13-4 起始资源库存：%s" % format_resource_inventory(inv))

    if not try_update_auto_capture_from_index_payload(response):
        print("[!] 已请求 Index/index，但未解析出有效梯队。")
        preview = str(response)[:300]
        print("    Parsed JSON preview: %s..." % preview)
        print("    请把 index_debug.json 发给我，我可以继续精确修正解析逻辑。")
        return False

    apply_auto_capture_to_config()
    if CONFIG.get("MODE_NAME") == "resource134":
        print("\n[AUTO] 已主动请求并解析 Index/index。")
        print("[AUTO] 13-4 双单人资源打捞固定梯队校验通过：")
        for team_cfg in CAPTURED_TEAM_CONFIGS:
            print("[AUTO] 梯队%s -> FAIRY_ID=%s | GUNS=%s" % (
                team_cfg["team_id"],
                team_cfg["fairy_id"],
                team_cfg["guns"],
            ))
        print("[AUTO] 运行时将部署梯队1@91263、梯队2@91297，并只移动梯队1。")
    elif CONFIG.get("MODE_NAME") == "team":
        print("\n[AUTO] 已主动请求并解析 Index/index。")
        if CONFIG.get("TRAIN_13_4_MODE"):
            print("[AUTO] 13-4 五战练级校验通过：梯队1为单人占位队，不参与练级。")
            print("[AUTO] 共解析出 %d 个实际练级梯队（从梯队2开始）：" % len(CAPTURED_TEAM_CONFIGS))
            for idx, team_cfg in enumerate(CAPTURED_TEAM_CONFIGS, start=1):
                print("[AUTO] 练级序号%d -> TEAM_ID=%s | FAIRY_ID=%s | GUNS=%s" % (
                    idx,
                    team_cfg["team_id"],
                    team_cfg["fairy_id"],
                    team_cfg["guns"],
                ))
            print("[AUTO] 运行时将部署：当前练级队@91263 + 梯队1占位@91297，并只移动当前练级队。")
        else:
            print("[AUTO] 共解析出 %d 个有效练级梯队：" % len(CAPTURED_TEAM_CONFIGS))
            for idx, team_cfg in enumerate(CAPTURED_TEAM_CONFIGS, start=1):
                print("[AUTO] 梯队%d -> TEAM_ID=%s | FAIRY_ID=%s | GUNS=%s" % (
                    idx,
                    team_cfg["team_id"],
                    team_cfg["fairy_id"],
                    team_cfg["guns"],
                ))
            print("[AUTO] 将默认从梯队一开始轮转。")
    else:
        print("\n[AUTO] 已主动请求并解析 Index/index。")
        print("[AUTO] TEAM_ID  = %s" % CONFIG["TEAM_ID"])
        print("[AUTO] FAIRY_ID = %s" % CONFIG["FAIRY_ID"])
        print("[AUTO] GUNS     = %s" % CONFIG["GUNS"])
        if not validate_captured_team_for_mode():
            return False

    MENU_STATE["selection_unlocked"] = True
    reset_selection_menu()
    print_main_menu()
    print_difficulty_menu()
    return True


def collect_keyed_values(obj, target_key: str):
    results = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k) == target_key:
                    results.append(v)
                walk(v)
        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(obj)
    return results


def collect_gun_entries(obj):
    guns = []

    def walk(x):
        if isinstance(x, dict):
            if "id" in x and "life" in x:
                gun_id = x.get("id")
                life = x.get("life")
                if isinstance(gun_id, int) and isinstance(life, int):
                    guns.append({"id": gun_id, "life": life})
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(obj)

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for gun in guns:
        key = (gun["id"], gun["life"])
        if key not in seen:
            seen.add(key)
            deduped.append(gun)
    return deduped


def try_update_auto_capture_from_payload(url: str, payload):
    # 新流程不再依赖被动抓取 TEAM_ID / FAIRY_ID / GUNS。
    # 这里只保留函数壳，避免旧调用报错。
    return False


def apply_auto_capture_to_config():
    if CONFIG.get("MODE_NAME") in ("team", "resource134"):
        if CAPTURED_TEAM_CONFIGS:
            CONFIG["TEAM_ID"] = CAPTURED_TEAM_CONFIGS[0]["team_id"]
            CONFIG["FAIRY_ID"] = CAPTURED_TEAM_CONFIGS[0]["fairy_id"]
            CONFIG["GUNS"] = copy.deepcopy(CAPTURED_TEAM_CONFIGS[0]["guns"])
    else:
        if AUTO_CAPTURE_STATE["team_id"] is not None:
            CONFIG["TEAM_ID"] = AUTO_CAPTURE_STATE["team_id"]
        if AUTO_CAPTURE_STATE["fairy_id"] is not None:
            CONFIG["FAIRY_ID"] = AUTO_CAPTURE_STATE["fairy_id"]
        if AUTO_CAPTURE_STATE["guns"]:
            CONFIG["GUNS"] = copy.deepcopy(AUTO_CAPTURE_STATE["guns"])


def stop_proxy_instance():
    global proxy_instance, worker_mode
    if proxy_instance:
        proxy_instance.stop()
        set_windows_proxy(False)
        proxy_instance = None
    worker_mode = None


def maybe_finish_auto_capture():
    return

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

def normalize_menu_input(cmd: str) -> str:
    raw = (cmd or "").strip()
    lower = raw.lower()

    alias_map = {
        "b": "-back",
        "back": "-back",

        "p": "普通",
        "普": "普通",
        "normal": "普通",

        "j": "紧急",
        "紧": "紧急",
        "urgent": "紧急",
        "em": "紧急",

        "y": "夜战",
        "夜": "夜战",
        "night": "夜战",

        "team": "-team",
        "t": "-team",
        "single": "-single",
        "s1": "-single",

        "full": "-full",
        "f": "-full",
        "equal": "-equal",
        "e": "-equal",

        "protecton": "-protecton",
        "on": "-protecton",
        "po": "-protecton",

        "protectoff": "-protectoff",
        "off": "-protectoff",
        "pf": "-protectoff",

        "stopmax": "-stopmax",
        "sm": "-stopmax",
        "stop": "-stopmax",

        "keepmax": "-keepmax",
        "km": "-keepmax",
        "keep": "-keepmax",

        # 13-4 练级快捷入口
        "13-4": "13-4",
        "134": "13-4",
        "13_4": "13-4",
        "13.4": "13-4",
        "train134": "13-4",
        "练级13-4": "13-4",
        "13-4练级": "13-4",
        "resource134": "13-4",
        "res134": "13-4",
        "资源13-4": "13-4",
        "13-4资源": "13-4",
        "13-4打捞": "13-4",
        "-134": "-134",
        "134mode": "-134",
        "resource134mode": "-134",
        "资源模式13-4": "-134",
    }

    if lower in alias_map:
        return alias_map[lower]

    # A1 / a1 -> A-1
    if re.fullmatch(r"[aA]\d{1,2}", raw):
        return "A-" + raw[1:]

    # 1 / 2 / 3 / 4 / 5 -> -1 / -2 / ...
    if re.fullmatch(r"\d+", raw):
        return "-" + raw

    return raw


def print_difficulty_menu():
    print("\n=========== EN 13-4 关卡菜单 ===========")
    print("当前仅开放：")
    print("  13-4   （-134train 为练级；-134 为四项基础资源打捞）")
    print("------------------------------------")
    print("提示：输入 13-4 / 134 选择关卡")
    print("====================================\n")

def print_stage_menu(difficulty: str):
    if difficulty == "普通":
        options = NORMAL_STAGE_OPTIONS
    elif difficulty == "紧急":
        options = EMERGENCY_STAGE_OPTIONS
    else:
        options = NIGHT_STAGE_OPTIONS

    print("\n=========== %s 关卡列表 ===========" % difficulty)
    print("请选择关卡：")
    print("  " + "  ".join(options))
    print("------------------------------------")
    print("提示：输入选项名称并回车，例如：A-10")
    print("提示：也可输入别名，例如：a10 / A10")
    print("提示：输入 -back 或 b 返回难度选择菜单")
    print("====================================\n")


def print_placeholder_menu(difficulty: str, stage: str):
    print("\n[!] %s %s 菜单暂未实现，当前先占位。" % (difficulty, stage))
    if difficulty == "夜战":
        print("[!] 夜战已接入装备掉落统计逻辑，但当前尚未写入该关的 MISSION_ID / START_SPOT / ROUTE / 目标装备。")
    else:
        print("[!] 你可以重新选择其他关卡，或等待后续继续补全。")


def print_target_menu(difficulty: str, stage: str):
    options = get_stage_options(difficulty, stage)
    print("\n=========== %s %s ===========" % (difficulty, stage))
    print("请选择你要打捞的目标：")
    if difficulty == "夜战":
        print("（夜战目标为装备）")
        print("（说明：夜战目前仅支持自动打捞，暂不支持自动拆解）")
    for key, item in options.items():
        print("  %s : %s" % (key, item["label"]))
    print("---------------------------------")
    print("提示：输入对应编号并回车，例如：-1")
    print("提示：也可直接输入数字，例如：1")
    print("提示：输入 -back 或 b 返回上一级菜单")
    print("=================================\n")


def print_ready_to_run_hint():
    print("[*] 选择已完成，请确认后开始运行。")



def print_filter_protection_menu():
    print("\n=========== 过滤保护 ===========")
    print("  -protecton  : 开启（默认）")
    print("  -protectoff : 关闭")
    print("--------------------------------")
    print("提示：练级模式下关闭后，可减少目标掉落占仓导致的中断。")
    print("================================")


def print_run_confirm_menu():
    print("\n=========== 运行前确认 ===========")
    print("关卡：%s %s -> %s" % (
        CONFIG["SELECTED_DIFFICULTY"],
        CONFIG["SELECTED_STAGE"],
        CONFIG["SELECTED_TARGET_LABEL"],
    ))
    if is_13_4_resource_farm_stage():
        print("模式：13-4 双单人五战资源打捞")
    else:
        print("模式：%s" % ("打捞单人模式" if CONFIG.get("SINGLE_GUN_MODE") else "练级五人模式"))
    if CONFIG.get("MODE_NAME") == "team":
        schedule_label = "整队满级后切换" if CONFIG.get("TRAIN_SCHEDULE_MODE") == "full" else "均等练级轮转"
        print("调度：%s" % schedule_label)
    print("满级停机：%s" % ("开启" if CONFIG.get("STOP_ON_MAX_LEVEL") else "关闭"))
    if CONFIG.get("MODE_NAME") == "single" and CONFIG.get("SELECTED_DIFFICULTY") != "夜战" and not is_13_4_resource_farm_stage():
        print("目标达成停机：%s" % ("开启" if CONFIG.get("STOP_AFTER_EACH_TARGET_DROPPED") else "关闭"))
    print("----------------------------------")
    print("输入 -y 确认，输入 -back 返回")
    print("==================================\n")


def print_stop_on_max_menu():
    print("\n=========== 满级停机设置 ===========")
    print("请选择当检测到人形 EXP 为 0（满级）后的行为：")
    print("  -stopmax : 停止程序")
    print("  -keepmax : 不停止程序")
    print("------------------------------------")
    print("提示：只能输入 -stopmax 或 -keepmax")
    print("====================================\n")



def print_target_drop_stop_menu():
    print("\n=========== 目标达成停机 ===========")
    print("请选择目标人形至少各掉落 1 个后的行为：")
    print("  -stopdrop : 停止打捞")
    print("  -keepdrop : 继续打捞（默认）")
    print("------------------------------------")
    print("说明：仅对打捞单人模式的人形目标生效。")
    print("提示：输入 -stopdrop / -keepdrop，回车默认 -keepdrop")
    print("====================================\n")



def get_selected_protected_gun_ids():
    if not CONFIG.get("ENABLE_FILTER_PROTECTION", True):
        return set()

    protected_ids = set(CONFIG.get("PROTECTED_DROP_GUN_IDS", []))
    label = CONFIG.get("SELECTED_TARGET_LABEL")
    if label:
        for name in split_target_label(label):
            gun_id = resolve_gun_id_by_name(name)
            if gun_id is not None:
                protected_ids.add(gun_id)
    return protected_ids


def get_selected_target_equip_ids():
    # 夜战自动拆解功能暂未启用，当前不使用装备保护列表。
    return set()


def is_no_space_retire_failure(resp) -> bool:
    text_blob = str(resp).lower()
    keywords = [
        "full", "space", "capacity", "inventory",
        "仓库", "满", "空间", "容量", "上限", "空位"
    ]
    return any(k in text_blob for k in keywords)


def reset_run_stats():
    RUN_STATS["start_time"] = None
    RUN_STATS["end_time"] = None
    RUN_STATS["target_counts"] = {}
    RUN_STATS["resource_counts"] = {key: 0 for key in BASIC_RESOURCE_KEYS}
    RUN_STATS["target_type"] = "gun"
    RUN_STATS["current_macro"] = 0
    RUN_STATS["current_micro"] = 0
    RUN_STATS["current_step"] = 0
    RUN_STATS["current_team_no"] = 1
    RUN_STATS["macro_drop_names"] = []
    RUN_STATS["last_micro_exp_lines"] = []
    RUN_STATS["panel_enabled"] = True
    RUN_STATS["recent_logs"] = []
    RUN_STATS["drop_marquee_offset"] = 0
    RUN_STATS["drop_marquee_last_key"] = ""
    RUN_STATS["resource_start_inventory"] = dict(CONFIG.get("RESOURCE_13_4_START_INVENTORY") or {})
    RUN_STATS["resource_end_inventory"] = {}
    RUN_STATS["resource_gained"] = {}
    RUN_STATS["resource_efficiency_per_hour"] = {}
    RUN_STATS["completed_resource_runs"] = 0



def get_selected_target_pairs():
    label = CONFIG.get("SELECTED_TARGET_LABEL", "")
    pairs = []
    if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
        for name in split_target_label(label):
            equip_id = resolve_equip_id_by_name(name)
            if equip_id is not None:
                pairs.append((name, equip_id))
        return pairs

    for name in split_target_label(label):
        gun_id = resolve_gun_id_by_name(name)
        if gun_id is not None:
            pairs.append((name, gun_id))
    return pairs


def init_run_target_counts():
    RUN_STATS["target_counts"] = {}
    RUN_STATS["resource_counts"] = {key: 0 for key in BASIC_RESOURCE_KEYS}
    if is_13_4_resource_farm_stage():
        RUN_STATS["target_type"] = "resource"
        return
    RUN_STATS["target_type"] = "equip" if CONFIG.get("SELECTED_DIFFICULTY") == "夜战" else "gun"
    for name, item_id in get_selected_target_pairs():
        RUN_STATS["target_counts"][name] = {"item_id": item_id, "count": 0}


def extract_basic_resource_rewards(obj):
    """递归提取四项基础资源奖励：mp/ammo/mre/part。"""
    rewards = {key: 0 for key in BASIC_RESOURCE_KEYS}

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                key = str(k)
                if key in rewards:
                    try:
                        rewards[key] += int(v)
                    except Exception:
                        pass
                else:
                    walk(v)
        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(obj)
    return {k: v for k, v in rewards.items() if v}


def record_basic_resource_rewards(resp_data):
    # 13-4 四项基础资源的有效收益以结束时 Index/index 库存差为准。
    # battleFinish/endTurn 返回中不稳定或可能不含真实库存变化，因此运行中不再显示“资源累计”。
    return {}


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




def has_each_target_dropped_once():
    if not RUN_STATS.get("target_counts"):
        return False
    return all(int(item.get("count", 0)) >= 1 for item in RUN_STATS["target_counts"].values())


def get_target_drop_progress_text():
    if is_13_4_resource_farm_stage():
        return "结束后通过 Index/index 统计四项基础资源"
    if not RUN_STATS.get("target_counts"):
        return "未配置"
    return "，".join("%s×%d" % (name, int(item.get("count", 0))) for name, item in RUN_STATS["target_counts"].items())


def should_stop_after_each_target_dropped():
    if not CONFIG.get("STOP_AFTER_EACH_TARGET_DROPPED", False):
        return False
    if CONFIG.get("MODE_NAME") != "single":
        return False
    if RUN_STATS.get("target_type") != "gun":
        return False
    return has_each_target_dropped_once()




def get_terminal_width(default=120):
    try:
        import shutil
        return max(60, shutil.get_terminal_size(fallback=(default, 30)).columns)
    except Exception:
        return default


def strip_ansi(text):
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", str(text))


def trim_ansi_line(text, max_width):
    s = str(text)
    if len(strip_ansi(s)) <= max_width:
        return s
    plain = strip_ansi(s)
    keep = max(10, max_width - 3)
    return plain[:keep] + "..."


def build_drop_marquee_segment(items, visible_width):
    if not items:
        return "无"

    parts = [format_drop_name_for_display(x) for x in items]
    plain_parts = [strip_ansi(x) for x in parts]
    joined_plain = "   ".join(plain_parts)
    if len(joined_plain) <= visible_width:
        return "   ".join(parts)

    key = "|".join(plain_parts)
    if RUN_STATS.get("drop_marquee_last_key") != key:
        RUN_STATS["drop_marquee_last_key"] = key
        RUN_STATS["drop_marquee_offset"] = 0

    count = len(parts)
    offset = RUN_STATS.get("drop_marquee_offset", 0) % max(1, count)
    RUN_STATS["drop_marquee_offset"] = (offset + 1) % max(1, count)

    ordered = parts[offset:] + parts[:offset]
    rendered = []
    used = 0
    for idx, part in enumerate(ordered):
        plain = strip_ansi(part)
        sep = "   " if idx > 0 else ""
        extra = len(sep) + len(plain)
        if rendered and used + extra > visible_width:
            break
        if not rendered and len(plain) > visible_width:
            return trim_ansi_line(part, visible_width)
        if sep:
            rendered.append(sep)
            used += len(sep)
        rendered.append(part)
        used += len(plain)

    if not rendered:
        return trim_ansi_line(ordered[0], visible_width)
    return "".join(rendered)



GUN_EXP_1_TO_100 = {
    1:100,2:200,3:300,4:400,5:500,6:600,7:700,8:800,9:900,10:1000,
    11:1100,12:1200,13:1300,14:1400,15:1500,16:1600,17:1700,18:1800,19:1900,20:2000,
    21:2100,22:2200,23:2300,24:2400,25:2500,26:2600,27:2800,28:3100,29:3400,30:4200,
    31:4600,32:5000,33:5400,34:5800,35:6300,36:6700,37:7200,38:7700,39:8200,40:8800,
    41:9300,42:9900,43:10500,44:11100,45:11800,46:12500,47:13100,48:13900,49:14600,50:15400,
    51:16100,52:16900,53:17800,54:18600,55:19500,56:20400,57:21300,58:22300,59:23300,60:24300,
    61:25300,62:26300,63:27400,64:28500,65:29600,66:30800,67:32000,68:33200,69:34400,70:45100,
    71:46800,72:48600,73:50400,74:52200,75:54000,76:55900,77:57900,78:59800,79:61800,80:63900,
    81:66000,82:68100,83:70300,84:72600,85:74800,86:77100,87:79500,88:81900,89:84300,90:112600,
    91:116100,92:119500,93:123100,94:126700,95:130400,96:134100,97:137900,98:141800,99:145700,
}
GUN_EXP_100_TO_120 = {
    100:100000,101:120000,102:140000,103:160000,104:180000,
    105:200000,106:220000,107:240000,108:280000,109:360000,
    110:480000,111:640000,112:900000,113:1200000,114:1600000,
    115:2200000,116:3000000,117:4000000,118:5000000,119:6000000,
}
FAIRY_EXP_1_TO_100 = {
    1:300,2:600,3:900,4:1200,5:1500,6:1800,7:2100,8:2400,9:2700,10:3000,
    11:3300,12:3600,13:3900,14:4200,15:4500,16:4800,17:5100,18:5500,19:6000,20:6500,
    21:7100,22:8000,23:9000,24:10000,25:11000,26:12200,27:13400,28:14700,29:16000,30:17500,
    31:18900,32:20500,33:22200,34:23900,35:25700,36:27600,37:29500,38:31600,39:33700,40:35900,
    41:38200,42:40500,43:43000,44:45500,45:48200,46:50900,47:53700,48:56600,49:59600,50:62700,
    51:65900,52:69200,53:72600,54:76000,55:79600,56:83300,57:87000,58:90900,59:94900,60:99000,
    61:103100,62:107400,63:111800,64:116300,65:120900,66:125600,67:130400,68:135300,69:140400,70:145500,
    71:150800,72:156100,73:161600,74:167200,75:172900,76:178700,77:184700,78:190700,79:196900,80:203200,
    81:209600,82:216100,83:222800,84:229600,85:236500,86:243500,87:250600,88:257900,89:265300,90:272800,
    91:280400,92:288200,93:296100,94:304100,95:312300,96:320600,97:329000,98:337500,99:357000,
}

def sum_exp_range(table, start_level, end_level_exclusive):
    total = 0
    for lv in range(start_level, end_level_exclusive):
        total += int(table.get(lv, 0))
    return total

def gun_total_exp_for_level(level, intra_exp=0):
    try:
        level = int(level)
    except Exception:
        level = 1
    try:
        intra_exp = int(intra_exp)
    except Exception:
        intra_exp = 0
    total = 0
    upper = min(level, 100)
    total += sum_exp_range(GUN_EXP_1_TO_100, 1, upper)
    if level > 100:
        total += sum_exp_range(GUN_EXP_100_TO_120, 100, min(level, 120))
    return total + max(0, intra_exp)

def gun_next_level_required_exp(level):
    try:
        level = int(level)
    except Exception:
        return 0
    if 1 <= level < 100:
        return int(GUN_EXP_1_TO_100.get(level, 0) or 0)
    if 100 <= level < 120:
        return int(GUN_EXP_100_TO_120.get(level, 0) or 0)
    return 0


def gun_base_total_exp_from_index(level, raw_exp):
    """
    Index/index 里的 gun_exp 在实际返回中更接近“累计总经验”，
    而不是“当前等级内经验”。如果继续把它当作等级内经验相加，
    99 级人形会被错误算到 100%。
    这里做兼容：
    - raw_exp 大于当前等级升下一级所需经验时，按累计总经验处理；
    - 否则按当前等级内经验处理。
    """
    try:
        level = int(level)
    except Exception:
        level = 1
    try:
        raw_exp = int(raw_exp)
    except Exception:
        raw_exp = 0

    next_need = gun_next_level_required_exp(level)
    total_1_to_100 = sum_exp_range(GUN_EXP_1_TO_100, 1, 100)
    if raw_exp > next_need or raw_exp >= total_1_to_100:
        return max(0, raw_exp)

    return gun_total_exp_for_level(level, raw_exp)


def fairy_total_exp_for_level(level, intra_exp=0):
    try:
        level = int(level)
    except Exception:
        level = 1
    try:
        intra_exp = int(intra_exp)
    except Exception:
        intra_exp = 0
    total = sum_exp_range(FAIRY_EXP_1_TO_100, 1, min(level, 100))
    return total + max(0, intra_exp)

def fairy_next_level_required_exp(level):
    try:
        level = int(level)
    except Exception:
        return 0
    if 1 <= level < 100:
        return int(FAIRY_EXP_1_TO_100.get(level, 0) or 0)
    return 0


def fairy_base_total_exp_from_index(level, raw_exp):
    """
    Index/index 里的 fairy_exp 可能是“累计总经验”，也可能是“当前等级内经验”。
    妖精等级已知时，累计总经验必须落在：
        当前等级累计下限 <= fairy_exp < 下一等级累计下限
    如果 raw_exp 超出该等级可能范围，不直接拿来当累计值，避免 92 级妖精被算成 100%。
    """
    try:
        level = int(level)
    except Exception:
        level = 1
    try:
        raw_exp = int(raw_exp)
    except Exception:
        raw_exp = 0

    total_1_to_100 = sum_exp_range(FAIRY_EXP_1_TO_100, 1, 100)
    level = max(1, min(level, 100))
    level_floor = sum_exp_range(FAIRY_EXP_1_TO_100, 1, level)

    if level >= 100:
        return total_1_to_100

    next_need = fairy_next_level_required_exp(level)
    next_floor = min(total_1_to_100, level_floor + next_need)

    # 形态一：fairy_exp 是累计总经验。
    if level_floor <= raw_exp < next_floor:
        return raw_exp

    # 形态二：fairy_exp 是当前等级内经验。
    if 0 <= raw_exp <= next_need:
        return level_floor + raw_exp

    # 超出当前等级可能范围时，保守使用当前等级下限，避免异常满进度。
    return level_floor


def infer_gun_target_level(gun):
    # Best-effort: if current level already passed a mind-update cap, preserve that cap family.
    level = int(gun.get("level", gun.get("gun_level", 1)) or 1)
    explicit = gun.get("target_level") or gun.get("max_level")
    if explicit:
        try:
            explicit = int(explicit)
            if explicit in (100,110,115,120):
                return explicit
        except Exception:
            pass
    if level > 115:
        return 120
    if level > 110:
        return 115
    if level > 100:
        return 110
    return 100

def infer_fairy_target_level(fairy):
    return 100

def init_team_progress_runtime_fields(team_cfg):
    for gun in team_cfg.get("guns", []):
        level = int(gun.get("level", gun.get("gun_level", 1)) or 1)
        exp = int(gun.get("exp", gun.get("gun_exp", 0)) or 0)
        target_level = infer_gun_target_level(gun)
        gun["level"] = level
        gun["exp"] = exp
        gun["target_level"] = target_level
        gun["base_total_exp"] = gun_base_total_exp_from_index(level, exp)
        gun["runtime_gained_exp"] = int(gun.get("runtime_gained_exp", 0) or 0)
        gun["target_total_exp"] = gun_total_exp_for_level(target_level, 0)
    fairy = team_cfg.get("fairy")
    if isinstance(fairy, dict):
        level = int(fairy.get("level", fairy.get("fairy_lv", 1)) or 1)
        exp = int(fairy.get("exp", fairy.get("fairy_exp", 0)) or 0)
        fairy["level"] = level
        fairy["exp"] = exp
        fairy["target_level"] = infer_fairy_target_level(fairy)
        fairy["base_total_exp"] = fairy_base_total_exp_from_index(level, exp)
        fairy["runtime_gained_exp"] = int(fairy.get("runtime_gained_exp", 0) or 0)
        fairy["target_total_exp"] = fairy_total_exp_for_level(fairy["target_level"], 0)
        fairy["last_total_exp_seen"] = int(fairy.get("last_total_exp_seen", fairy["base_total_exp"]) or fairy["base_total_exp"])
    team_cfg.setdefault("runtime_seconds", 0.0)
    team_cfg.setdefault("completed", False)
    team_cfg.setdefault("maxed_member_uids", set())
    team_cfg.setdefault("warned_max_member_uids", set())

def initialize_all_team_progress():
    for team_cfg in CAPTURED_TEAM_CONFIGS:
        init_team_progress_runtime_fields(team_cfg)
    if not CAPTURED_TEAM_CONFIGS:
        init_team_progress_runtime_fields({"guns": CONFIG.get("GUNS", []), "fairy": CONFIG.get("FAIRY")})

def pause_current_team_runtime():
    team_id = TEAM_PROGRESS_STATE.get("current_active_team_id")
    started_at = TEAM_PROGRESS_STATE.get("current_active_started_at")
    if not team_id or not started_at:
        return
    cfg = get_team_config_by_team_id(team_id)
    if cfg is not None:
        cfg["runtime_seconds"] = float(cfg.get("runtime_seconds", 0.0)) + max(0.0, time.time() - started_at)
    TEAM_PROGRESS_STATE["current_active_started_at"] = None
    TEAM_PROGRESS_STATE["current_active_team_id"] = None

def activate_team_runtime(team_id):
    pause_current_team_runtime()
    TEAM_PROGRESS_STATE["current_active_team_id"] = team_id
    TEAM_PROGRESS_STATE["current_active_started_at"] = time.time()

def get_team_config_by_team_id(team_id):
    for team_cfg in CAPTURED_TEAM_CONFIGS:
        if int(team_cfg.get("team_id", 0)) == int(team_id):
            return team_cfg
    if int(CONFIG.get("TEAM_ID", 0) or 0) == int(team_id):
        return {"team_id": CONFIG.get("TEAM_ID"), "guns": CONFIG.get("GUNS", []), "fairy": CONFIG.get("FAIRY")}
    return None

def get_team_runtime_seconds(team_cfg):
    total = float(team_cfg.get("runtime_seconds", 0.0))
    if TEAM_PROGRESS_STATE.get("current_active_team_id") == int(team_cfg.get("team_id", 0) or 0):
        started = TEAM_PROGRESS_STATE.get("current_active_started_at")
        if started:
            total += max(0.0, time.time() - started)
    return total

def get_team_member_progress(team_cfg):
    guns = team_cfg.get("guns", [])
    maxed_uids = set(str(x) for x in team_cfg.get("maxed_member_uids", set()))

    current_total = 0
    base_total = 0
    target_total = 0

    for g in guns:
        target = int(g.get("target_total_exp", 0))
        base = int(g.get("base_total_exp", 0))
        gained = int(g.get("runtime_gained_exp", 0))
        uid = str(g.get("id", ""))

        base_total += base
        target_total += target

        cur = min(target, base + gained)

        # 服务器返回 EXP=0 才是当前流程里最可靠的“该人形已满级”信号。
        # 如果累计经验已经达到表格上限，但该 UID 仍然在获得 EXP，
        # 说明表格进度已到理论上限，但实际还不能视为满级。
        # 因此未收到 EXP=0 的成员最多显示到 target-1，避免整队提前显示 100%。
        if uid not in maxed_uids and target > 0 and cur >= target:
            cur = target - 1

        current_total += max(0, cur)

    gained_total = max(0, current_total - base_total)
    percent = (current_total / target_total * 100.0) if target_total > 0 else 0.0
    return current_total, target_total, gained_total, percent

def get_team_fairy_progress(team_cfg):
    fairy = team_cfg.get("fairy")
    if not isinstance(fairy, dict):
        return 0, 0, 0.0
    current_total = min(int(fairy.get("target_total_exp",0)), int(fairy.get("base_total_exp",0)) + int(fairy.get("runtime_gained_exp",0)))
    target_total = int(fairy.get("target_total_exp",0))
    percent = (current_total / target_total * 100.0) if target_total > 0 else 0.0
    return current_total, target_total, percent

def estimate_team_eta_seconds(team_cfg):
    current_total, target_total, gained_total, _ = get_team_member_progress(team_cfg)
    runtime_seconds = get_team_runtime_seconds(team_cfg)
    remaining = max(0, target_total - current_total)
    if gained_total <= 0 or runtime_seconds <= 1:
        return None
    exp_per_sec = gained_total / runtime_seconds
    if exp_per_sec <= 0:
        return None
    return remaining / exp_per_sec

def format_percent(value):
    return "%.2f%%" % float(value)

def format_clock_time(ts):
    if ts is None:
        return "-"
    try:
        return time.strftime("%H:%M:%S", time.localtime(ts))
    except Exception:
        return "-"

def format_duration(seconds):
    seconds = int(max(0, seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}小时{m}分{s}秒"
    if m > 0:
        return f"{m}分{s}秒"
    return f"{s}秒"

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



ANSI = {
    "reset": "\033[0m",
    "panel_border": "\033[96m",
    "panel_label": "\033[97m",
    "target": "\033[93m",
    "success": "\033[92m",
    "warn": "\033[91m",
    "dim": "\033[90m",
}

GUN_ID_NAME_CACHE = None

def colorize(text, color_key=None):
    s = str(text)
    if not color_key or color_key not in ANSI:
        return s
    return ANSI[color_key] + s + ANSI["reset"]


def get_gun_id_name_map():
    global GUN_ID_NAME_CACHE
    if GUN_ID_NAME_CACHE is not None:
        return GUN_ID_NAME_CACHE

    mapping = {}
    catalog = load_gun_catalog()
    if not catalog:
        GUN_ID_NAME_CACHE = mapping
        return mapping

    for gun in catalog:
        try:
            gid = int(gun.get("id"))
        except Exception:
            continue
        name = gun.get("en_name") or gun.get("code") or gun.get("name") or str(gid)
        if isinstance(name, str) and name.startswith("gun-"):
            name = gun.get("code") or gun.get("en_name") or name
        mapping[gid] = str(name)
    GUN_ID_NAME_CACHE = mapping
    return mapping


def resolve_gun_name_by_id(gun_id):
    try:
        gun_id = int(gun_id)
    except Exception:
        return str(gun_id)
    return get_gun_id_name_map().get(gun_id, str(gun_id))


def get_target_name_set():
    return set(split_target_label(CONFIG.get("SELECTED_TARGET_LABEL", "")))


def is_target_gun_name(name: str) -> bool:
    if not name:
        return False

    # 不使用子串匹配，避免 G3 被 SSG3000 误判为目标。
    # 优先按 gun_id 判断，其次按名称/别名精确匹配。
    try:
        drop_id = resolve_gun_id_by_name(name)
    except Exception:
        drop_id = None

    target_ids = set()
    for item in RUN_STATS.get("target_counts", {}).values():
        try:
            target_ids.add(int(item.get("item_id")))
        except Exception:
            pass

    if drop_id is not None and int(drop_id) in target_ids:
        return True

    n = normalize_gun_name(name)
    for target in get_target_name_set():
        if n == normalize_gun_name(target):
            return True
        alias = GUN_NAME_ALIAS.get(target)
        if alias and n == normalize_gun_name(alias):
            return True

    return False


def format_drop_name_for_display(name: str):
    if is_target_gun_name(name):
        return colorize(name, "target")
    return str(name)

def _safe_panel_text(value):
    try:
        return str(value)
    except Exception:
        return ""



def build_runtime_panel_lines():
    if not RUN_STATS.get("panel_enabled", True):
        return []

    term_width = get_terminal_width(120)
    inner_width = max(40, term_width - 2)

    if is_13_4_resource_farm_stage():
        mode_label = "13-4双单人资源打捞"
    else:
        mode_label = "练级五人模式" if CONFIG.get("MODE_NAME") == "team" else "打捞单人模式"
    stage_label = "%s %s -> %s" % (
        CONFIG.get("SELECTED_DIFFICULTY") or "-",
        CONFIG.get("SELECTED_STAGE") or "-",
        CONFIG.get("SELECTED_TARGET_LABEL") or "-",
    )
    server_label = CONFIG.get("SERVER_NAME", "SOP")
    elapsed = 0
    if RUN_STATS.get("start_time") is not None:
        elapsed = time.time() - RUN_STATS["start_time"]

    drop_text = "无"
    if RUN_STATS.get("macro_drop_names"):
        drop_text = build_drop_marquee_segment(RUN_STATS["macro_drop_names"], max(20, inner_width - 12))

    exp_text = "无"
    if RUN_STATS.get("last_micro_exp_lines"):
        exp_text = " | ".join(RUN_STATS["last_micro_exp_lines"])

    current_cfg = get_current_team_config()
    member_cur, member_target, member_gained, member_pct = get_team_member_progress(current_cfg)
    fairy_cur, fairy_target, fairy_pct = get_team_fairy_progress(current_cfg)
    team_runtime = get_team_runtime_seconds(current_cfg)
    eta_seconds = estimate_team_eta_seconds(current_cfg)
    eta_text = "-"
    eta_clock = "-"
    if eta_seconds is not None:
        eta_text = format_duration(eta_seconds)
        eta_clock = format_clock_time(time.time() + eta_seconds)

    if CONFIG.get("MODE_NAME") == "team":
        team_label = "%d / %d" % (CONFIG.get("CURRENT_TRAIN_TEAM_INDEX", 0) + 1, max(1, len(CAPTURED_TEAM_CONFIGS)))
        macro_text = "当前 MACRO：%s / 直到全部梯队满级" % RUN_STATS.get("current_macro", 0)
    elif is_13_4_resource_farm_stage():
        team_label = "梯队1+梯队2（移动梯队1）"
        macro_text = "当前 MACRO：%s / 直到手动停止或触发停止条件" % RUN_STATS.get("current_macro", 0)
    else:
        team_label = "1"
        macro_text = "当前 MACRO：%s / 直到手动停止或触发停止条件" % RUN_STATS.get("current_macro", 0)

    raw_lines = [
        colorize("============= EN 13-4 运行状态 =============", "panel_border"),
        "%s%s    %s%s" % (colorize("服务器：", "panel_label"), server_label, colorize("模式：", "panel_label"), mode_label),
        "%s%s" % (colorize("关卡：", "panel_label"), stage_label),
        "%s%s" % (colorize("当前梯队：", "panel_label"), team_label),
        colorize(macro_text, "panel_label"),
        "%s%s / %s | %s%s / %s" % (
            colorize("当前 MICRO：", "panel_label"),
            RUN_STATS.get("current_micro", 0),
            CONFIG.get("MISSIONS_PER_RETIRE", 8),
            colorize("当前 Step：", "panel_label"),
            RUN_STATS.get("current_step", 0),
            max(1, len(CONFIG.get("ROUTE", []) or [])),
        ),
        "%s%s" % (colorize("本轮掉落：", "panel_label"), drop_text),
        "%s%s" % (colorize("目标统计：", "panel_label"), get_target_drop_progress_text()),
        "%s%s" % (colorize("最近一轮经验：", "panel_label"), exp_text),
        "%s%s (%s / %s)" % (colorize("人形进度：", "panel_label"), format_percent(member_pct), f"{member_cur:,}", f"{member_target:,}"),
        "%s%s (%s / %s)" % (colorize("妖精进度：", "panel_label"), format_percent(fairy_pct), f"{fairy_cur:,}", f"{fairy_target:,}"),
        "%s%s" % (colorize("本梯队已运行：", "panel_label"), format_duration(team_runtime)),
        "%s%s 后（%s）" % (colorize("预计完成：", "panel_label"), eta_text, eta_clock),
        "%s%s" % (colorize("总运行时间：", "panel_label"), format_duration(elapsed)),
        colorize("停止：-q 当前 Macro 后停 / -Q 当前 Micro 后停", "dim"),
        colorize("=" * min(inner_width, 37), "panel_border"),
    ]
    lines = [trim_ansi_line(line, inner_width) for line in raw_lines]
    return lines


def clear_runtime_panel():
    try:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    except Exception:
        try:
            os.system("cls" if os.name == "nt" else "clear")
        except Exception:
            pass


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
    max_logs = 10
    if len(buf) > max_logs:
        RUN_STATS["recent_logs"] = buf[-max_logs:]
    refresh_runtime_panel()


def print_run_summary():
    if RUN_STATS["start_time"] is None or RUN_STATS["end_time"] is None:
        return

    duration = RUN_STATS["end_time"] - RUN_STATS["start_time"]
    print("\n=========== 本次运行统计 ===========")
    print("运行总时长：%s" % format_duration(duration))
    if RUN_STATS.get("target_type") == "resource":
        start_inv = RUN_STATS.get("resource_start_inventory") or CONFIG.get("RESOURCE_13_4_START_INVENTORY") or {}
        end_inv = RUN_STATS.get("resource_end_inventory") or CONFIG.get("RESOURCE_13_4_END_INVENTORY") or {}
        gained = RUN_STATS.get("resource_gained") or {}
        efficiency = RUN_STATS.get("resource_efficiency_per_hour") or {}
        print("13-4 四项基础资源统计：")
        print("  起始库存：%s" % format_resource_inventory(start_inv))
        print("  结束库存：%s" % format_resource_inventory(end_inv))
        print("  本次获得：%s" % format_resource_inventory(gained))
        print("  每小时效率：%s" % format_resource_inventory(efficiency))
        print("  完成轮数：%s" % int_safe(RUN_STATS.get("completed_resource_runs"), 0))
    else:
        title = "目标装备掉落" if RUN_STATS.get("target_type") == "equip" else "目标人形掉落"
        if RUN_STATS["target_counts"]:
            print("%s：" % title)
            for name, item in RUN_STATS["target_counts"].items():
                print("  %-12s %d" % (name + "：", item["count"]))
        else:
            print("%s：未配置" % title)
    print("================================\n")


SERVER_MENU_OPTIONS = {
    "-1": "SOP",
    "-2": "RO635",
    "-3": "M4A1",
    "-4": "M16",
    "-5": "AR-15",
}

SERVER_KEY_ALIASES = {
    "EN": ["EN"],
    "SOP": ["SOP"],
}


def print_server_menu():
    print("\n=========== 服务器选择 ===========")
    print("EN 特供版默认使用 EN，同时保留 SOP 方便测试。")
    print("  回车 / EN / 1 : EN（默认）")
    print("  SOP / 2       : SOP（测试用）")
    print("----------------------------------")
    print("如果 gflzirc 没有内置 EN，请在文件顶部 EN_FALLBACK_BASE_URL 填入实际 EN BASE_URL。")
    print("==================================\n")

def normalize_server_input(cmd: str):
    cmd = str(cmd or "").strip()
    if not cmd:
        return "EN"
    cmd_norm = cmd.upper().replace("_", "-")
    if cmd_norm in ("1", "-1", "EN"):
        return "EN"
    if cmd_norm in ("2", "-2", "SOP"):
        return "SOP"
    return None

def apply_server_selection(server_name: str) -> bool:
    server_name = normalize_server_input(server_name)
    if not server_name:
        return False

    candidates = SERVER_KEY_ALIASES.get(server_name, [server_name])
    for key in candidates:
        if key in SERVERS:
            CONFIG["SERVER_NAME"] = server_name
            CONFIG["BASE_URL"] = SERVERS[key]
            print("[+] 已选择服务器：%s" % server_name)
            if server_name == "EN" and SERVERS.get("EN") == SERVERS.get("SOP"):
                print("[!] 当前 EN BASE_URL 与 SOP 相同；若运行失败，请在文件顶部 EN_FALLBACK_BASE_URL 填入实际 EN BASE_URL。")
            return True

    print("[!] 当前 gflzirc 未找到服务器配置：%s" % server_name)
    print("[!] 可用服务器键：%s" % ", ".join(sorted(str(k) for k in SERVERS.keys())))
    return False



def print_gun_mode_menu():
    print("\n=========== EN 13-4 模式 ===========")
    print("  -134train : 13-4 五战练级（梯队1单人占位，从梯队2开始练级）")
    print("  -134      : 13-4 双单人五战资源打捞（固定梯队1+梯队2）")
    print("--------------------------------")
    print("提示：EN 特供版已移除 EPA 活动打捞菜单。")
    print("提示：13-4 练级要求梯队1为单人占位队，实际从梯队2开始练级。")
    print("提示：13-4 资源打捞要求梯队1、梯队2都为单人编队。")
    print("提示：回车默认选择 -134train")
    print("================================\n")

def normalize_gun_mode_input(cmd: str) -> str:
    """编队模式菜单专用输入归一化。

    注意：全局 normalize_menu_input 会把 134 归一化为 13-4，
    那是关卡菜单需要的行为；但在“编队模式”菜单里，134 应该表示 -134。
    因此这里单独处理，避免输入 134 被误判为无效模式。
    """
    raw = str(cmd or "").strip()
    if not raw:
        return "-134train"

    lower = raw.lower().replace("_", "-").replace(" ", "")
    alias_map = {
        "team": "-team",
        "-team": "-team",
        "t": "-team",
        "练级": "-team",

        "134train": "-134train",
        "-134train": "-134train",
        "train134": "-134train",
        "-train134": "-134train",
        "13-4train": "-134train",
        "13-4练级": "-134train",
        "练级13-4": "-134train",
        "134练级": "-134train",

        "single": "-single",
        "-single": "-single",
        "s1": "-single",
        "单人": "-single",
        "打捞": "-single",

        "134": "-134",
        "-134": "-134",
        "13-4": "-134",
        "13.4": "-134",
        "resource134": "-134",
        "resource-134": "-134",
        "res134": "-134",
        "13-4资源": "-134",
        "资源13-4": "-134",
        "13-4打捞": "-134",
        "资源模式13-4": "-134",
    }
    return alias_map.get(lower, raw)


def preset_resource134_mode():
    CONFIG["MODE_NAME"] = "resource134"
    CONFIG["SINGLE_GUN_MODE"] = False
    CONFIG["RESOURCE_FARM_MODE"] = True
    CONFIG["MODE_SELECTED_EARLY"] = True
    CONFIG["TRAIN_TEAM_COUNT"] = 2
    CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 2
    reset_captured_team_configs()
    print("[*] 已预选 13-4 双单人五战资源打捞模式。")
    print("[*] 固定要求：梯队1单人部署 91263；梯队2单人部署 91297；运行时只移动梯队1。")
    print("[*] 现在请输入 -a，程序会保留该模式并进入服务器选择 / UID-SIGN 抓取流程。")


def preset_train134_mode():
    apply_13_4_training_config()
    CONFIG["MODE_SELECTED_EARLY"] = True
    CONFIG["TRAIN_TEAM_COUNT"] = 1
    CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 2  # 梯队1占位 + 至少1个练级队
    reset_captured_team_configs()
    print("[*] 已预选 13-4 五战练级模式。")
    print("[*] 固定要求：梯队1为单人占位队，部署 91297，不参与练级。")
    print("[*] 实际练级从梯队2开始，当前练级队部署 91263 并走五战路线。")
    print("[*] 现在请输入 -a，程序会保留该模式并进入服务器选择 / UID-SIGN 抓取流程。")


def reset_selection_menu():
    MENU_STATE["difficulty"] = None
    MENU_STATE["stage"] = None
    MENU_STATE["awaiting_gun_mode"] = False
    MENU_STATE["awaiting_stop_on_max"] = False
    MENU_STATE["awaiting_target_drop_stop"] = False
    MENU_STATE["awaiting_filter_protection"] = False
    MENU_STATE["awaiting_run_confirm"] = False


def reopen_stage_selection_menu():
    MENU_STATE["selection_unlocked"] = True
    reset_selection_menu()
    print_main_menu()
    print_difficulty_menu()


def validate_captured_team_for_mode() -> bool:
    guns = CONFIG.get("GUNS", []) or []
    if CONFIG.get("MODE_NAME") == "single":
        if len(guns) != 1:
            print("[!] 当前为 single 打捞模式，但本次 Index/index 解析到的梯队人数为 %d 人。" % len(guns))
            print("[!] single 模式要求仅使用梯队1，且梯队1必须配置为单人编队。")
            print("[!] 请前往游戏编队界面，将梯队1调整为仅 1 名人形后，再重新输入 -a 抓取。")
            print("[*] 提示：程序会保留你当前选择的 single 模式。调整好梯队1后，可直接再次输入 -a。")
            return False
        print("[*] single 模式校验通过。")
    return True


def handle_selection_input(cmd: str) -> bool:
    """Returns True if the input was consumed by the selection menu."""
    if not MENU_STATE["selection_unlocked"]:
        return False

    cmd = normalize_menu_input(cmd)

    if MENU_STATE["awaiting_filter_protection"]:
        if not cmd:
            cmd = "-protecton"
        if cmd == "-back":
            MENU_STATE["awaiting_filter_protection"] = False
            print("[*] 已返回上一级。")
            stage_data = get_stage_data(CONFIG.get("SELECTED_DIFFICULTY"), CONFIG.get("SELECTED_STAGE"))
            if stage_data:
                print_target_menu(CONFIG["SELECTED_DIFFICULTY"], CONFIG["SELECTED_STAGE"])
            return True
        if cmd == "-protecton":
            MENU_STATE["awaiting_filter_protection"] = False
            MENU_STATE["awaiting_stop_on_max"] = True
            CONFIG["ENABLE_FILTER_PROTECTION"] = True
            print("[+] 已选择：过滤保护开启。")
            print_stop_on_max_menu()
            return True
        if cmd == "-protectoff":
            MENU_STATE["awaiting_filter_protection"] = False
            MENU_STATE["awaiting_stop_on_max"] = True
            CONFIG["ENABLE_FILTER_PROTECTION"] = False
            print("[+] 已选择：过滤保护关闭。")
            print("[!] 提示：关闭后目标掉落也不会被保护，适合练级避免仓库被占满。")
            print_stop_on_max_menu()
            return True
        return False

    if MENU_STATE["awaiting_stop_on_max"]:
        if not cmd:
            cmd = "-stopmax"
        if cmd == "-back":
            MENU_STATE["awaiting_stop_on_max"] = False
            if CONFIG.get("MODE_NAME") == "team":
                MENU_STATE["awaiting_filter_protection"] = True
                print("[*] 已返回过滤保护设置菜单。")
                print_filter_protection_menu()
            else:
                print("[*] 已返回上一级。")
                stage_data = get_stage_data(CONFIG.get("SELECTED_DIFFICULTY"), CONFIG.get("SELECTED_STAGE"))
                if stage_data:
                    print_target_menu(CONFIG["SELECTED_DIFFICULTY"], CONFIG["SELECTED_STAGE"])
            return True
        if cmd == "-stopmax":
            MENU_STATE["awaiting_stop_on_max"] = False
            CONFIG["STOP_ON_MAX_LEVEL"] = True
            print("[+] 已选择：检测到满级后停止程序。")
            if CONFIG.get("MODE_NAME") == "single" and CONFIG.get("SELECTED_DIFFICULTY") != "夜战" and not is_13_4_resource_farm_stage():
                MENU_STATE["awaiting_target_drop_stop"] = True
                print_target_drop_stop_menu()
            else:
                MENU_STATE["awaiting_run_confirm"] = True
                print_run_confirm_menu()
            return True
        if cmd == "-keepmax":
            MENU_STATE["awaiting_stop_on_max"] = False
            CONFIG["STOP_ON_MAX_LEVEL"] = False
            print("[+] 已选择：检测到满级后不停止程序。")
            if CONFIG.get("MODE_NAME") == "single" and CONFIG.get("SELECTED_DIFFICULTY") != "夜战" and not is_13_4_resource_farm_stage():
                MENU_STATE["awaiting_target_drop_stop"] = True
                print_target_drop_stop_menu()
            else:
                MENU_STATE["awaiting_run_confirm"] = True
                print_run_confirm_menu()
            return True
        return False

    if MENU_STATE["awaiting_target_drop_stop"]:
        if not cmd:
            cmd = "-keepdrop"
        if cmd == "-back":
            MENU_STATE["awaiting_target_drop_stop"] = False
            MENU_STATE["awaiting_stop_on_max"] = True
            print("[*] 已返回满级停机设置。")
            print_stop_on_max_menu()
            return True
        if cmd == "-stopdrop":
            MENU_STATE["awaiting_target_drop_stop"] = False
            MENU_STATE["awaiting_run_confirm"] = True
            CONFIG["STOP_AFTER_EACH_TARGET_DROPPED"] = True
            print("[+] 已选择：目标人形至少各掉落 1 个后停止打捞。")
            print_run_confirm_menu()
            return True
        if cmd == "-keepdrop":
            MENU_STATE["awaiting_target_drop_stop"] = False
            MENU_STATE["awaiting_run_confirm"] = True
            CONFIG["STOP_AFTER_EACH_TARGET_DROPPED"] = False
            print("[+] 已选择：目标达成后继续打捞。")
            print_run_confirm_menu()
            return True
        return False

    if MENU_STATE["awaiting_run_confirm"]:
        if cmd == "-back":
            MENU_STATE["awaiting_run_confirm"] = False
            if CONFIG.get("MODE_NAME") == "single" and CONFIG.get("SELECTED_DIFFICULTY") != "夜战" and not is_13_4_resource_farm_stage():
                MENU_STATE["awaiting_target_drop_stop"] = True
                print("[*] 已返回目标达成停机设置。")
                print_target_drop_stop_menu()
            else:
                MENU_STATE["awaiting_stop_on_max"] = True
                print("[*] 已返回满级停机设置。")
                print_stop_on_max_menu()
            return True
        if cmd == "-y":
            MENU_STATE["awaiting_run_confirm"] = False
            print("[+] 配置已确认。")
            
            print("[+] 当前模式：%s" % ("打捞单人模式" if CONFIG.get("SINGLE_GUN_MODE") else "练级五人模式"))
            if CONFIG.get("MODE_NAME") == "team":
                schedule_label = "整队满级后切换" if CONFIG.get("TRAIN_SCHEDULE_MODE") == "full" else "均等练级轮转"
                
                print("[+] 练级调度模式：%s" % schedule_label)
                
                if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                    print("[!] 提示：夜战暂时没有自动拆解功能，不建议去夜战关卡练级。")
            print("[+] 满级停机设置：%s" % ("开启" if CONFIG.get("STOP_ON_MAX_LEVEL") else "关闭"))
            if CONFIG.get("MODE_NAME") == "single" and CONFIG.get("SELECTED_DIFFICULTY") != "夜战" and not is_13_4_resource_farm_stage():
                print("[+] 目标达成停机：%s" % ("开启" if CONFIG.get("STOP_AFTER_EACH_TARGET_DROPPED") else "关闭"))
            protected_ids = sorted(get_selected_protected_gun_ids())
            print("[+] 自动拆解保护 gun_id：%s" % (protected_ids if protected_ids else "当前未配置"))
            if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                print("[!] 说明：夜战关卡当前仅支持自动打捞，暂不支持自动拆解。")
                print("[!] 当前版本夜战仅保留掉落统计与关卡流程。")
            print("[*] 输入 -r 开始运行。")
            return True
        return False

    if MENU_STATE["difficulty"] is None:
        if cmd == "13-4":
            if CONFIG.get("MODE_NAME") == "team":
                if not CONFIG.get("TRAIN_13_4_MODE"):
                    print("[!] 13-4 练级已改为独立捕获模式：梯队1单人占位，实际从梯队2开始练级。")
                    print("[!] 请重新输入 -a，并在编队模式中选择 -134train / train134。")
                    return True
                apply_13_4_training_config()
                MENU_STATE["difficulty"] = CONFIG["SELECTED_DIFFICULTY"]
                MENU_STATE["stage"] = CONFIG["SELECTED_STAGE"]
                MENU_STATE["awaiting_filter_protection"] = False
                MENU_STATE["awaiting_stop_on_max"] = True

                print("[+] 已选择：13-4 五战练级")
                print("[+] 当前关卡配置已写入：MISSION_ID=%s, START_SPOT=%s, ROUTE=%s" % (
                    CONFIG["MISSION_ID"],
                    CONFIG["START_SPOT"],
                    CONFIG["ROUTE"],
                ))
                print("[+] 13-4 为纯练级关卡，已自动关闭拆解过滤保护。")
                print("[+] 固定部署：当前练级队@91263 + 梯队1单人占位@91297；只移动当前练级队。")
                print("[+] 1002 将根据当前梯队配置自动生成，无需为每个任务单独修改。")
                print_ready_to_run_hint()
                print_stop_on_max_menu()
                return True

            if CONFIG.get("MODE_NAME") == "resource134":
                apply_13_4_resource_farm_config()
                MENU_STATE["difficulty"] = CONFIG["SELECTED_DIFFICULTY"]
                MENU_STATE["stage"] = CONFIG["SELECTED_STAGE"]
                MENU_STATE["awaiting_filter_protection"] = False
                MENU_STATE["awaiting_stop_on_max"] = True

                print("[+] 已选择：13-4 双单人五战四项基础资源打捞")
                print("[+] 当前关卡配置已写入：MISSION_ID=%s, 部署=梯队1@%s + 梯队2@%s, 梯队1路线=%s" % (
                    CONFIG["MISSION_ID"],
                    CONFIG["START_SPOT"],
                    CONFIG.get("RESOURCE_13_4_SUPPORT_START_SPOT", 91297),
                    CONFIG["ROUTE"],
                ))
                print("[+] 本模式目标为四项基础资源：人力 / 弹药 / 口粮 / 零件。")
                print("[+] 不启用人形过滤保护；所有 T-Doll 掉落都会进入自动拆解。")
                print("[+] 13-4 与 EPA 关卡一致，不调用 API_MISSION_SUPPLY，避免补给浪费。")
                print("[+] 当前模式固定使用梯队1和梯队2，且两队都必须为单人编队；运行时只移动梯队1。")
                print_ready_to_run_hint()
                print_stop_on_max_menu()
                return True

            if CONFIG.get("MODE_NAME") == "single":
                print("[!] 13-4 已移出 single 模式。请重新输入 -a，并在编队模式中选择 -134。")
                return True

            print("[!] 请先重新输入 -a，并选择 -team 或 -134 模式后再选择 13-4。")
            return True

        if cmd in ("普通", "紧急", "夜战"):
            print("[!] EN 特供版已移除 EPA 活动关卡，仅开放 13-4。")
            print_difficulty_menu()
            return True
        return False

    if MENU_STATE["stage"] is None:
        if cmd == "-back":
            reset_selection_menu()
            print("[*] 当前已返回到难度选择菜单。")
            print_difficulty_menu()
            return True

        difficulty = MENU_STATE["difficulty"]
        valid_options = {
            "普通": NORMAL_STAGE_OPTIONS,
            "紧急": EMERGENCY_STAGE_OPTIONS,
            "夜战": NIGHT_STAGE_OPTIONS,
        }[difficulty]

        if cmd in valid_options:
            MENU_STATE["stage"] = cmd
            CONFIG["SELECTED_STAGE"] = cmd
            CONFIG["SELECTED_TARGET"] = None
            CONFIG["SELECTED_TARGET_LABEL"] = None
            CONFIG["SELECTED_BATTLE_TEMPLATE"] = None
            CONFIG["RESOURCE_FARM_MODE"] = False

            stage_data = get_stage_data(difficulty, cmd)
            if stage_data:
                print_target_menu(difficulty, cmd)
            else:
                print_placeholder_menu(difficulty, cmd)
                MENU_STATE["stage"] = None
                CONFIG["SELECTED_STAGE"] = None
                print_stage_menu(difficulty)
            return True
        return False

    stage_data = get_stage_data(CONFIG.get("SELECTED_DIFFICULTY"), CONFIG.get("SELECTED_STAGE"))
    if stage_data:
        if cmd == "-back":
            MENU_STATE["stage"] = None
            CONFIG["SELECTED_STAGE"] = None
            CONFIG["SELECTED_TARGET"] = None
            CONFIG["SELECTED_TARGET_LABEL"] = None
            CONFIG["SELECTED_BATTLE_TEMPLATE"] = None
            MENU_STATE["awaiting_stop_on_max"] = False
            MENU_STATE["awaiting_run_confirm"] = False
            print("[*] 已返回%s难度关卡列表。" % CONFIG["SELECTED_DIFFICULTY"])
            print_stage_menu(CONFIG["SELECTED_DIFFICULTY"])
            return True

        options = stage_data.get("OPTIONS", {})
        if cmd in options:
            item = options[cmd]
            CONFIG["SELECTED_TARGET"] = cmd
            CONFIG["SELECTED_TARGET_LABEL"] = item["label"]
            CONFIG["MISSION_ID"] = stage_data["MISSION_ID"]
            if "start_spot" in item:
                CONFIG["START_SPOT"] = item["start_spot"]
            else:
                CONFIG["START_SPOT"] = stage_data["START_SPOTS"][cmd]
            CONFIG["ROUTE"] = item["route"]

            if CONFIG["SELECTED_DIFFICULTY"] == "普通" and CONFIG["SELECTED_STAGE"] == "A-10":
                CONFIG["SELECTED_BATTLE_TEMPLATE"] = A10_SINGLE_BATTLE_TEMPLATE
            else:
                CONFIG["SELECTED_BATTLE_TEMPLATE"] = None

            print("[+] 已选择：%s %s -> %s" % (
                CONFIG["SELECTED_DIFFICULTY"],
                CONFIG["SELECTED_STAGE"],
                CONFIG["SELECTED_TARGET_LABEL"],
            ))
            print("[+] 当前关卡配置已写入：MISSION_ID=%s, START_SPOT=%s, ROUTE=%s" % (
                CONFIG["MISSION_ID"],
                CONFIG["START_SPOT"],
                CONFIG["ROUTE"],
            ))
            print("[+] 当前模式已在抓包前确定：%s" % ("打捞单人模式" if CONFIG.get("SINGLE_GUN_MODE") else "练级五人模式"))
            if CONFIG.get("MODE_NAME") == "team" and CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                print("[!] 提示：夜战当前暂未支持自动拆解功能，不建议用于自动练级。")
            print("[+] 当前战斗将自动调用已抓取的 TEAM_ID / FAIRY_ID / GUNS。")
            print("[+] 1002 将根据当前梯队配置自动生成，无需为每个任务单独修改。")
            print_ready_to_run_hint()
            if CONFIG.get("MODE_NAME") == "team":
                MENU_STATE["awaiting_filter_protection"] = True
                print_filter_protection_menu()
            else:
                MENU_STATE["awaiting_stop_on_max"] = True
                print_stop_on_max_menu()
            return True
        return False

    return False


def on_traffic(event_type: str, url: str, data: dict):
    event_upper = str(event_type).upper()

    if event_upper == "SYS_KEY_UPGRADE":
        CONFIG["USER_UID"] = data.get("uid")
        CONFIG["SIGN_KEY"] = data.get("sign")
        CONFIG["INDEX_FETCH_READY"] = True
        print("\n[+] 成功！密钥已自动配置：")
        print("    UID  : %s" % CONFIG['USER_UID'])
        print("    SIGN : %s" % CONFIG['SIGN_KEY'])

        if CONFIG.get("AUTO_MONITOR_MODE"):
            print("[AUTO] 动态密钥已更新。")
            print("[AUTO] 请等待游戏完全进入指挥官主界面，然后再次输入 -a。")
            print("[AUTO] 程序将停止代理并主动请求 Index/index 解析梯队。")
        else:
            print("\n[!] CRITICAL: 请等待游戏完全加载到指挥官主界面！")
            print("[!] 然后输入 '-r' 自动停止代理并开始打捞。")


def check_step_error(resp: dict, step_name: str) -> bool:
    if "error_local" in resp:
        print("[-] %s 本地错误: %s" % (step_name, resp['error_local']))
        return True
    if "error" in resp:
        print("[-] %s 服务器错误: %s" % (step_name, resp['error']))
        return True
    return False


def check_battle_drop(resp_data: dict, spot_id: int) -> list:
    collected = []
    bg = resp_data.get("battle_get_gun", [])
    if bg:
        for gun in bg:
            gun_id = int(gun.get("gun_id"))
            gun_uid = int(gun.get("gun_with_user_id"))
            # 详细掉落已汇总到状态面板，本处不再逐条打印。
            DROPPED_UID_TO_GUN_ID[gun_uid] = gun_id
            record_target_drop(gun_id, "gun")
            RUN_STATS["macro_drop_names"].append(resolve_gun_name_by_id(gun_id))
            collected.append(gun_uid)
    return collected


def check_battle_equip_drop(resp_data: dict, spot_id: int):
    collected = []
    be = resp_data.get("battle_get_equip", [])
    if be:
        for equip in be:
            equip_id = int(equip.get("equip_id"))
            equip_uid = int(equip.get("id"))
            DROPPED_UID_TO_EQUIP_ID[equip_uid] = equip_id
            record_target_drop(equip_id, "equip")
            collected.append({"equip_id": equip_id, "equip_uid": equip_uid})
    return collected



def extract_fairy_exp_gain_from_resp(resp_data: dict) -> int:
    """
    尝试从 battleFinish / startTurn 返回中提取当前妖精本次获得的经验增量。
    这里只统计妖精本体经验，不统计 quality_exp / mod_exp。
    """
    current_cfg = get_current_team_config()
    fairy = current_cfg.get("fairy")
    if not isinstance(fairy, dict):
        return 0

    fairy_uid = str(fairy.get("id", ""))
    fairy_type_id = str(fairy.get("fairy_id", ""))

    candidates = []

    def walk(node):
        if isinstance(node, dict):
            exp_key = None
            for k in ("fairy_exp", "fairyExp", "fairyexp"):
                if k in node:
                    exp_key = k
                    break

            if exp_key is not None:
                try:
                    exp_val = int(node.get(exp_key) or 0)
                except Exception:
                    exp_val = 0

                uid_match = False
                if fairy_uid:
                    for id_key in ("id", "fairy_with_user_id", "fairy_uid"):
                        if str(node.get(id_key, "")) == fairy_uid:
                            uid_match = True
                            break

                type_match = False
                if fairy_type_id:
                    for id_key in ("fairy_id", "type_id"):
                        if str(node.get(id_key, "")) == fairy_type_id:
                            type_match = True
                            break

                has_identity = any(k in node for k in ("id", "fairy_with_user_id", "fairy_uid", "fairy_id", "type_id"))
                if exp_val > 0 and (uid_match or type_match or not has_identity):
                    candidates.append(exp_val)

            for v in node.values():
                walk(v)

        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(resp_data)

    if not candidates:
        return 0

    return max(candidates)


def apply_fairy_exp_gain_from_resp(resp_data: dict):
    current_cfg = get_current_team_config()
    fairy = current_cfg.get("fairy")
    if not isinstance(fairy, dict):
        return 0

    raw_val = extract_fairy_exp_gain_from_resp(resp_data)
    if raw_val <= 0:
        return 0

    base_total = int(fairy.get("base_total_exp", 0) or 0)
    target_total = int(fairy.get("target_total_exp", 0) or 0)
    current_runtime = int(fairy.get("runtime_gained_exp", 0) or 0)
    current_total = min(target_total, base_total + current_runtime)

    level = int(fairy.get("level", fairy.get("fairy_lv", 1)) or 1)
    next_need = fairy_next_level_required_exp(level)

    # 形态一：返回的是当前累计总经验。
    # 只接受“比当前总量略高”的累计值，避免把 9,999,000 这类异常/上限值
    # 每次都当作真实当前累计，导致 92 级妖精直接显示 100%。
    if current_total <= raw_val <= target_total:
        delta = raw_val - current_total
        max_reasonable_jump = max(500000, next_need * 2)
        if 0 < delta <= max_reasonable_jump:
            fairy["runtime_gained_exp"] = current_runtime + delta
            fairy["last_total_exp_seen"] = raw_val
            refresh_runtime_panel()
            return delta
        if delta == 0:
            return 0

    # 形态二：返回的是本次获得经验。
    # 妖精单次战斗经验不应巨大；过大的值更可能是累计/异常字段，直接忽略。
    max_reasonable_delta = max(50000, next_need)
    if raw_val <= max_reasonable_delta:
        fairy["runtime_gained_exp"] = current_runtime + raw_val
        refresh_runtime_panel()
        return raw_val

    return 0



def check_battle_exp(resp_data: dict, spot_id: int):
    """Returns (any_zero, all_zero)."""
    gun_exp_list = resp_data.get("gun_exp", [])
    any_zero = False
    all_zero = False

    if gun_exp_list:
        exp_details = []
        zero_flags = []
        current_cfg = get_current_team_config()
        gun_map = {str(g.get("id")): g for g in current_cfg.get("guns", [])}

        for item in gun_exp_list:
            gun_uid = str(item.get("gun_with_user_id", "unknown"))
            exp_val = str(item.get("exp", "0"))
            exp_int = int(exp_val) if str(exp_val).isdigit() else 0
            exp_details.append("%s: +%s" % (gun_uid[-4:], exp_val))

            maxed_set = current_cfg.setdefault("maxed_member_uids", set())
            warned_set = current_cfg.setdefault("warned_max_member_uids", set())

            if gun_uid in gun_map and exp_int > 0:
                gun_map[gun_uid]["runtime_gained_exp"] = int(gun_map[gun_uid].get("runtime_gained_exp", 0)) + exp_int
                # 如果仍能获得经验，则不把它视为满级。
                maxed_set.discard(gun_uid)

            is_zero = (exp_val == "0")
            zero_flags.append(is_zero)
            if is_zero:
                maxed_set.add(gun_uid)
                if gun_uid not in warned_set:
                    panel_safe_print("    [满级检测] 人形 %s EXP 为 0，已标记为满级。" % gun_uid)
                    warned_set.add(gun_uid)
                any_zero = True

        all_zero = all(zero_flags) if zero_flags else False
        RUN_STATS["last_micro_exp_lines"] = exp_details
        apply_fairy_exp_gain_from_resp(resp_data)

    return any_zero, all_zero


def check_win_drop(resp_data: dict) -> list:
    collected = []
    win_result = resp_data.get("mission_win_result", {})
    if win_result:
        rg = win_result.get("reward_gun", [])
        for gun in rg:
            gun_id = int(gun.get("gun_id"))
            gun_uid = int(gun.get("gun_with_user_id"))
            refresh_runtime_panel()
            DROPPED_UID_TO_GUN_ID[gun_uid] = gun_id
            record_target_drop(gun_id, "gun")
            RUN_STATS["macro_drop_names"].append(resolve_gun_name_by_id(gun_id))
            collected.append(gun_uid)
    return collected


def check_win_equip_drop(resp_data: dict):
    collected = []
    win_result = resp_data.get("mission_win_result", {})
    if win_result:
        re_list = win_result.get("reward_equip", [])
        for equip in re_list:
            equip_id = int(equip.get("equip_id"))
            equip_uid = int(equip.get("id"))
            refresh_runtime_panel()
            DROPPED_UID_TO_EQUIP_ID[equip_uid] = equip_id
            record_target_drop(equip_id, "equip")
            collected.append({"equip_id": equip_id, "equip_uid": equip_uid})
    return collected


def get_mvp_generator():
    idx = 0
    while True:
        guns = get_active_guns()
        if not guns:
            yield 0
            continue
        yield guns[idx % len(guns)]["id"]
        idx = (idx + 1) % len(guns)


def get_active_guns():
    if is_13_4_resource_farm_stage():
        team_cfg = get_13_4_main_team_config()
        return list(team_cfg.get("guns", []))

    guns = get_current_team_config()["guns"]
    if CONFIG.get("SINGLE_GUN_MODE"):
        idx = CONFIG.get("SINGLE_GUN_INDEX", 0)
        if 0 <= idx < len(guns):
            return [guns[idx]]
        return []
    return guns


def build_battle_guns():
    return [{"id": g["id"], "life": g["life"]} for g in get_active_guns()]


def build_battle_1002():
    """
    与原版风格尽量保持一致：
    - 单人编队时，使用抓包里验证过的座位值 1
    - 多人编队时，按原版自动生成，不需要为每个任务单独写死
    """
    result = {}
    guns = get_active_guns()

    if len(guns) == 1:
        result[str(guns[0]["id"])] = {"47": 1}
        return result

    for gun in guns:
        result[str(gun["id"])] = {"47": 0}
    return result


def farm_mission_epa(client: GFLClient, team_id: int, mvp_gen):
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
                current_spots_state[str(s.get("spot_id"))] = int(s.get("seed", 0))

    refresh_runtime_panel()
    if check_step_error(client.send_request(API_MISSION_COMBINFO, {"mission_id": mission_id}), "combInfo"):
        return None

    refresh_runtime_panel()
    if is_13_4_resource_farm_stage():
        main_team_id = int(CONFIG.get("RESOURCE_13_4_MAIN_TEAM_ID", 1))
        support_team_id = int(CONFIG.get("RESOURCE_13_4_SUPPORT_TEAM_ID", 2))
        team_id = main_team_id
        start_spots = [
            {"spot_id": int(CONFIG.get("START_SPOT", 91263)), "team_id": main_team_id},
            {"spot_id": int(CONFIG.get("RESOURCE_13_4_SUPPORT_START_SPOT", 91297)), "team_id": support_team_id},
        ]
    elif is_13_4_training_independent_mode():
        # 13-4 练级：梯队1为单人占位队，部署在 91297；
        # 当前实际练级队从梯队2开始轮转，部署在 91263 并移动作战。
        dummy_team_id = get_13_4_training_dummy_team_id()
        start_spots = [
            {"spot_id": int(CONFIG.get("START_SPOT", 91263)), "team_id": int(team_id)},
            {"spot_id": get_13_4_training_dummy_start_spot(), "team_id": dummy_team_id},
        ]
    else:
        start_spots = [{"spot_id": start_spot, "team_id": team_id}]

    start_payload = {
        "mission_id": mission_id,
        "spots": start_spots,
        "squad_spots": [], "sangvis_spots": [], "vehicle_spots": [],
        "ally_spots": [], "mission_ally_spots": [],
        "ally_id": int(time.time())
    }
    start_resp = client.send_request(API_MISSION_START, start_payload)
    if check_step_error(start_resp, "startMission"):
        return None
    update_seeds(start_resp)

    # 13-4 练级不再自动补给
    # 昨晚实测确认：像 EPA 各个关卡一样关闭 API_MISSION_SUPPLY，
    # 否则每轮都会给部署梯队补满弹粮，造成大量资源浪费。

    curr_spot = start_spot
    for step, next_spot in enumerate(route, 1):
        RUN_STATS["current_step"] = step
        refresh_runtime_panel()
        move_payload = {
            "person_type": 1, "person_id": team_id,
            "from_spot_id": curr_spot, "to_spot_id": next_spot, "move_type": 1
        }
        move_resp = client.send_request(API_MISSION_TEAM_MOVE, move_payload)
        if check_step_error(move_resp, "teamMove(%d->%d)" % (curr_spot, next_spot)):
            return None
        update_seeds(move_resp)

        client.send_request(API_MISSION_COMBINFO, {"mission_id": mission_id})

        seed = current_spots_state.get(str(next_spot), 0)
        current_mvp = next(mvp_gen)
        refresh_runtime_panel()

        selected_template = CONFIG.get("SELECTED_BATTLE_TEMPLATE")

        if selected_template:
            fairy_dict = {}
            current_fairy_id = get_current_fairy_id()
            if current_fairy_id:
                fairy_dict = {
                    str(current_fairy_id): {
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
                "guns": build_battle_guns(),
                "user_rec": '{"seed":%d,"record":[]}' % seed,
                "1000": selected_template.get("1000", {}),
                "1001": selected_template.get("1001", {}),
                "1002": build_battle_1002(),
                "1003": fairy_dict,
                "1005": selected_template.get("1005", {}),
                "1007": selected_template.get("1007", {}),
                "1008": selected_template.get("1008", {}),
                "1009": selected_template.get("1009", {}),
                "battle_damage": {},
                "micalog": {
                    "user_device": CONFIG["USER_DEVICE"],
                    "user_ip": ""
                }
            }
        else:
            fairy_dict = {}
            current_fairy_id = get_current_fairy_id()
            if current_fairy_id:
                fairy_dict = {
                    str(current_fairy_id): {
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
                "guns": build_battle_guns(),
                "user_rec": '{"seed":%d,"record":[]}' % seed,

                "1000": TRAIN_13_4_BATTLE_1000_BY_SPOT.get(int(next_spot), {"10": 18473, "11": 18473, "12": 18473, "13": 18473, "15": 27550, "16": 0, "17": 98, "33": 10017, "40": 50, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 25975, "25": 0, "26": 25975, "27": 4, "34": 63, "35": 63, "41": 519, "42": 0, "43": 0, "44": 0}) if is_13_4_training_stage() else {"10": 18473, "11": 18473, "12": 18473, "13": 18473, "15": 27550, "16": 0, "17": 98, "33": 10017, "40": 50, "18": 0, "19": 0, "20": 0, "21": 0, "22": 0, "23": 0, "24": 25975, "25": 0, "26": 25975, "27": 4, "34": 63, "35": 63, "41": 519, "42": 0, "43": 0, "44": 0},
                "1001": {},
                "1002": build_battle_1002(),
                "1003": fairy_dict,
                "1005": {}, "1007": {}, "1008": {}, "1009": {},
                "battle_damage": {},
                "micalog": {
                    "user_device": CONFIG["USER_DEVICE"],
                    "user_ip": ""
                }
            }

        battle_resp = client.send_request(API_MISSION_BATTLE_FINISH, battle_payload)
        if check_step_error(battle_resp, "battleFinish(%d)" % next_spot):
            return None

        record_basic_resource_rewards(battle_resp)
        # 13-4 的妖精经验可能随 battleFinish 返回，而不是只在 endTurn/startTurn 返回。
        # 因此每个战斗点结算后都尝试更新一次妖精经验进度，避免面板一直停在初始值。
        apply_fairy_exp_gain_from_resp(battle_resp)
        dropped_uids.extend(check_battle_drop(battle_resp, next_spot))
        battle_equip_drops = check_battle_equip_drop(battle_resp, next_spot)
        dropped_equip_uids.extend([x["equip_uid"] for x in battle_equip_drops])

        any_zero, all_zero = check_battle_exp(battle_resp, next_spot)
        if CONFIG.get("MODE_NAME") == "team":
            if all_zero:
                TEAM_SWITCH_PENDING = True
                mark_current_training_team_completed()
                print("    [*] 当前五人编队成员 EXP 均为 0，该梯队已完成。")
        else:
            if any_zero:
                if CONFIG.get("STOP_ON_MAX_LEVEL", True):
                    stop_macro_flag = True
                    stop_micro_flag = True
                    print("    [*] 为避免浪费 EXP，已触发自动停机。本轮结束后将安全停止。")
                else:
                    print("    [*] 检测到满级，但已关闭满级停机，程序将继续运行。")

        curr_spot = next_spot
        time.sleep(0.2)

    refresh_runtime_panel()
    end_turn_resp = client.send_request(API_MISSION_END_TURN, {})
    if check_step_error(end_turn_resp, "endTurn"):
        return None

    # 13-4 手动抓包显示：到达 91271 后发送 endTurn，响应中已经带 mission_win_result，
    # 没有继续发送 startEnemyTurn / endEnemyTurn / startTurn。
    # 资源打捞和练级共用 mission_id/start_spot，因此这里同样走 13-4 收尾。
    if is_13_4_training_stage():
        record_basic_resource_rewards(end_turn_resp)
        apply_fairy_exp_gain_from_resp(end_turn_resp)
        dropped_uids.extend(check_win_drop(end_turn_resp))
        win_equip_drops = check_win_equip_drop(end_turn_resp)
        dropped_equip_uids.extend([x["equip_uid"] for x in win_equip_drops])
        return {"guns": dropped_uids, "equips": dropped_equip_uids}

    time.sleep(0.1)
    if check_step_error(client.send_request(API_MISSION_START_ENEMY_TURN, {}), "startEnemyTurn"):
        return None
    time.sleep(0.1)
    if check_step_error(client.send_request(API_MISSION_END_ENEMY_TURN, {}), "endEnemyTurn"):
        return None
    time.sleep(0.1)

    win_resp = client.send_request(API_MISSION_START_TURN, {})
    if check_step_error(win_resp, "startTurn"):
        return None

    record_basic_resource_rewards(win_resp)
    apply_fairy_exp_gain_from_resp(win_resp)
    dropped_uids.extend(check_win_drop(win_resp))
    win_equip_drops = check_win_equip_drop(win_resp)
    dropped_equip_uids.extend([x["equip_uid"] for x in win_equip_drops])

    return {"guns": dropped_uids, "equips": dropped_equip_uids}


def retire_guns(client: GFLClient, gun_uids: list):
    global stop_macro_flag, stop_micro_flag, RETIRE_NO_SPACE_COUNT

    if not gun_uids:
        return

    protected_ids = get_selected_protected_gun_ids()
    filtered_uids = []

    for gun_uid in gun_uids:
        gun_id = DROPPED_UID_TO_GUN_ID.get(gun_uid)
        if gun_id is not None:
            try:
                gun_id = int(gun_id)
            except Exception:
                pass
        if gun_id in protected_ids:
            print("[*] 已保留受保护掉落。Gun ID: %s | UID: %s" % (gun_id, gun_uid))
            continue
        filtered_uids.append(gun_uid)

    if protected_ids:
        print("[*] 已启用自动拆解保护，受保护 gun_id：%s" % sorted(protected_ids))

    if not filtered_uids:
        print("[*] 过滤后没有可自动拆解的人形。")
        return

    print("[*] 正在提交 %d 名人形进行自动拆解……" % len(filtered_uids))
    resp = client.send_request(API_GUN_RETIRE, filtered_uids)
    if resp.get("success"):
        RETIRE_NO_SPACE_COUNT = 0
        print("[+] 自动拆解成功！")
    else:
        print("[-] 拆解失败：%s" % str(resp))
        if is_no_space_retire_failure(resp):
            RETIRE_NO_SPACE_COUNT += 1
            print("[!] 检测到疑似仓库无空位导致的拆解失败次数：%d / %d" % (
                RETIRE_NO_SPACE_COUNT,
                CONFIG.get("STOP_AFTER_RETIRE_NO_SPACE_TIMES", 2),
            ))
            if RETIRE_NO_SPACE_COUNT >= CONFIG.get("STOP_AFTER_RETIRE_NO_SPACE_TIMES", 2):
                stop_macro_flag = True
                stop_micro_flag = True
                print("[!] 已触发自动停机：多次自动拆解后仓库似乎仍无空位。")
        else:
            RETIRE_NO_SPACE_COUNT = 0

    for gun_uid in gun_uids:
        if gun_uid in DROPPED_UID_TO_GUN_ID:
            del DROPPED_UID_TO_GUN_ID[gun_uid]


def retire_equips(client: GFLClient, equip_uids: list):
    # 夜战自动拆解功能暂未启用。
    return False


def perform_deferred_night_recovery():
    return


def farm_worker():
    global stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread, TEAM_SWITCH_PENDING

    if CONFIG["SIGN_KEY"] == DEFAULT_SIGN:
        print("[!] SIGN_KEY 为默认值，请先通过 -a 获取 UID / SIGN。")
        worker_mode, current_worker_thread = None, None
        return

    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"], CONFIG["BASE_URL"])
    mvp_gen = get_mvp_generator()

    reset_run_stats()
    RUN_STATS["start_time"] = time.time()
    init_run_target_counts()
    initialize_all_team_progress()

    if CONFIG.get("MODE_NAME") == "team":
        schedule_label = "整队满级后切换" if CONFIG.get("TRAIN_SCHEDULE_MODE") == "full" else "均等练级轮转"
        if CONFIG.get("TRAIN_13_4_MODE"):
            print("[*] 13-4 五战练级模式已启用，共 %d 个实际练级梯队参与轮转。" % len(CAPTURED_TEAM_CONFIGS))
            print("[*] 固定部署：梯队1单人占位@91297；当前练级队@91263，只移动当前练级队。")
        else:
            print("[*] 练级模式已启用，共 %d 个梯队参与轮转。" % len(CAPTURED_TEAM_CONFIGS))
        print("[*] 练级调度：%s" % schedule_label)
        print("[*] 将持续运行到全部梯队满级或你手动停止。")
        reset_training_progress()
        if CAPTURED_TEAM_CONFIGS:
            activate_team_runtime(CAPTURED_TEAM_CONFIGS[0]["team_id"])
    else:
        if is_13_4_resource_farm_stage():
            print("[*] 13-4 双单人五战四项基础资源打捞模式已启用。")
            print("[*] 固定部署：梯队1@91263，梯队2@91297；只移动梯队1。")
            print("[*] 不启用人形过滤保护；所有 T-Doll 掉落都会自动拆解。")
        else:
            print("[*] 打捞模式已启用。")
            if CONFIG.get("STOP_AFTER_EACH_TARGET_DROPPED"):
                print("[*] 目标达成停机已开启：目标人形至少各掉落 1 个后停止。")
        print("[*] 将持续运行到你手动停止或触发其他停止条件。")
        activate_team_runtime(get_current_team_id())
    print("=== GFL Protocol Auto-Farming Started (EPA) ===")
    panel_safe_print(colorize("[*] 已启用固定运行状态面板：上方为最近日志，下方为固定状态面板。", "success"))
    macro = 1
    while True:
        if stop_macro_flag:
            break

        if CONFIG.get("MODE_NAME") == "team":
            panel_safe_print("=== MACRO %d / 直到全部梯队满级 ===" % macro)
        else:
            panel_safe_print("=== MACRO %d / 直到手动停止或触发停止条件 ===" % macro)

        RUN_STATS["current_macro"] = macro
        RUN_STATS["current_team_no"] = get_current_team_id() if (CONFIG.get("MODE_NAME") == "team" and CONFIG.get("TRAIN_13_4_MODE")) else ((CONFIG.get("CURRENT_TRAIN_TEAM_INDEX", 0) + 1) if CONFIG.get("MODE_NAME") == "team" else get_current_team_id())
        RUN_STATS["macro_drop_names"] = []
        RUN_STATS["last_micro_exp_lines"] = []
        batch_guns = []
        batch_equips = []
        night_retire_attempted_after_failure = False
        for micro in range(1, CONFIG["MISSIONS_PER_RETIRE"] + 1):
            if stop_micro_flag or stop_macro_flag:
                break

            RUN_STATS["current_micro"] = micro
            RUN_STATS["current_step"] = 0
            refresh_runtime_panel()
            dropped = farm_mission_epa(client, get_current_team_id(), mvp_gen)

            if dropped is None:
                print("[-] 本轮失败或中止，正在放弃关卡……")
                client.send_request(API_MISSION_ABORT, {"mission_id": CONFIG["MISSION_ID"]})
                time.sleep(3)

                if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
                    print("[!] 夜战当前仅支持自动打捞，不支持自动拆解。")
                    print("[!] 若因仓库问题无法继续，请检查装备仓库空位后再重新运行。")
                    stop_macro_flag = True
                    stop_micro_flag = True
                    break

                continue

            if is_13_4_resource_farm_stage():
                RUN_STATS["completed_resource_runs"] = int_safe(RUN_STATS.get("completed_resource_runs"), 0) + 1

            if should_stop_after_each_target_dropped():
                stop_macro_flag = True
                stop_micro_flag = True
                panel_safe_print(colorize("[目标达成] 当前目标人形已至少各掉落 1 个：%s，程序将安全停止。" % get_target_drop_progress_text(), "success"))
                break

            batch_guns.extend(dropped.get("guns", []))
            if "batch_equips" not in locals():
                batch_equips = []
            new_equips = dropped.get("equips", [])
            batch_equips.extend(new_equips)

            night_retire_attempted_after_failure = False
            time.sleep(1)

            if CONFIG.get("MODE_NAME") == "team" and TEAM_SWITCH_PENDING:
                advance_to_next_training_team()
                break

            if CONFIG.get("MODE_NAME") == "team" and CONFIG.get("TRAIN_SCHEDULE_MODE") == "equal":
                switch_to_next_available_training_team("当前梯队已练级一轮")
                break

        if CONFIG.get("SELECTED_DIFFICULTY") == "夜战":
            if batch_equips:
                print("[*] 夜战模式：本轮不执行装备拆解。")
        else:
            retire_guns(client, batch_guns)

        drop_summary = "无"
        if is_13_4_resource_farm_stage():
            drop_summary = "资源收益结束后统计"
        elif RUN_STATS.get("macro_drop_names"):
            shown = [format_drop_name_for_display(x) for x in RUN_STATS["macro_drop_names"][:8]]
            drop_summary = ", ".join(shown)
            if len(RUN_STATS["macro_drop_names"]) > 8:
                drop_summary += colorize(" ...", "dim")
        elapsed_now = 0
        if RUN_STATS.get("start_time") is not None:
            elapsed_now = time.time() - RUN_STATS["start_time"]
        panel_safe_print("[MACRO %d] 梯队 %s | 掉落：%s | 用时：%s" % (
            macro,
            RUN_STATS.get("current_team_no", 1),
            drop_summary,
            format_duration(elapsed_now),
        ))

        time.sleep(2)
        if stop_micro_flag:
            break

        macro += 1

    RUN_STATS["end_time"] = time.time()
    panel_safe_print(colorize("\n[*] 本次运行结束。", "success"))
    if is_13_4_resource_farm_stage():
        finalize_13_4_resource_summary_from_index(client)
    print_run_summary()
    worker_mode, current_worker_thread = None, None
    reopen_stage_selection_menu()


if __name__ == '__main__':
    enable_console_ansi()
    print_main_menu()
    while True:
        try:
            cmd = input("GFL-EN13> ").strip()
            if not cmd:
                continue
            cmd_prefix = cmd.split()[0]

            if handle_selection_input(cmd):
                continue

            if cmd_prefix.lower() in ('-134train', '-train134', '134train', 'train134'):
                preset_train134_mode()
                continue

            if cmd_prefix in ('-134', '134'):
                preset_resource134_mode()
                continue

            if cmd_prefix == '-a':
                # 优先复用已抓到的动态密钥，直接请求 Index/index。
                if not CONFIG.get("INDEX_FETCH_READY", False) and not proxy_instance and has_usable_dynamic_keys() and CONFIG.get("MODE_SELECTED_EARLY"):
                    print("[*] 检测到已有可用动态密钥，优先复用当前 UID / SIGN 直接请求 Index/index。")
                    ok = request_index_and_prepare_configs()
                    if ok:
                        continue
                    print("[!] 复用当前 UID / SIGN 请求 Index/index 失败。")
                    print("[*] 将回退到重新开启代理并抓取 UID / SIGN 的流程。")

                # Phase 1: start proxy and capture UID/SIGN
                if not CONFIG.get("INDEX_FETCH_READY", False) and not proxy_instance:
                    print_server_menu()
                    server_cmd = input("GFL-EN13(服务器, 默认EN，可输SOP)> ").strip()
                    if not apply_server_selection(server_cmd):
                        print("[!] 服务器选择无效，请重新输入 -a 后选择服务器。")
                        continue

                    if CONFIG.get("MODE_SELECTED_EARLY") and ((CONFIG.get("MODE_NAME") == "team" and CONFIG.get("TRAIN_13_4_MODE")) or CONFIG.get("MODE_NAME") == "resource134"):
                        if CONFIG.get("MODE_NAME") == "team":
                            mode_cmd = "-134train"
                            keep_label = "13-4 五战练级模式"
                        else:
                            mode_cmd = "-134"
                            keep_label = "13-4 双单人资源打捞模式"
                        print("[*] 已保留上次选择：%s" % keep_label)
                    else:
                        print_gun_mode_menu()
                        mode_cmd = normalize_gun_mode_input(input("GFL-EN13(模式)> ").strip())
                        if mode_cmd not in ("-134", "-134train"):
                            print("[!] EN 特供版只支持 -134train / -134。")
                            continue

                    if mode_cmd == "-team":
                        CONFIG["MODE_NAME"] = "team"
                        CONFIG["SINGLE_GUN_MODE"] = False
                        CONFIG["RESOURCE_FARM_MODE"] = False
                        CONFIG["TRAIN_13_4_MODE"] = False
                        CONFIG["MODE_SELECTED_EARLY"] = True

                        print("[*] 练级调度说明：")
                        print("    -full  = 先把当前梯队一直练到全员满级，再切换到下一梯队。（默认）")
                        print("    -equal = 每个梯队先各练一轮，再轮流继续，直到所有梯队满级。")
                        print("[*] 提示：直接按回车将使用默认配置（-full），输入 -back 或 b 可返回编队模式选择。")
                        schedule_cmd = normalize_menu_input(input("GFL-EN13(练级调度: -full/-equal, 默认-full)> ").strip())
                        if schedule_cmd == "-back":
                            print_gun_mode_menu()
                            continue
                        if schedule_cmd == "-equal":
                            CONFIG["TRAIN_SCHEDULE_MODE"] = "equal"
                            print("[*] 已选择均等练级。")
                        else:
                            CONFIG["TRAIN_SCHEDULE_MODE"] = "full"
                            print("[*] 已选择整队练满。")

                        print("[*] 梯队数量：表示从第1队开始，总共练多少个梯队。")
                        print("[*] 例如输入 3，则练第1、2、3队。回车默认 1。")
                        count_str = input("GFL-EN13(梯队数量, 默认1)> ").strip()
                        if count_str in ("-back", "b"):
                            print("[*] 已返回练级调度选择。")
                            continue
                        team_count = 1
                        if count_str:
                            try:
                                team_count = max(1, min(10, int(count_str)))
                            except Exception:
                                team_count = 1
                        CONFIG["TRAIN_TEAM_COUNT"] = team_count
                        CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = team_count
                        reset_captured_team_configs()
                        reset_training_progress()
                        print("[*] 已选择练级模式，共需解析 %d 个梯队。" % team_count)
                    elif mode_cmd == "-134train":
                        apply_13_4_training_config()
                        CONFIG["MODE_SELECTED_EARLY"] = True

                        print("[*] 13-4 练级调度说明：")
                        print("    -full  = 先把当前练级梯队一直练到全员满级，再切换到下一梯队。（默认）")
                        print("    -equal = 每个练级梯队先各练一轮，再轮流继续，直到所有练级梯队满级。")
                        schedule_cmd = normalize_menu_input(input("GFL-EN13(13-4练级调度: -full/-equal, 默认-full)> ").strip())
                        if schedule_cmd == "-equal":
                            CONFIG["TRAIN_SCHEDULE_MODE"] = "equal"
                            print("[*] 已选择均等练级。")
                        else:
                            CONFIG["TRAIN_SCHEDULE_MODE"] = "full"
                            print("[*] 已选择整队练满。")

                        print("[*] 13-4 练级：梯队1固定为单人占位队，不参与练级。")
                        print("[*] 梯队数量表示从梯队2开始，总共练多少个实际练级梯队。")
                        print("[*] 例如输入 3，则练第2、3、4队；回车默认 1。")
                        count_str = input("GFL-EN13(13-4练级梯队数量, 默认1)> ").strip()
                        team_count = 1
                        if count_str:
                            try:
                                team_count = max(1, min(9, int(count_str)))
                            except Exception:
                                team_count = 1
                        CONFIG["TRAIN_TEAM_COUNT"] = team_count
                        CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = team_count + 1
                        reset_captured_team_configs()
                        reset_training_progress()
                        print("[*] 已选择 13-4 五战练级，共需解析 梯队1占位 + %d 个练级梯队。" % team_count)
                        print("[*] 固定要求：梯队1单人占位@91297；实际练级队从梯队2开始@91263。")
                    elif mode_cmd == "-134":
                        CONFIG["MODE_NAME"] = "resource134"
                        CONFIG["SINGLE_GUN_MODE"] = False
                        CONFIG["RESOURCE_FARM_MODE"] = True
                        CONFIG["TRAIN_13_4_MODE"] = False
                        CONFIG["MODE_SELECTED_EARLY"] = True
                        CONFIG["TRAIN_TEAM_COUNT"] = 2
                        CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 2
                        reset_captured_team_configs()
                        print("[*] 已选择 13-4 双单人五战资源打捞模式。")
                        print("[*] 固定要求：梯队1单人部署 91263；梯队2单人部署 91297；运行时只移动梯队1。")
                    else:
                        CONFIG["MODE_NAME"] = "single"
                        CONFIG["SINGLE_GUN_MODE"] = True
                        CONFIG["RESOURCE_FARM_MODE"] = False
                        CONFIG["TRAIN_13_4_MODE"] = False
                        CONFIG["MODE_SELECTED_EARLY"] = True
                        CONFIG["TRAIN_TEAM_COUNT"] = 1
                        CONFIG["AUTO_CAPTURE_EXPECTED_COUNT"] = 1
                        reset_captured_team_configs()
                        print("[*] 已选择 EPA 打捞单人模式。")
                        print("[*] 提示：single 模式仅使用梯队1，请先将梯队1配置为单人编队。")

                    reset_auto_capture_state()
                    CONFIG["AUTO_MONITOR_MODE"] = True
                    CONFIG["INDEX_FETCH_READY"] = False
                    proxy_instance = GFLProxy(CONFIG["PROXY_PORT"], STATIC_KEY, on_traffic)
                    proxy_instance.start()
                    set_windows_proxy(True, "127.0.0.1:%d" % CONFIG['PROXY_PORT'])
                    worker_mode = 'a'
                    print("[*] 一体化代理已启动，端口 %d。Windows 代理已设置。" % CONFIG['PROXY_PORT'])
                    print("[*] 当前服务器：%s" % CONFIG.get("SERVER_NAME", "SOP"))
                    print("[*] 登录后会先自动获取 UID / SIGN。")
                    print("[*] 未使用 8080 端口，当前代理端口为 %d。" % CONFIG['PROXY_PORT'])
                    print("[*] 获取 UID/SIGN 后，请等待游戏完全进入指挥官主界面。")
                    print("[*] 然后再次输入 -a，程序会主动请求 Index/index 并解析梯队。")
                    continue

                # Phase 2: stop proxy and actively request Index/index
                if CONFIG.get("INDEX_FETCH_READY", False):
                    if proxy_instance:
                        print("[*] 发送 Index/index 请求前，正在停止代理……")
                        stop_proxy_instance()
                        time.sleep(1)
                    CONFIG["AUTO_MONITOR_MODE"] = False
                    CONFIG["INDEX_FETCH_READY"] = False
                    request_index_and_prepare_configs()
                    continue

                if proxy_instance:
                    print("[!] 代理已在运行！ 请先完成登录并等待 UID/SIGN 抓取。")
                    continue

                print("[!] 尚未抓取到有效 UID/SIGN，请先重新输入 -a 启动代理。")

            elif cmd_prefix == '-r':
                if MENU_STATE["selection_unlocked"]:
                    if CONFIG["SELECTED_DIFFICULTY"] is None or CONFIG["SELECTED_STAGE"] is None or CONFIG["SELECTED_TARGET_LABEL"] is None:
                        print("[!] 请先完成关卡菜单选择。")
                        continue
                    if MENU_STATE["awaiting_run_confirm"] or MENU_STATE["awaiting_stop_on_max"]:
                        print("[!] 请先完成满级停机设置与运行前确认，或输入 -back 返回上一级菜单。")
                        continue
                    if CONFIG.get("MODE_NAME") == "team" and not CAPTURED_TEAM_CONFIGS:
                        print("[!] 练级模式尚未抓取到有效梯队配置。请先执行 -a。")
                        continue

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
                print("[*] 将在当前 MACRO 批次结束后停止……")
            elif cmd_prefix == '-Q':
                stop_micro_flag = True
                print("[*] 将在当前 MICRO 轮次结束后停止……")
            elif cmd_prefix == '-s':
                if proxy_instance:
                    CONFIG["AUTO_MONITOR_MODE"] = False
                    stop_proxy_instance()
                    print("[*] 代理已安全停止。")
                else:
                    print("[!] 代理未在运行。")
            elif cmd_prefix == '-E':
                if proxy_instance:
                    proxy_instance.stop()
                set_windows_proxy(False)
                CONFIG["AUTO_MONITOR_MODE"] = False
                stop_macro_flag, stop_micro_flag = True, True
                print("[*] 已安全退出，Windows 代理已恢复。")
                sys.exit(0)
            else:
                if MENU_STATE["selection_unlocked"]:
                    if MENU_STATE["difficulty"] is None:
                        print("[!] 无效输入，请输入：普通 / 紧急 / 夜战 / 13-4，也可输入：p / j / y / 134")
                    elif MENU_STATE["stage"] is None:
                        print("[!] 无效输入，请输入对应关卡名称，例如：A-10，也可输入 a10，或输入 -back / b 返回难度菜单")
                    elif MENU_STATE["awaiting_filter_protection"]:
                        print("[!] 无效输入，请输入 -protecton / -protectoff，或 on / off，或输入 -back / b 返回上一级菜单")
                    elif MENU_STATE["awaiting_stop_on_max"]:
                        print("[!] 无效输入，请输入 -stopmax / -keepmax，或 sm / km，或输入 -back / b 返回上一级菜单")
                    elif MENU_STATE["awaiting_run_confirm"]:
                        print("[!] 无效输入，请输入 -y 确认运行，或输入 -back 返回上一级菜单")
                    elif MENU_STATE["stage"] is not None and get_stage_data(MENU_STATE["difficulty"], MENU_STATE["stage"]):
                        opt_keys = list(get_stage_options(MENU_STATE["difficulty"], MENU_STATE["stage"]).keys())
                        print("[!] 无效输入，请输入 %s，也可直接输入数字 1/2/3...，或输入 -back / b 返回上一级菜单" % " / ".join(opt_keys))
                    else:
                        print("[!] 当前菜单暂未实现。")
                else:
                    print("[!] 未知命令: %s" % cmd)

        except KeyboardInterrupt:
            print("\n[!] Use '-E' to exit safely!")
