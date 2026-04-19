# src/gha/missions/__init__.py

from .f2p import F2PMission
from .pick_coin import PickCoinMission
from .f2p_pr import F2PPRMission
from .epa import EPAFifoMission, EPARRMission

# Route table for mission handlers
MISSION_HANDLERS = {
    "f2p": F2PMission,
    "pick_coin": PickCoinMission,
    "f2p_pr": F2PPRMission,
    "epa_fifo": EPAFifoMission,
    "epa_rr": EPARRMission
}