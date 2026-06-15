"""
Campaign Views — Sub-module package.

Split from the original monolithic views.py for maintainability.

Structure:
    campaign_viewset.py  — CampaignViewSet (CRUD + lifecycle actions)
    message_viewset.py   — CampaignMessageViewSet (per-message scheduling)
"""
from campaigns.views.campaign_viewset import CampaignViewSet
from campaigns.views.message_viewset import CampaignMessageViewSet

__all__ = ["CampaignViewSet", "CampaignMessageViewSet"]
