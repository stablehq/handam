"""
Real SMS Provider - Integration with existing SMS API
Ported from stable-clasp-main/00_main.js and 01_sns.js
"""
from typing import Dict, Any, List
from datetime import datetime
import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)


class RealSMSProvider:
    """Real SMS provider using existing SMS API (URL configured via SMS_API_URL setting)"""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        """
        Initialize SMS provider

        Args:
            api_key: Not used currently (API endpoint doesn't require auth)
            api_secret: Not used currently
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_url = settings.SMS_API_URL

    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        """
        Send single SMS message

        Args:
            to: Phone number (e.g., "01012345678")
            message: Message content
            **kwargs: Additional options (msg_type, testmode_yn)

        Returns:
            Standard SMS response dict (see providers/base.py)
        """
        msg_type = kwargs.get('msg_type', 'LMS')
        testmode = kwargs.get('testmode_yn', 'N')
        timestamp = datetime.now().isoformat()
        message_id = f"real_{int(datetime.now().timestamp())}"

        payload = {
            "msg_type": msg_type,
            "cnt": "1",
            "rec_1": to,
            "msg_1": message,
            "testmode_yn": testmode
        }

        result = await self._send_bulk(payload)
        return {
            "success": result.get("success", False),
            "message_id": message_id,
            "to": to,
            "message": message,
            "timestamp": timestamp,
            "provider": "real",
            "error": result.get("error"),
        }

    async def send_bulk(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """
        Send bulk SMS messages

        Args:
            messages: List of dicts with 'to' and 'message' keys
            **kwargs: Additional options (msg_type, testmode_yn)

        Returns:
            Standard bulk SMS response dict (see providers/base.py)
        """
        timestamp = datetime.now().isoformat()
        total = len(messages)

        if not messages:
            logger.warning("No messages to send")
            return {"success": False, "total": 0, "sent": 0, "failed": 0, "timestamp": timestamp, "provider": "real", "error": "No messages provided"}

        msg_type = kwargs.get('msg_type', 'LMS')
        testmode = kwargs.get('testmode_yn', 'N')

        payload = {
            "msg_type": msg_type,
            "cnt": str(total),
            "testmode_yn": testmode
        }

        for i, msg in enumerate(messages, start=1):
            payload[f"rec_{i}"] = msg['to']
            payload[f"msg_{i}"] = msg['message']

        result = await self._send_bulk(payload)
        if result.get("success"):
            return {"success": True, "total": total, "sent": total, "failed": 0, "timestamp": timestamp, "provider": "real"}
        else:
            return {"success": False, "total": total, "sent": 0, "failed": total, "timestamp": timestamp, "provider": "real", "error": result.get("error")}

    async def _send_bulk(self, payload: Dict[str, str]) -> Dict[str, Any]:
        """
        Internal method to send bulk SMS via API

        Args:
            payload: Full payload dict with msg_type, cnt, rec_N, msg_N

        Returns:
            API response
        """
        try:
            logger.info(f"Sending {payload.get('cnt', 0)} SMS messages (testmode={payload.get('testmode_yn')})")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=30.0
                )

                response.raise_for_status()
                result = response.json()

                logger.info(f"SMS API response: {result}")

                return {
                    "success": True,
                    "count": int(payload.get('cnt', 0)),
                    "response": result
                }

        except httpx.HTTPError as e:
            logger.error(f"HTTP error sending SMS: {e}")
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"Error sending SMS: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def simulate_receive(self, from_: str, to: str, message: str) -> Dict[str, Any]:
        """Simulate receiving SMS (테스트/데모 전용, production에서는 webhook 사용)"""
        timestamp = datetime.now().isoformat()
        message_id = f"real_received_{int(datetime.now().timestamp())}"

        logger.info(f"📥 [SIMULATED SMS RECEIVED] From: {from_}, To: {to}, Message: {message}")

        return {
            "success": True,
            "message_id": message_id,
            "from_": from_,
            "to": to,
            "message": message,
            "timestamp": timestamp,
            "provider": "real",
        }
