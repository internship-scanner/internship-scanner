"""Adapter registry."""

from .ashby import AshbyAdapter
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .smartrecruiters import SmartRecruitersAdapter
from .workday import WorkdayAdapter
from .custom import CustomPlaywrightAdapter

ADAPTERS = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "smartrecruiters": SmartRecruitersAdapter,
    "workday": WorkdayAdapter,
    "custom_playwright": CustomPlaywrightAdapter,
}

__all__ = ["ADAPTERS"]
