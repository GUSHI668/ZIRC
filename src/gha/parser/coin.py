# src/gha/parser/coin.py

from .base import BaseParser

class CoinParser(BaseParser):
    def parse(self, raw_data: dict):
        """
        Extracts the 'coin2' (Medium Training Data) value from the node drop payload.
        Returns the integer amount, or None if not found.
        """
        if not isinstance(raw_data, dict): 
            return None
            
        keys = list(raw_data.keys())
        try:
            target_idx = keys.index("building_defender_change") - 1
            if target_idx >= 0:
                reward_key = keys[target_idx]
                
                if reward_key == "coin2":
                    return int(raw_data[reward_key])
                    
                reward_val = raw_data[reward_key]
                if isinstance(reward_val, dict) and "coin2" in reward_val:
                    return int(reward_val["coin2"])
        except ValueError:
            pass
            
        return None