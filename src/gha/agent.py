# src/gha/agent.py

import os
import sys
import time
import json
import platform
import types
from datetime import datetime

# Cross-platform compatibility for gflzirc
if platform.system() != "Windows":
    sys.modules["winreg"] = types.ModuleType("winreg")

from gflzirc import (
    GFLClient, SERVERS, API_GUN_RETIRE, API_MISSION_ABORT
)

# Import our modular mission handlers
from missions import MISSION_HANDLERS

# Constants
MAX_RUNTIME_SEC = 5 * 3600 + 30 * 60  # 5 hours 30 mins
MAX_CONSECUTIVE_ERRORS = 5

class GFLAgent:
    def __init__(self):
        self.start_time = time.time()
        self.total_dolls = 0
        self.macro_count = 0
        self.error_count = 0
        
        # 1. Fetch raw Environment Variables
        self.account_idx = int(os.environ.get("GFL_ACCOUNT_INDEX", "0"))
        self.mission_type = os.environ.get("GFL_MISSION_TYPE", "f2p")
        
        is_epa = self.mission_type.startswith("epa")
        config_env_key = "GFL_EPA_CONFIG" if is_epa else "GFL_CONFIG"
        config_raw = os.environ.get(config_env_key, "{}").strip()
        
        sign_raw = os.environ.get("GFL_SIGN_KEY", "").strip()
        device_raw = os.environ.get("GFL_USER_DEVICE", "").strip()

        # 2. Parse Configs safely
        try:
            parsed_configs = json.loads(config_raw)
            # Normalize to list if single dict is provided
            if not isinstance(parsed_configs, list):
                parsed_configs = [parsed_configs]
                
            self.config = parsed_configs[self.account_idx]
        except Exception as e:
            print(f"[-] FATAL: Failed to parse {config_env_key} JSON. Exception: {e}")
            sys.exit(1)
            
        # 3. Parse Array Secrets Safely (Sign Key & Device)
        self.sign_key = self._extract_array_secret(sign_raw, self.account_idx)
        self.user_device = self._extract_array_secret(device_raw, self.account_idx)
        
        uid = str(self.config.get("USER_UID", "")).strip()
        server_key = self.config.get("SERVER_KEY", "M4A1")
        self.base_url = SERVERS.get(server_key)
        
        # Resolve Mission Handler
        handler_class = MISSION_HANDLERS.get(self.mission_type)
        if not handler_class:
            print(f"[-] FATAL: Unknown mission type '{self.mission_type}'.")
            sys.exit(1)
        self.mission_handler = handler_class(self)
        
        # === CONFIGURATION AUDIT ===
        print(f"\n================ ACCOUNT [{self.account_idx}] AUDIT ================")
        print(f"[*] Mission Type : {self.mission_type.upper()}")
        
        masked_uid = uid[:-3] + "***" if len(uid) > 3 else "INVALID"
        print(f"[*] USER_UID     : {masked_uid} (Length: {len(uid)})")
        
        if len(self.sign_key) > 12:
            masked_sign = self.sign_key[:8] + "*" * (len(self.sign_key)-12) + self.sign_key[-4:]
            print(f"[*] SIGN_KEY     : {masked_sign} (Length: {len(self.sign_key)})")
        else:
            print(f"[*] SIGN_KEY     : INVALID_OR_TOO_SHORT")
            
        print(f"[*] SERVER_KEY   : {server_key}")
        print(f"[*] BASE_URL     : {self.base_url}")
        
        if is_epa:
            teams = self.config.get("TEAMS", [])
            print(f"[*] EPA Teams    : {len(teams)} Echelons Configured")
            print(f"[*] USER_DEVICE  : {self.user_device[:8]}... (Length: {len(self.user_device)})")
            
        print("=====================================================\n")

        if not self.sign_key or not uid or len(self.sign_key) < 12:
            print("[-] FATAL: Missing or Invalid UID / SIGN_KEY.")
            sys.exit(1)
        if not self.base_url:
            print(f"[-] FATAL: Invalid SERVER_KEY: {server_key}.")
            sys.exit(1)
            
        self.client = GFLClient(uid, self.sign_key, self.base_url)

    def _extract_array_secret(self, raw_str: str, target_idx: int) -> str:
        if not raw_str: return ""
        try:
            parsed = json.loads(raw_str)
            if not isinstance(parsed, list):
                parsed = [str(parsed)]
        except Exception:
            parsed = [raw_str]
        val = parsed[target_idx] if target_idx < len(parsed) else parsed[-1]
        return val.strip().strip('"').strip("'")

    def write_summary(self, status="Running"):
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if not summary_path:
            return
            
        elapsed = int(time.time() - self.start_time)
        hours, rem = divmod(elapsed, 3600)
        mins, secs = divmod(rem, 60)
        time_str = f"{hours:02d}h {mins:02d}m {secs:02d}s"
        
        content = (
            f"### GFL Auto-Farm Report: Account [{self.account_idx}] ({self.mission_type.upper()})\n"
            f"| Metric | Value |\n"
            f"| ------ | ----- |\n"
            f"| **Status** | {status} |\n"
            f"| **Runtime** | {time_str} |\n"
            f"| **Macros Completed** | {self.macro_count} |\n"
            f"| **Total Dolls Dropped** | {self.total_dolls} |\n"
            f"| **Timestamp** | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} |\n"
            f"---\n"
        )
        with open(summary_path, "w") as f:
            f.write(content)

    def safe_request(self, api_endpoint: str, payload: dict, step_name: str, max_retries=3):
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.client.send_request(api_endpoint, payload)
                if resp is not None:
                    return resp
            except Exception as e:
                print(f"[-] {step_name}: Exception -> {e}. (Attempt {attempt}/{max_retries})")
            
            if attempt < max_retries:
                time.sleep(3)
                
        return {"error_local": "Max retries reached or empty server response."}

    def check_step_error(self, resp, step_name: str) -> bool:
        # 只检查 isinstance(dict) 时的 error_local 和 error
        if resp is None:
            self.error_count += 1
            return True
            
        if isinstance(resp, dict):
            if "error_local" in resp:
                print(f"[-] {step_name} Local Error: {resp['error_local']}")
                if 'raw' in resp:
                    print(f"[DEBUG] Raw Server Payload: {resp['raw']}")
                self.error_count += 1
                return True
            if "error" in resp:
                print(f"[-] {step_name} Server Error: {resp['error']}")
                self.error_count += 1
                return True
        
        # 只要没有明确抛出错误，就重置错误计数器并放行
        self.error_count = 0
        return False

    def check_drop_result(self, response_data) -> list:
        collected_guns = []
        if not isinstance(response_data, dict): return collected_guns
        win_result = response_data.get("mission_win_result", {})
        if not win_result: return collected_guns
        reward_guns = win_result.get("reward_gun", [])
        if reward_guns:
            for gun in reward_guns:
                gun_id = gun.get('gun_id')
                gun_uid = int(gun.get('gun_with_user_id'))
                print(f"[+] Got T-Doll! Gun ID: {gun_id} | UID: {gun_uid} | Time: {time.strftime('%H:%M:%S')}")
                collected_guns.append(gun_uid)
        return collected_guns

    def parse_random_node_drop(self, resp_data):
        if not isinstance(resp_data, dict): return
        keys = list(resp_data.keys())
        try:
            target_idx = keys.index("building_defender_change") - 1
            if target_idx >= 0:
                reward_key = keys[target_idx]
                if reward_key not in ["trigger_para", "mission_win_step_control_ids", "spot_act_info"]:
                    print(f"[+] Random Node Drop Captured -> {reward_key} : {resp_data[reward_key]}")
        except ValueError:
            pass

    def retire_guns(self, gun_uids: list):
        if not gun_uids: return
        print(f"[*] Submitting {len(gun_uids)} T-Dolls for Auto-Retire...")
        resp = self.safe_request(API_GUN_RETIRE, gun_uids, "retireGuns")
        if isinstance(resp, dict) and resp.get("success"): 
            print("[+] Auto-Retire Successful!")
        else: 
            print(f"[-] Retire Failed: {resp}")

    def run(self):
        print(f"=== GHA Auto-Farming Started: {self.mission_type.upper()} [Acct: {self.account_idx}] ===")
        
        # Run Mission Specific Pre-flight Check
        self.mission_handler.prepare()
        
        macro_target = self.config.get("MACRO_LOOPS", 200)
        micro_target = self.config.get("MISSIONS_PER_RETIRE", 50)
        
        for macro in range(1, macro_target + 1):
            print(f"\n--- MACRO BATCH {macro} / {macro_target} ---")
            batch_guns = []
            
            for micro in range(1, micro_target + 1):
                if self.error_count >= MAX_CONSECUTIVE_ERRORS:
                    print("\n[!] FATAL: Too many consecutive errors. Server WAF blocked or Auth Expired.")
                    self.write_summary(status="FATAL ERROR (Aborted)")
                    sys.exit(1)
                    
                print(f"[*] Micro Run: {micro}/{micro_target}")
                
                # Use modular handler
                dropped = self.mission_handler.farm()
                    
                if dropped is None:
                    # Generic fallback
                    abort_id = self.mission_handler.get_mission_id()
                    self.safe_request(API_MISSION_ABORT, {"mission_id": abort_id}, "missionAbort", max_retries=1)
                    time.sleep(3)
                    continue
                    
                batch_guns.extend(dropped)
                self.total_dolls += len(dropped)
                time.sleep(1)
                
            self.retire_guns(batch_guns)
            self.macro_count += 1
            self.write_summary(status="Running")
            time.sleep(2)
            
            elapsed = time.time() - self.start_time
            if elapsed > MAX_RUNTIME_SEC:
                print(f"\n[!] Time limit reached ({elapsed}s). Preparing to respawn.")
                with open("respawn.flag", "w") as f:
                    f.write("1")
                self.write_summary(status="Timeout Reached - Spawning Next Job")
                sys.exit(0)
                
        print("\n[*] All macros completed gracefully.")
        self.write_summary(status="Completed")

if __name__ == '__main__':
    agent = GFLAgent()
    agent.run()