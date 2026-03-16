"""
Gender Analyzer - Extract and analyze gender statistics for party planning
Ported from stable-clasp-main/function_extractGenderCount.js
"""
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
import logging

from app.db.models import GenderStat, Reservation, ReservationStatus

logger = logging.getLogger(__name__)


class GenderAnalyzer:
    """
    Analyzer for gender statistics
    """

    def __init__(self, db: Session):
        self.db = db

    def get_gender_stats(self, date: datetime) -> Optional[GenderStat]:
        """Get gender statistics from database"""
        date_str = date.strftime("%Y-%m-%d")
        return self.db.query(GenderStat).filter_by(date=date_str).first()

    def extract_gender_stats(self, target_date: datetime) -> Optional[GenderStat]:
        """
        DB Reservation 테이블에서 성비를 집계하여 GenderStat에 upsert.
        (레거시 Google Sheets 연동을 대체)
        """
        date_str = target_date.strftime("%Y-%m-%d")

        # Reservation에서 해당 날짜의 성비 집계
        reservations = (
            self.db.query(Reservation)
            .filter(
                Reservation.check_in_date == date_str,
                Reservation.status != ReservationStatus.CANCELLED,
            )
            .all()
        )

        male_total = 0
        female_total = 0
        for r in reservations:
            if r.male_count is not None and r.female_count is not None:
                male_total += r.male_count
                female_total += r.female_count
            elif r.gender == "남":
                male_total += 1
            elif r.gender == "여":
                female_total += 1

        total = male_total + female_total

        # GenderStat에 upsert
        stat = self.db.query(GenderStat).filter(GenderStat.date == date_str).first()
        if stat:
            stat.male_count = male_total
            stat.female_count = female_total
            stat.participant_count = total
            stat.updated_at = datetime.now()
        else:
            stat = GenderStat(
                date=date_str,
                male_count=male_total,
                female_count=female_total,
                participant_count=total,
            )
            self.db.add(stat)

        self.db.flush()
        return stat

    def generate_invite_message(self, stat: GenderStat) -> str:
        """
        Generate dynamic invite message based on gender ratio

        Args:
            stat: GenderStat record

        Returns:
            Formatted invite message

        Ported from: stable-clasp-main/01_sns.js:260-270 (inviteGirlMessage logic)
        """
        male = stat.male_count
        female = stat.female_count
        total = stat.participant_count

        # Calculate ratio
        if total == 0:
            ratio_str = "아직 참여자가 없습니다"
        else:
            male_pct = round((male / total) * 100)
            female_pct = round((female / total) * 100)
            ratio_str = f"남자 {male_pct}% / 여자 {female_pct}%"

        message = f"""
현재 파티 참여 현황입니다!

총 인원: {total}명
남자: {male}명
여자: {female}명
비율: {ratio_str}

여성 분들의 많은 참여 부탁드립니다! 🎉

파티 시간: 저녁 8시
장소: 스테이블 B동 1층 포차
        """.strip()

        return message

    def calculate_party_balance(self, stat: GenderStat) -> Dict[str, Any]:
        """
        Calculate party gender balance metrics

        Returns:
            Dictionary with balance analysis
        """
        male = stat.male_count
        female = stat.female_count
        total = stat.participant_count

        if total == 0:
            return {
                'balance': 'no_data',
                'recommendation': 'Need participants',
                'male_pct': 0,
                'female_pct': 0
            }

        male_pct = (male / total) * 100
        female_pct = (female / total) * 100

        # Determine balance
        if abs(male_pct - female_pct) < 10:
            balance = 'balanced'
            recommendation = 'Good balance!'
        elif male_pct > female_pct:
            balance = 'male_heavy'
            recommendation = f'Need {int((male - female) / 2)} more women for balance'
        else:
            balance = 'female_heavy'
            recommendation = f'Need {int((female - male) / 2)} more men for balance'

        return {
            'balance': balance,
            'recommendation': recommendation,
            'male_pct': round(male_pct, 1),
            'female_pct': round(female_pct, 1),
            'male_count': male,
            'female_count': female,
            'total': total
        }
