import hashlib
import base64
import time
import json
import requests
import gzip
import os
import sys
import threading
import frida
import shlex

# ==========================================
# [1] Parameterized Configuration
# ==========================================
CONFIG = {
    "USER_UID": "_InputYourID_",                                                # User ID
    "SIGN_KEY": "1234567890abcdefghijklmnopqrstuv",                             # User's sign key
    "MACRO_LOOPS": 200,                                                         # total f2p times = MACRO_LOOPS * MISSIONS_PER_RETIRE
    "MISSIONS_PER_RETIRE": 50,                                                  # Retire the doll after `MISSIONS_PER_RETIRE` times
    "SQUAD_ID": 106360,                                                         # BGM-71's ID
    "PROCESS_NAME": "GrilsFrontLine.exe",                                       # CN's steam version program with typo
    "BASE_URL": "http://gfcn-game.gw.merge.sunborngame.com/index.php/1000"      # URL of CN's M4A1, replace the URL if you are using a different server
}

# ==========================================
# [2] Threading State Flags
# ==========================================
# Threading control
current_worker_thread = None
worker_mode = None  # 'i' for Frida, 'r' for Farm, None for Idle

# Stop flags
stop_macro_flag = False
stop_micro_flag = False
stop_frida_flag = False

# ==========================================
# [3] GFL Crypto Core
# ==========================================
def md5(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def gf_authcode(string: str, operation: str = 'ENCODE', key: str = '', expiry: int = 3600) -> str:
    key_hash = md5(key)
    keya = md5(key_hash[0:16])
    keyb = md5(key_hash[16:32])
    
    cryptkey = keyb + md5(keyb)
    key_length = len(cryptkey)
    
    if operation == 'DECODE':
        try:
            b64_str = string.strip()
            b64_str = b64_str + "=" * ((4 - len(b64_str) % 4) % 4)
            string_bytes = base64.b64decode(b64_str)
        except Exception:
            return ""
    else:
        expiry_time = (expiry + int(time.time())) if expiry > 0 else 0
        header = f"{expiry_time:010d}"
        checksum = md5(string + keya)[0:16]
        payload = header + checksum + string
        string_bytes = payload.encode('utf-8')

    string_length = len(string_bytes)
    result = bytearray()
    box = list(range(256))
    rndkey = [ord(cryptkey[i % key_length]) for i in range(256)]
    
    j = 0
    for i in range(256):
        j = (j + box[i] + rndkey[i]) % 256
        box[i], box[j] = box[j], box[i]
        
    a = j = 0
    for i in range(string_length):
        a = (a + 1) % 256
        j = (j + box[a]) % 256
        box[a], box[j] = box[j], box[a]
        result.append(string_bytes[i] ^ box[(box[a] + box[j]) % 256])
        
    if operation == 'DECODE':
        res_str = bytes(result)
        try:
            ext_bytes = res_str[26:]
            if ext_bytes.startswith(b'\x1f\x8b'):
                try:
                    ext_bytes = gzip.decompress(ext_bytes)
                except Exception:
                    pass
            ext_text = ext_bytes.decode('utf-8', errors='ignore').strip('\0')
            return ext_text
        except Exception:
            return ""
    else:
        return base64.b64encode(bytes(result)).decode('utf-8')

# ==========================================
# [4] GFL API Client
# ==========================================
class GFLClient:
    def __init__(self, uid: str, sign_key: str):
        self.uid = uid
        self.sign_key = sign_key
        self.req_idx = 1
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "UnityPlayer/2018.4.36f1 (UnityWebRequest/1.0, libcurl/7.52.0-DEV)",
            "X-Unity-Version": "2018.4.36f1",
            "Content-Type": "application/x-www-form-urlencoded"
        })
        self.base_url = CONFIG["BASE_URL"]

    def _get_req_id(self):
        timestamp = int(time.time())
        req_id = f"{timestamp}{self.req_idx:05d}"
        self.req_idx += 1
        return req_id

    def send_request(self, endpoint: str, payload: dict, max_retries: int = 3):
        json_str = json.dumps(payload, separators=(',', ':'))
        encrypted = gf_authcode(json_str, 'ENCODE', self.sign_key)
        
        data = {
            "uid": self.uid,
            "req_id": self._get_req_id(),
            "outdatacode": encrypted
        }

        url = f"{self.base_url}{endpoint}"
        
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, data=data, timeout=15)
                text = response.text.strip()
                
                if text.startswith("#"):
                    decrypted_str = gf_authcode(text[1:], 'DECODE', self.sign_key)
                    if decrypted_str:
                        try:
                            return json.loads(decrypted_str)
                        except json.JSONDecodeError:
                            return {"error_local": "JSON parse error", "raw": decrypted_str}
                    else:
                        return {"error_local": "Decryption failed.", "raw": text}
                elif text.startswith("{") or text.startswith("["):
                    try:
                        return json.loads(text)
                    except:
                        pass
                elif text.startswith("1"):
                    return {"success": True, "raw": text}
                    
                return {"error_local": "Unexpected plaintext response", "raw": text}
                
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    return {"error_local": f"Network Exception after {max_retries} retries: {str(e)}"}
                print(f"[!] Network error on {endpoint}, retrying ({attempt + 1}/{max_retries})...")
                time.sleep(2)

# ==========================================
# [5] Auto Farm Logic
# ==========================================
def abort_stuck_mission(client: GFLClient, mission_id: int):
    print(f"[!] Attempting to Force Abort Mission {mission_id} to clear state...")
    resp = client.send_request("/Mission/abortMission", {"mission_id": mission_id})
    if resp.get("success") or "mission_win_result" in str(resp):
        print("[+] Mission aborted successfully. State cleared.")
    else:
        print("[-] Abort returned:", resp)
    time.sleep(2)

def check_step_error(resp: dict, step_name: str) -> bool:
    if "error_local" in resp:
        print(f"[-] {step_name} Local Error: {resp['error_local']}")
        return True
    if "error" in resp:
        print(f"[-] {step_name} Server Error: {resp['error']}")
        return True
    return False

def check_drop_result(response_data: dict) -> list:
    collected_guns = []
    win_result = response_data.get("mission_win_result", {})
    if not win_result:
        print("[!] Flow finished, but no 'mission_win_result' found.")
        return collected_guns
        
    reward_guns = win_result.get("reward_gun", [])
    if reward_guns:
        for gun in reward_guns:
            gun_id = gun.get('gun_id')
            gun_uid = int(gun.get('gun_with_user_id'))
            print(f"[+] MISSION CLEARED! Got T-Doll! Gun ID: {gun_id} | UID: {gun_uid}")
            
            current_time = time.strftime("%H:%M:%S")
            print(f"\033[36m[T] {current_time}\033[0m")
            
            collected_guns.append(gun_uid)
    else:
        print("[+] Mission cleared successfully. (No T-Doll drop this time)")
        
    return collected_guns

def farm_mission_11880(client: GFLClient, squad_id: int):
    mission_id = 11880
    GUIDE_COURSE = [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,1,1,1,1,0,1,0,0,0,0,0,0,1,1,1,1,1,1,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,1,0,0,0,0,0,0,1,1,1,0,0,1,0,1,1,1,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,1,1,1,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,1,1,1,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]

    resp = client.send_request("/Mission/combinationInfo", {"mission_id": mission_id})
    if check_step_error(resp, "combinationInfo"): return None
    
    start_payload = {
        "mission_id": mission_id, "spots": [],
        "squad_spots": [{"spot_id": 901926, "squad_with_user_id": squad_id, "battleskill_switch": 1}],
        "sangvis_spots": [], "vehicle_spots": [], "ally_spots": [], "mission_ally_spots": [],
        "ally_id": int(time.time())
    }
    resp = client.send_request("/Mission/startMission", start_payload)
    if check_step_error(resp, "startMission"): return None
    
    guide_inner_json = json.dumps({"course": GUIDE_COURSE}, separators=(',', ':'))
    resp = client.send_request("/Index/guide", {"guide": guide_inner_json})
    if check_step_error(resp, "Index/guide"): return None
    
    time.sleep(0.5)
    resp = client.send_request("/Mission/endTurn", {})
    if check_step_error(resp, "endTurn"): return None
    
    time.sleep(0.2)
    resp = client.send_request("/Mission/startEnemyTurn", {})
    if check_step_error(resp, "startEnemyTurn"): return None
    
    time.sleep(0.2)
    resp = client.send_request("/Mission/endEnemyTurn", {})
    if check_step_error(resp, "endEnemyTurn"): return None
    
    time.sleep(0.2)
    final_resp = client.send_request("/Mission/startTurn", {})
    if check_step_error(final_resp, "startTurn"): return None
    
    return check_drop_result(final_resp)

def retire_guns(client: GFLClient, gun_uids: list):
    if not gun_uids:
        print("[*] No T-Dolls to retire in this batch.")
        return
    
    print(f"[*] Submitting {len(gun_uids)} T-Dolls for Auto-Retire...")
    resp = client.send_request("/Gun/retireGun", gun_uids)
    
    if resp.get("success"):
        print("[+] Auto-Retire Successful! Workspace Cleared.")
    else:
        print(f"[-] Retire Failed: {resp}")

# ==========================================
# [6] Worker Threads Logic
# ==========================================

# Extract Sign Key Only
FRIDA_JS_SCRIPT = """
var addr_Encode = 28343008; // AC.AuthCode$$Encode

function getCSharpString(ptr) {
    if (ptr.isNull()) return null;
    try {
        var len = ptr.add(0x10).readU32();
        if (len === 0) return "";
        return ptr.add(0x14).readUtf16String(len);
    } catch (e) {
        return null;
    }
}

function hook() {
    var gameAssembly = Process.findModuleByName("GameAssembly.dll");
    if (!gameAssembly) {
        setTimeout(hook, 1000);
        return;
    }

    var targetC2S = gameAssembly.base.add(addr_Encode);
    Interceptor.attach(targetC2S, {
        onEnter: function(args) {
            var strKey = getCSharpString(args[1]);
            if (strKey && strKey.length > 0) {
                send({ id: "KEY", content: strKey });
            }
        }
    });
}

setTimeout(hook, 1000);
"""

def on_frida_message(message, data):
    if message['type'] == 'send':
        payload = message['payload']
        if payload.get('id') == 'KEY':
            key = payload.get('content')
            if key != CONFIG["SIGN_KEY"]:
                CONFIG["SIGN_KEY"] = key
                print(f"\n[+] [Frida] New SIGN_KEY Captured and Updated: {key}")

def frida_worker():
    global stop_frida_flag, worker_mode, current_worker_thread
    
    print(f"[*] Attaching Frida to process: {CONFIG['PROCESS_NAME']} ...")
    try:
        session = frida.attach(CONFIG['PROCESS_NAME'])
        script = session.create_script(FRIDA_JS_SCRIPT)
        script.on('message', on_frida_message)
        script.load()
        
        print("[*] Frida successfully injected. Waiting for network traffic...")
        print("[*] Type -q or -Q to safely detach Frida.")
        
        while not stop_frida_flag:
            time.sleep(0.5)
            
        session.detach()
        print("[*] Frida detached safely.")
    except Exception as e:
        print(f"[!] Frida Error: {e}")
        print("[!] Please ensure the game is running.")
        
    worker_mode = None
    current_worker_thread = None

def farm_worker():
    global stop_macro_flag, stop_micro_flag, worker_mode, current_worker_thread
    
    client = GFLClient(CONFIG["USER_UID"], CONFIG["SIGN_KEY"])

    print("=========================================")
    print("   GFL Protocol Auto-Farming Started     ")
    print("=========================================")

    for macro in range(1, CONFIG["MACRO_LOOPS"] + 1):
        if stop_macro_flag:
            print("[*] Macro loop stop requested. Breaking outer loop.")
            break
            
        print(f"\n=========================================")
        print(f"  >>> MACRO BATCH {macro} / {CONFIG['MACRO_LOOPS']} STARTING <<<")
        print(f"=========================================")
        
        batch_collected_guns = []
        
        for micro in range(1, CONFIG["MISSIONS_PER_RETIRE"] + 1):
            if stop_micro_flag or stop_macro_flag:
                print("[*] Micro loop stop requested. Breaking inner loop.")
                break
                
            print(f"\n--- Mission Run {micro} / {CONFIG['MISSIONS_PER_RETIRE']} (Batch {macro}) ---")
            
            dropped_guns = farm_mission_11880(client, CONFIG["SQUAD_ID"])
            
            if dropped_guns is None:
                abort_stuck_mission(client, 11880)
                print("[!] Skipping to next run to recover state...")
                time.sleep(3)
                continue
                
            batch_collected_guns.extend(dropped_guns)
            
            if micro < CONFIG["MISSIONS_PER_RETIRE"]:
                time.sleep(1) 
                
        # 边界保护：无论循环是正常结束还是被-Q中断，只要手里有枪，必须先拆解清理
        print(f"\n[+] Batch {macro} completed or interrupted. Preparing to retire...")
        retire_guns(client, batch_collected_guns)
        time.sleep(2)
        
        # 如果是-Q引发的单局结束，拆完之后就退出大循环
        if stop_micro_flag:
            break
            
    print("\n[*] All farming runs ended gracefully.")
    worker_mode = None
    current_worker_thread = None

# ==========================================
# [7] Interactive Command Line Interface
# ==========================================

def print_menu():
    print("\n================= MENU =================")
    print(" -i : Inject Frida to capture SIGN_KEY")
    print(" -r : Run Auto-Farming")
    print(" -q : Stop Frida OR Stop Farm after current Macro")
    print(" -Q : Stop Frida OR Stop Farm after current Micro")
    print(" -s : Set configs (e.g. -s --uid 123 --key abc)")
    print(" -E : Exit program safely")
    print("========================================\n")

def process_settings(cmd_str):
    try:
        parts = shlex.split(cmd_str)[1:] # Remove '-s'
        for i in range(0, len(parts), 2):
            key = parts[i]
            val = parts[i+1] if i+1 < len(parts) else None
            
            if key == '--uid' and val:
                CONFIG["USER_UID"] = val
                print(f"[*] Updated USER_UID = {val}")
            elif key == '--key' and val:
                CONFIG["SIGN_KEY"] = val
                print(f"[*] Updated SIGN_KEY = {val}")
            elif key == '--loop' and val:
                CONFIG["MACRO_LOOPS"] = int(val)
                print(f"[*] Updated MACRO_LOOPS = {val}")
            elif key == '--retire' and val:
                CONFIG["MISSIONS_PER_RETIRE"] = int(val)
                print(f"[*] Updated MISSIONS_PER_RETIRE = {val}")
            else:
                print(f"[!] Unrecognized setting format: {key} {val}")
    except Exception as e:
        print(f"[!] Failed to parse settings: {e}")

def main_loop():
    global current_worker_thread, worker_mode
    global stop_macro_flag, stop_micro_flag, stop_frida_flag
    
    print_menu()
    
    while True:
        try:
            cmd_input = input("GFL-F2P> ").strip()
            if not cmd_input:
                continue
                
            cmd = cmd_input.split()[0]
            
            if cmd == '-i':
                if current_worker_thread and current_worker_thread.is_alive():
                    print("[!] A task is already running. Please stop it first (-q or -Q).")
                else:
                    stop_frida_flag = False
                    worker_mode = 'i'
                    current_worker_thread = threading.Thread(target=frida_worker)
                    current_worker_thread.daemon = True
                    current_worker_thread.start()
                    
            elif cmd == '-r':
                if current_worker_thread and current_worker_thread.is_alive():
                    print("[!] A task is already running. Please stop it first (-q or -Q).")
                else:
                    stop_macro_flag = False
                    stop_micro_flag = False
                    worker_mode = 'r'
                    current_worker_thread = threading.Thread(target=farm_worker)
                    current_worker_thread.daemon = True
                    current_worker_thread.start()
                    
            elif cmd == '-q':
                if worker_mode == 'i':
                    print("[*] Stopping Frida...")
                    stop_frida_flag = True
                elif worker_mode == 'r':
                    print("[*] Boundary Protection: Will safely exit after current MACRO batch completes...")
                    stop_macro_flag = True
                else:
                    print("[*] No task is currently running.")
                    
            elif cmd == '-Q':
                if worker_mode == 'i':
                    print("[*] Stopping Frida...")
                    stop_frida_flag = True
                elif worker_mode == 'r':
                    print("[*] Boundary Protection: Will safely exit after current MICRO run completes...")
                    stop_micro_flag = True
                else:
                    print("[*] No task is currently running.")
                    
            elif cmd == '-s':
                if current_worker_thread and current_worker_thread.is_alive():
                    print("[!] Cannot change settings while a task is running. Stop it first.")
                else:
                    process_settings(cmd_input)
                    
            elif cmd == '-E':
                print("[*] Emergency Exit requested. Cleaning up resources...")
                stop_frida_flag = True
                stop_macro_flag = True
                stop_micro_flag = True
                if current_worker_thread and current_worker_thread.is_alive():
                    print("[*] Waiting for background threads to terminate safely...")
                    current_worker_thread.join(timeout=3)
                print("[*] Goodbye!")
                sys.exit(0)
                
            else:
                print(f"[!] Unknown command: {cmd}")
                print_menu()
                
        except KeyboardInterrupt:
            print("\n[!] Please use '-E' to exit the program safely to avoid server desync.")
            
if __name__ == '__main__':
    main_loop()