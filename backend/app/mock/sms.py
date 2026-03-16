"""
Mock SMS Provider for demo mode.
Logs SMS sending instead of actually sending, and allows simulating SMS reception.
"""
import logging
from typing import Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


class MockSMSProvider:
    """Mock SMS provider - logs instead of sending real SMS"""

    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        """Mock SMS sending - only logs the action"""
        timestamp = datetime.now().isoformat()
        message_id = f"mock_{int(datetime.now().timestamp())}"

        # This is what client sees during demo
        logger.info(
            f"📤 [MOCK SMS SENT]\n"
            f"   To: {to}\n"
            f"   Message: {message}\n"
            f"   Timestamp: {timestamp}\n"
            f"   Message ID: {message_id}\n"
            f"   ⚠️  In production mode, this will send actual SMS via API"
        )

        return {
            "success": True,
            "message_id": message_id,
            "to": to,
            "message": message,
            "timestamp": timestamp,
            "provider": "mock",
        }

    async def send_bulk(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """Mock bulk SMS sending"""
        timestamp = datetime.now().isoformat()

        logger.info(
            f"📤 [MOCK BULK SMS SENT]\n"
            f"   Count: {len(messages)}\n"
            f"   Timestamp: {timestamp}\n"
            f"   ⚠️  In production mode, this will send actual bulk SMS via API"
        )

        for i, msg in enumerate(messages):
            logger.info(f"   [{i+1}] To: {msg.get('to')} | Message: {msg.get('message', '')[:50]}...")

        return {
            "success": True,
            "total": len(messages),
            "sent": len(messages),
            "failed": 0,
            "timestamp": timestamp,
            "provider": "mock",
        }

    async def simulate_receive(self, from_: str, to: str, message: str) -> Dict[str, Any]:
        """Simulate receiving SMS (triggered by frontend simulator)"""
        timestamp = datetime.now().isoformat()
        message_id = f"mock_received_{int(datetime.now().timestamp())}"

        logger.info(
            f"📥 [MOCK SMS RECEIVED]\n"
            f"   From: {from_}\n"
            f"   To: {to}\n"
            f"   Message: {message}\n"
            f"   Timestamp: {timestamp}\n"
            f"   Message ID: {message_id}\n"
            f"   ⚠️  In production mode, this will be triggered by real webhook"
        )

        return {
            "success": True,
            "message_id": message_id,
            "from_": from_,
            "to": to,
            "message": message,
            "timestamp": timestamp,
            "provider": "mock",
        }
