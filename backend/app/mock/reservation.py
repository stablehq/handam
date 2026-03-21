"""
Mock Reservation Provider for DEMO_MODE.
Returns empty data — no external API calls.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime


class MockReservationProvider:
    """Mock reservation provider that returns empty data for demo mode."""

    async def sync_reservations(self, date: Any = None, from_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return empty list — no Naver API in demo mode."""
        return []

    async def get_reservation_details(self, reservation_id: str) -> Optional[Dict[str, Any]]:
        """Return None — no Naver API in demo mode."""
        return None

    async def fetch_by_checkin_date(self, target_date: str) -> List[Dict[str, Any]]:
        """Return empty list — reconciliation not needed in demo mode."""
        return []

    async def fetch_biz_items(self) -> List[Dict[str, Any]]:
        """Return empty list — no Naver biz items in demo mode."""
        return []
