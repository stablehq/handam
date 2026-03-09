"""
Real Reservation Provider - Naver Smart Place API integration
Ported from stable-clasp-main/00_main.js + 03_trigger.js
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio
import httpx
import json
import logging

logger = logging.getLogger(__name__)

# Room type mapping (bizItemId -> display name)
ROOM_TYPES = {
    "7358349": "파티만",
    "4341604": "트윈룸",
    "2579095": "남성 4인실",
    "5053141": "여성 4인실",
    "10913": "남성 8인캡슐룸",
    "4206780": "남성 2인캡슐룸",
    "4133363": "여성 2인캡슐룸",
    "7093674": "별관 더블룸",
    "6960578": "별관 남성 더블룸",
    "4368589": "3인실",
    "5314854": "여성 4인캡슐룸",
    "2792572": "여성 4인캡슐룸",
    "3441558": "여성 파티만",
    "5501758": "여성용 트윈룸",
}

# Dormitory/shared room bizItemIds (gender determined by room, not user info)
# Note: bizItemId from Naver API may be int or string; use string sets for safe comparison
DORMITORY_IDS = {"2579095", "5053141", "10913", "4206780", "4133363", "5314854", "2792572"}

# Female room bizItemIds (for gender auto-detection)
FEMALE_ROOM_IDS = {"5053141", "4133363", "5314854", "2792572", "3441558", "5501758"}
MALE_ROOM_IDS = {"2579095", "10913", "4206780", "6960578"}


class RealReservationProvider:
    """Real reservation provider using Naver Smart Place API"""

    def __init__(self, business_id: str, cookie: str):
        self.business_id = business_id
        self.cookie = cookie
        self.base_url = "https://new.smartplace.naver.com"

    def _get_headers(self) -> Dict[str, str]:
        return {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': f'{self.base_url}/bizes/place/{self.business_id}',
            'Sec-Ch-Ua': '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
            'X-Booking-Naver-Role': 'OWNER',
            'Cookie': self.cookie,
        }

    async def sync_reservations(self, target_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Fetch reservations from Naver Smart Place API.

        Uses REGDATE (registration date) filter to catch all newly created
        and cancelled reservations regardless of check-in date.
        Fetches last 7 days of registrations by default.
        """
        now = datetime.now()

        # Fetch by registration date: last 7 days to catch new bookings & cancellations
        end_date = now
        start_date = now - timedelta(days=7)

        start_str = start_date.strftime("%Y-%m-%dT00%%3A00%%3A00.000Z")
        end_str = end_date.strftime("%Y-%m-%dT23%%3A59%%3A59.999Z")

        url = (
            f"{self.base_url}/api/booking/v3.0/businesses/{self.business_id}/bookings"
            f"?bizItemTypes=STANDARD"
            f"&bookingStatusCodes="
            f"&dateDropdownType=CUSTOM"
            f"&dateFilter=REGDATE"
            f"&endDateTime={end_str}"
            f"&maxDays=31"
            f"&nPayChargedStatusCodes="
            f"&orderBy="
            f"&orderByStartDate=ASC"
            f"&paymentStatusCodes="
            f"&searchValue="
            f"&searchValueCode=USER_NAME"
            f"&startDateTime={start_str}"
            f"&page=0"
            f"&size=200"
            f"&noCache={int(now.timestamp() * 1000)}"
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self._get_headers(), timeout=30.0)
                response.raise_for_status()

                data = response.json()
                logger.info(f"Fetched {len(data)} reservations from Naver API (REGDATE last 7 days)")

                # Filter confirmed (RC03)
                confirmed = [
                    item for item in data
                    if item.get('bookingStatusCode') == 'RC03'
                ]

                # Filter cancelled (RC04)
                cancelled = [
                    item for item in data
                    if item.get('bookingStatusCode') == 'RC04'
                ]

                # Remove cancelled that were re-booked (same bizItemId+name+phone in confirmed)
                cancelled_filtered = []
                for cancel_item in cancelled:
                    is_rebooked = any(
                        cancel_item.get('bizItemId') == c.get('bizItemId')
                        and cancel_item.get('name') == c.get('name')
                        and cancel_item.get('phone') == c.get('phone')
                        for c in confirmed
                    )
                    if not is_rebooked:
                        cancelled_filtered.append(cancel_item)

                logger.info(f"Confirmed: {len(confirmed)}, Cancelled: {len(cancelled_filtered)}")

                # Detect multi-bookings
                multi_booking_ids = self._detect_multi_bookings(confirmed)

                # Fetch user info (gender/age) with dedup by userId, parallel with semaphore
                all_items = confirmed + cancelled_filtered
                unique_user_ids = {str(item.get('userId', '')) for item in all_items if item.get('userId')}
                sem = asyncio.Semaphore(10)

                async def _fetch_user(uid: str):
                    async with sem:
                        return uid, await self.get_user_info(uid)

                results = await asyncio.gather(*[_fetch_user(uid) for uid in unique_user_ids])
                user_info_cache = {uid: info for uid, info in results if info}

                logger.info(f"Fetched user info for {len(user_info_cache)}/{len(unique_user_ids)} users")

                def _enrich(reservation: Dict, item: Dict):
                    uid = str(item.get('userId', ''))
                    if uid in user_info_cache:
                        reservation['gender'] = user_info_cache[uid].get('gender', '')
                        reservation['age_group'] = user_info_cache[uid].get('age_group', '')
                        reservation['visit_count'] = user_info_cache[uid].get('visit_count', 0)

                # Convert to standardized format
                reservations = []
                for item in confirmed:
                    reservation = self._parse_reservation(item, multi_booking_ids)
                    _enrich(reservation, item)
                    reservations.append(reservation)

                for item in cancelled_filtered:
                    reservation = self._parse_reservation(item, multi_booking_ids)
                    reservation['status'] = 'cancelled'
                    reservation['cancelled_datetime'] = item.get('cancelledDateTime', '')
                    _enrich(reservation, item)
                    reservations.append(reservation)

                return reservations

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching reservations: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching reservations: {e}")
            return []

    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user information (age, gender, visit count) from Naver API
        """
        url = (
            f"{self.base_url}/api/booking/v3.0/businesses/{self.business_id}/users/{user_id}"
            f"?revisitPeriod=%27%27&noCache={int(datetime.now().timestamp() * 1000)}"
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self._get_headers(), timeout=10.0)
                response.raise_for_status()

                data = response.json()

                age_group = data.get('ageGroup', '')
                # Normalize "19세" to "20"
                import re
                age_match = re.search(r'\d+', age_group)
                age_str = ''
                if age_match:
                    age_str = '20' if age_match.group() == '19' else age_match.group()

                gender = '남' if data.get('sex') == 'MALE' else '여' if data.get('sex') == 'FEMALE' else ''
                visit_count = data.get('completedCount', 0) + 1

                return {
                    'age_group': age_str,
                    'gender': gender,
                    'visit_count': visit_count,
                    'summary': f"{visit_count}번/{age_str}{gender}",
                }

        except Exception as e:
            logger.error(f"Error fetching user info for {user_id}: {e}")
            return None

    async def get_reservation_details(self, reservation_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed reservation info"""
        return None

    def _format_date(self, date_str: Optional[str]) -> str:
        """Format date string to YYYY-MM-DD"""
        if not date_str:
            return ""
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return ""

    def _detect_multi_bookings(self, reservations: List[Dict]) -> set:
        """Detect same person (name+phone) with multiple bookings"""
        booking_map: Dict[str, list] = {}
        for item in reservations:
            key = f"{item.get('name')}_{item.get('phone')}"
            booking_map.setdefault(key, []).append(item.get('bookingId'))

        multi_booking_ids = set()
        for booking_ids in booking_map.values():
            if len(booking_ids) > 1:
                multi_booking_ids.update(booking_ids)
        return multi_booking_ids

    def _parse_reservation(self, item: Dict[str, Any], multi_booking_ids: set) -> Dict[str, Any]:
        """Parse Naver API reservation item to standardized format"""
        biz_item_id = item.get('bizItemId')
        booking_count = item.get('bookingCount', 1)

        # Determine people count from bookingOptionJson if available
        people_count = booking_count
        booking_options = item.get('bookingOptionJson') or []
        if booking_options:
            people_count = booking_options[0].get('bookingCount', booking_count)

        return {
            'external_id': str(item.get('bookingId', '')),
            'naver_booking_id': str(item.get('bookingId', '')),
            'naver_biz_item_id': str(biz_item_id or ''),
            'customer_name': item.get('name', ''),
            'phone': item.get('phone', ''),
            'visitor_name': item.get('visitorName'),
            'visitor_phone': item.get('visitorPhone'),
            'user_id': str(item.get('userId', '')),
            'date': self._format_date(item.get('startDate')),
            'end_date': self._format_date(item.get('endDate')),
            'time': item.get('startTime', ''),
            'status': 'confirmed',
            'source': 'naver',
            'room_type': ROOM_TYPES.get(str(biz_item_id), f'unknown_{biz_item_id}'),
            'biz_item_name': ROOM_TYPES.get(str(biz_item_id), f'unknown_{biz_item_id}'),
            'booking_count': booking_count,
            'people_count': people_count,
            'booking_options': json.dumps(booking_options, ensure_ascii=False) if booking_options else None,
            'custom_form_input': self._extract_custom_form(item),
            'total_price': item.get('totalPrice'),
            'confirmed_at': item.get('confirmedDateTime', ''),
            'confirmed_datetime': item.get('confirmedDateTime', ''),
            'cancelled_datetime': item.get('cancelledDateTime', ''),
            'is_multi_booking': item.get('bookingId') in multi_booking_ids,
            'is_dormitory': str(biz_item_id) in DORMITORY_IDS,
            'raw_data': item,
        }

    def _extract_custom_form(self, item: Dict[str, Any]) -> Optional[str]:
        """Extract custom form input (요청사항) as readable string"""
        custom_forms = item.get('customFormInputJson') or []
        if not custom_forms:
            return None
        parts = []
        for form in custom_forms:
            value = form.get('value', '').strip()
            if value:
                parts.append(value)
        return '; '.join(parts) if parts else None

    async def fetch_biz_items(self) -> List[Dict[str, Any]]:
        """Fetch business item (product/room type) list from Naver API"""
        url = (
            f"{self.base_url}/api/booking/v3.0/businesses/{self.business_id}/biz-items"
            f"?noCache={int(datetime.now().timestamp() * 1000)}"
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self._get_headers(), timeout=15.0)
                response.raise_for_status()
                data = response.json()
                logger.info(f"Fetched {len(data)} biz items from Naver API")

                items = []
                for item in data:
                    items.append({
                        'biz_item_id': str(item.get('bizItemId', '')),
                        'name': item.get('name', ''),
                        'biz_item_type': item.get('bizItemType', ''),
                    })
                return items
        except Exception as e:
            logger.error(f"Error fetching biz items: {e}")
            return []

    @staticmethod
    def get_room_name(biz_item_id: str) -> str:
        """Map bizItemId to room name"""
        return ROOM_TYPES.get(str(biz_item_id), f'방타입{biz_item_id}')
