# src/gha/parser/skill.py

from .base import BaseParser

# Total EXP required to reach level 115 (unlock skill 2)
EXP_REQUIREMENT_SKILL_2 = 10448800

class SkillTrainParser(BaseParser):
    def parse(self, raw_data: dict) -> list:
        """
        Scans Index/index for locked T-Dolls with skill levels < 10.
        Returns a queue (list) of dictionaries containing training candidates.
        """
        candidates = []
        
        guns = raw_data.get("gun_with_user_info", [])
        if not isinstance(guns, list):
            return candidates
            
        for gun in guns:
            if str(gun.get("is_locked", "0")) != "1":
                continue
                
            gun_uid = int(gun.get("id", 0))
            if gun_uid == 0:
                continue

            raw_exp = int(gun.get("gun_exp", 0))
            has_skill_2 = raw_exp >= EXP_REQUIREMENT_SKILL_2

            for skill_no in (1, 2):
                if skill_no == 2 and not has_skill_2:
                    continue
                    
                skill_lv = int(gun.get(f"skill{skill_no}", 1 if skill_no == 2 else 0))
                if skill_lv <= 0: 
                    skill_lv = 1
                
                if skill_lv < 10:
                    candidates.append({
                        "gun_uid": gun_uid,
                        "skill_no": skill_no,
                        "current_lv": skill_lv
                    })
                    
        print(f"[+] SkillTrainParser: Found {len(candidates)} skills requiring training.")
        return candidates