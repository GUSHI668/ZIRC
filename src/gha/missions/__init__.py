# src/gha/missions/__init__.py

from .f2p import F2PMission
from .pick_coin import PickCoinMission
from .pick_and_train import PickAndTrainMission
from .f2p_pr import F2PPRMission
from .epa import EPAFifoMission, EPARRMission
from .epa_134_resource import EPA134ResourceMission
from .greyzone_halloween import GreyZoneHalloweenMission

# Route table for mission handlers
MISSION_HANDLERS = {
    "f2p": F2PMission,
    "f2p_pr": F2PPRMission,
    "pick_coin": PickCoinMission,
    "pick_and_train": PickAndTrainMission,
    "epa_fifo": EPAFifoMission,
    "epa_rr": EPARRMission,
    "epa_134_resource": EPA134ResourceMission,
    "greyzone_halloween": GreyZoneHalloweenMission
}