"""
Seed data for demo mode - creates sample messages, reservations, rules, documents,
message templates, campaign logs, and gender statistics
"""
from sqlalchemy.orm import Session
from app.db.database import SessionLocal, init_db
from app.db.models import (
    Message, Reservation, Rule, Document,
    MessageTemplate, CampaignLog, GenderStat, Room,
    User, UserRole,
    MessageDirection, MessageStatus, ReservationStatus,
)
from app.auth.utils import hash_password
from datetime import datetime, timedelta
import logging
import json
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_sample_messages(db: Session):
    """Create sample conversation threads matching reservation phone numbers"""
    now = datetime.utcnow()
    our = "010-9999-0000"

    # Conversations — phone numbers match reservations (010-{1000+i}-{2000+i})
    # Each conversation is a list of (direction, message, minutes_ago, source, confidence, needs_review)
    conversations = [
        # 김철수 (010-1000-2000) — 영업시간 문의, 3턴
        ("010-1000-2000", [
            ("in",  "안녕하세요, 영업시간이 어떻게 되나요?",       120, None, None, False),
            ("out", "평일 09:00-18:00, 주말 10:00-17:00 영업합니다. 공휴일은 휴무입니다.", 119, "rule", 0.95, False),
            ("in",  "주말에도 예약 가능한가요?",                    60, None, None, False),
            ("out", "네, 주말에도 예약 가능합니다. 네이버 예약이나 전화로 예약해주세요.", 59, "rule", 0.92, False),
            ("in",  "감사합니다!",                                  30, None, None, False),
            ("out", "감사합니다. 좋은 하루 보내세요!",              29, "llm", 0.80, False),
        ]),
        # 이영희 (010-1001-2001) — 예약 변경, 2턴 + 검토 필요 케이스
        ("010-1001-2001", [
            ("in",  "예약 변경하고 싶은데요, 2월 12일로 바꿀 수 있나요?", 180, None, None, False),
            ("out", "예약 변경은 고객센터(010-9999-0000)로 전화 부탁드립니다. 영업시간 내에 연락주시면 바로 처리해드리겠습니다.", 179, "llm", 0.78, False),
            ("in",  "전화 말고 문자로 처리 안 되나요?",             90, None, None, True),
        ]),
        # 박민수 (010-1002-2002) — 가격 문의, 3턴
        ("010-1002-2002", [
            ("in",  "가격이 얼마인가요?",                         300, None, None, False),
            ("out", "서비스 종류에 따라 가격이 다릅니다. 자세한 상담은 전화 주세요.", 299, "rule", 0.85, False),
            ("in",  "스탠다드룸 1박 기준으로요",                   240, None, None, False),
            ("out", "스탠다드룸 1박 기준 50,000원입니다. 주말/공휴일은 10,000원 추가됩니다.", 239, "llm", 0.72, False),
            ("in",  "카드 결제 되나요?",                           200, None, None, False),
            ("out", "네, 카드 결제 가능합니다. 현장에서 결제해주시면 됩니다.", 199, "llm", 0.80, False),
        ]),
        # 정수진 (010-1003-2003) — 주차 + 위치 문의
        ("010-1003-2003", [
            ("in",  "주차 가능한가요?",                            400, None, None, False),
            ("out", "건물 지하 1층에 무료 주차 가능합니다.",        399, "rule", 0.92, False),
            ("in",  "위치가 정확히 어디예요?",                      350, None, None, False),
            ("out", "서울시 강남구 테헤란로 123 (강남역 2번 출구에서 도보 5분)", 349, "rule", 0.95, False),
        ]),
        # 최동욱 (010-1004-2004) — 할인 문의, 검토 필요
        ("010-1004-2004", [
            ("in",  "할인 행사 같은 거 있나요?",                   500, None, None, True),
            ("in",  "단체 할인도 궁금합니다",                      480, None, None, True),
        ]),
        # 강미영 (010-1005-2005) — 취소 문의
        ("010-1005-2005", [
            ("in",  "예약 취소하고 싶습니다",                      600, None, None, False),
            ("out", "예약 취소는 1일 전까지 무료 취소 가능합니다. 예약번호를 알려주시면 처리해드리겠습니다.", 599, "llm", 0.75, False),
            ("in",  "NB20260205 이 번호입니다",                    550, None, None, False),
            ("out", "해당 예약이 취소 처리되었습니다. 감사합니다.", 549, "llm", 0.70, False),
        ]),
        # 윤서준 (010-1006-2006) — 파티 문의
        ("010-1006-2006", [
            ("in",  "파티는 몇시에 시작하나요?",                    45, None, None, False),
            ("out", "파티는 저녁 8시에 B동 1층 포차에서 시작됩니다. 편한 옷차림으로 와주세요!", 44, "rule", 0.95, False),
            ("in",  "드레스코드 같은 거 있나요?",                   20, None, None, False),
            ("out", "특별한 드레스코드는 없습니다. 편한 옷차림이면 충분합니다.", 19, "llm", 0.68, False),
        ]),
        # 장지은 (010-1007-2007) — 체크인 문의, 최근 대화
        ("010-1007-2007", [
            ("in",  "체크인 시간이 어떻게 되나요?",                  10, None, None, False),
            ("out", "체크인은 오후 3시부터 가능합니다. 무인 체크인이라 바로 입실하시면 됩니다.", 9, "rule", 0.95, False),
            ("in",  "비밀번호는 어디서 확인하나요?",                  5, None, None, False),
            ("out", "객실 안내 문자에 비밀번호가 포함되어 있습니다. 확인 부탁드립니다.", 4, "llm", 0.82, False),
            ("in",  "감사합니다 곧 도착합니다!",                      2, None, None, False),
            ("out", "감사합니다. 편안한 시간 보내세요!",              1, "llm", 0.85, False),
        ]),
    ]

    msg_count = 0
    for phone, thread in conversations:
        for i, (direction, text, mins_ago, source, confidence, needs_review) in enumerate(thread):
            is_inbound = direction == "in"
            msg = Message(
                message_id=f"seed_{phone}_{i}",
                direction=MessageDirection.INBOUND if is_inbound else MessageDirection.OUTBOUND,
                from_=phone if is_inbound else our,
                to=our if is_inbound else phone,
                message=text,
                status=MessageStatus.RECEIVED if is_inbound else MessageStatus.SENT,
                created_at=now - timedelta(minutes=mins_ago),
                auto_response=None,
                auto_response_confidence=confidence if not is_inbound else None,
                needs_review=needs_review if is_inbound else False,
                response_source=source,
            )
            db.add(msg)
            msg_count += 1

    logger.info(f"Created {msg_count} sample messages (8 conversations)")


def create_sample_reservations(db: Session):
    """Create sample reservations for 3/3~3/8 with realistic distribution"""

    # 날짜별 예약자 데이터 (3/3: 6명, 3/4: 8명, 3/5: 10명, 3/6: 7명, 3/7: 9명, 3/8: 8명)
    daily_guests = {
        "2026-03-03": [
            ("백승호", "남", "010-1030-2030", "A101", "더블룸", "객후", "1062"),
            ("차예은", "여", "010-1031-2031", "A102", "트윈룸", "1초", "2045"),
            ("우진혁", "남", "010-1032-2032", "A103", "패밀리룸", "2차만", "3087"),
            ("민소희", "여", "010-1033-2033", "A104", "디럭스룸", "객후,1초", "4023"),
            ("탁재윤", "남", "010-1034-2034", "B201", "더블룸", "1초,2차만", "5071"),
            ("피수아", "여", "010-1035-2035", None, None, "파티만", None),
        ],
        "2026-03-04": [
            ("김철수", "남", "010-1000-2000", "A101", "더블룸", "객후", "1034"),
            ("이영희", "여", "010-1001-2001", "A102", "트윈룸", "1초", "2058"),
            ("박민수", "남", "010-1002-2002", "A103", "패밀리룸", "객후,1초", "3072"),
            ("정수진", "여", "010-1003-2003", "A104", "디럭스룸", "2차만", "4016"),
            ("최동욱", "남", "010-1004-2004", "B201", "더블룸", "객후", "5090"),
            ("강미영", "여", "010-1005-2005", "B202", "트윈룸", "1초,2차만", "6044"),
            ("윤서준", "남", "010-1006-2006", None, None, "파티만", None),
            ("장지은", "여", "010-1007-2007", None, None, "파티만", None),
        ],
        "2026-03-05": [
            ("임태준", "남", "010-1008-2008", "A101", "더블룸", "객후", "1025"),
            ("오혜진", "여", "010-1009-2009", "A102", "트윈룸", "1초", "2067"),
            ("한상우", "남", "010-1010-2010", "A103", "패밀리룸", "객후,1초", "3041"),
            ("배수연", "여", "010-1011-2011", "A104", "디럭스룸", "2차만", "4083"),
            ("송민호", "남", "010-1012-2012", "A105", "스탠다드룸", "객후", "5019"),
            ("류하은", "여", "010-1013-2013", "B201", "더블룸", "1초", "6052"),
            ("조윤서", "여", "010-1014-2014", "B202", "트윈룸", "객후,2차만", "7036"),
            ("권태양", "남", "010-1015-2015", "B203", "패밀리룸", "1초,2차만", "8074"),
            ("신예린", "여", "010-1016-2016", None, None, "파티만", None),
            ("황준혁", "남", "010-1017-2017", None, None, "파티만", None),
        ],
        "2026-03-06": [
            ("문서현", "여", "010-1018-2018", "A101", "더블룸", "객후", "1048"),
            ("안지호", "남", "010-1019-2019", "A102", "트윈룸", "1초", "2091"),
            ("고은비", "여", "010-1020-2020", "A103", "패밀리룸", "2차만", "3065"),
            ("서태민", "남", "010-1021-2021", "A104", "디럭스룸", "객후,1초", "4027"),
            ("나윤아", "여", "010-1022-2022", "B201", "더블룸", "객후", "5083"),
            ("허성빈", "남", "010-1023-2023", None, None, "1초,2차만", None),
            ("유채원", "여", "010-1024-2024", None, None, "파티만", None),
        ],
        "2026-03-07": [
            ("정하린", "여", "010-1036-2036", "A101", "더블룸", "객후", "1053"),
            ("김도현", "남", "010-1037-2037", "A102", "트윈룸", "1초", "2078"),
            ("이수빈", "여", "010-1038-2038", "A103", "패밀리룸", "객후,1초", "3014"),
            ("박준영", "남", "010-1039-2039", "A104", "디럭스룸", "2차만", "4096"),
            ("최유나", "여", "010-1040-2040", "A105", "스탠다드룸", "객후", "5032"),
            ("강민재", "남", "010-1041-2041", "B201", "더블룸", "1초,2차만", "6081"),
            ("윤지아", "여", "010-1042-2042", "B202", "트윈룸", "객후,2차만", "7049"),
            ("장석호", "남", "010-1043-2043", None, None, "파티만", None),
            ("한소율", "여", "010-1044-2044", None, None, "파티만", None),
        ],
        "2026-03-08": [
            ("오태경", "남", "010-1045-2045", "A101", "더블룸", "객후", "1087"),
            ("배지윤", "여", "010-1046-2046", "A102", "트윈룸", "1초", "2034"),
            ("송하준", "남", "010-1047-2047", "A103", "패밀리룸", "객후,1초", "3056"),
            ("류민서", "여", "010-1048-2048", "A104", "디럭스룸", "2차만", "4072"),
            ("조영훈", "남", "010-1049-2049", "B201", "더블룸", "1초", "5018"),
            ("권세아", "여", "010-1050-2050", "B202", "트윈룸", "객후,2차만", "6063"),
            ("신동건", "남", "010-1051-2051", None, None, "1초,2차만", None),
            ("황예지", "여", "010-1052-2052", None, None, "파티만", None),
        ],
    }

    count = 0
    for date_str, guests in daily_guests.items():
        for i, (name, gender, phone, room, room_info, tags, pw) in enumerate(guests):
            has_room = room is not None
            res = Reservation(
                external_id=f"naver_{date_str}_{i}",
                customer_name=name,
                phone=phone,
                date=date_str,
                time=f"{15 + (i % 4)}:00",
                status=ReservationStatus.CONFIRMED,
                notes=f"{date_str} 예약",
                source="naver" if i % 2 == 0 else "manual",
                naver_booking_id=f"NB{date_str.replace('-','')}{i:02d}" if i % 2 == 0 else None,
                room_number=room,
                room_password=pw,
                room_info=room_info,
                gender=gender,
                age_group=random.choice(["20대", "30대"]),
                visit_count=random.randint(1, 5),
                party_participants=random.randint(1, 3),
                tags=tags,
                room_sms_sent=has_room,
                party_sms_sent=has_room,
                room_sms_sent_at=datetime.utcnow() if has_room else None,
                party_sms_sent_at=datetime.utcnow() if has_room else None,
            )
            db.add(res)
            count += 1

    logger.info(f"Created {count} sample reservations (3/3~3/8)")


def create_sample_rules(db: Session):
    """Create 5 basic rules"""
    rules = [
        {
            "name": "영업시간 안내",
            "pattern": r"(영업시간|몇시|언제|시간)",
            "response": "평일 09:00-18:00, 주말 10:00-17:00 영업합니다. 공휴일은 휴무입니다.",
            "priority": 10,
            "active": True,
        },
        {
            "name": "예약 문의",
            "pattern": r"(예약|방문|언제|가능)",
            "response": "예약은 전화(010-9999-0000) 또는 네이버 예약으로 가능합니다.",
            "priority": 9,
            "active": True,
        },
        {
            "name": "가격 안내",
            "pattern": r"(가격|비용|얼마|요금)",
            "response": "서비스 종류에 따라 가격이 다릅니다. 자세한 상담은 전화 주세요.",
            "priority": 8,
            "active": True,
        },
        {
            "name": "주차 안내",
            "pattern": r"(주차|차|자동차)",
            "response": "건물 지하 1층에 무료 주차 가능합니다.",
            "priority": 7,
            "active": True,
        },
        {
            "name": "위치 안내",
            "pattern": r"(위치|어디|주소|찾아가|길)",
            "response": "서울시 강남구 테헤란로 123 (강남역 2번 출구에서 도보 5분)",
            "priority": 6,
            "active": True,
        },
    ]

    for rule_data in rules:
        rule = Rule(**rule_data)
        db.add(rule)

    logger.info(f"Created {len(rules)} sample rules")


def create_sample_documents(db: Session):
    """Create 3 sample documents"""
    documents = [
        {
            "filename": "서비스_가격표.pdf",
            "content": "기본 서비스: 50,000원\n프리미엄 서비스: 100,000원",
            "file_path": "/uploads/서비스_가격표.pdf",
            "indexed": False,
        },
        {
            "filename": "자주_묻는_질문_FAQ.txt",
            "content": "Q: 예약 취소 가능한가요?\nA: 예약 1일 전까지 무료 취소 가능합니다.",
            "file_path": "/uploads/FAQ.txt",
            "indexed": False,
        },
        {
            "filename": "이용_안내.docx",
            "content": "방문 시 주의사항:\n1. 예약 시간 10분 전 도착\n2. 신분증 지참",
            "file_path": "/uploads/이용_안내.docx",
            "indexed": False,
        },
    ]

    for doc_data in documents:
        doc = Document(**doc_data)
        db.add(doc)

    logger.info(f"Created {len(documents)} sample documents")


def create_sample_templates(db: Session):
    """Create 4 message templates"""
    templates = [
        {
            "key": "room_guide",
            "name": "객실 안내 문자",
            "content": (
                "금일 객실은 스테이블 {{building}}동 {{roomNum}}호 - {{roomInfo}}룸입니다."
                "(비밀번호: {{password}}*)\n\n"
                "무인 체크인이라서 바로 입실하시면 됩니다.\n"
                "객실내에서(발코니포함) 음주, 흡연, 취식, 혼숙 절대 금지입니다."
                "(적발시 벌금 10만원 또는 퇴실)\n\n"
                "파티 참여 시 저녁 8시에 B동 1층 포차로 내려와 주시면 되세요."
            ),
            "variables": json.dumps(["building", "roomNum", "roomInfo", "password"]),
            "category": "room_guide",
            "active": True,
        },
        {
            "key": "party_guide",
            "name": "파티 안내 문자",
            "content": (
                "금일 파티 참여 시 아래 계좌로 파티비 입금 후 "
                "저녁 8시 스테이블 B동 1층 포차로 내려와주세요!\n\n"
                "{{priceInfo}}\n\n"
                "- 금일 파티 인원은 {{totalParticipants}}명+ 예상됨(여자{{femaleCount}}명)\n"
                "- 조별활동이 있으니 편한 옷차림으로 내려와주세요."
            ),
            "variables": json.dumps(["priceInfo", "totalParticipants", "femaleCount"]),
            "category": "party_guide",
            "active": True,
        },
        {
            "key": "reservation_confirm",
            "name": "예약 확정 안내",
            "content": (
                "안녕하세요 {{name}}님, 예약이 확정되었습니다.\n\n"
                "날짜: {{date}}\n시간: {{time}}\n\n"
                "문의사항은 010-9999-0000으로 연락 주세요."
            ),
            "variables": json.dumps(["name", "date", "time"]),
            "category": "notification",
            "active": True,
        },
        {
            "key": "gender_invite",
            "name": "성비 초대 문자",
            "content": (
                "오늘 파티에 여성분들의 참여를 기다리고 있어요!\n\n"
                "현재 남녀비율: 남 {{maleCount}}명 / 여 {{femaleCount}}명\n"
                "총 {{totalParticipants}}명 참여 예정\n\n"
                "저녁 8시 스테이블 B동 1층 포차에서 만나요!"
            ),
            "variables": json.dumps(["maleCount", "femaleCount", "totalParticipants"]),
            "category": "party_guide",
            "active": True,
        },
        {
            "key": "tag_객후",
            "name": "객후 태그 메시지",
            "content": (
                "{{name}}님 안녕하세요!\n\n"
                "객실 이용 후 파티 참여 안내드립니다.\n\n"
                "📍 파티 장소: 스테이블 B동 1층 포차\n"
                "⏰ 파티 시작: 저녁 8시\n"
                "💰 파티 참여비: {{priceInfo}}\n\n"
                "객실 체크인 후 편하게 파티에 참여하실 수 있습니다."
            ),
            "variables": json.dumps(["name", "priceInfo"]),
            "category": "tag_based",
            "active": True,
        },
        {
            "key": "tag_1초",
            "name": "1초 태그 메시지",
            "content": (
                "{{name}}님 안녕하세요!\n\n"
                "1차 파티 안내드립니다.\n\n"
                "⏰ 시작 시간: 저녁 8시\n"
                "💰 참여비: {{priceInfo}}\n"
                "👥 예상 인원: {{totalParticipants}}명\n\n"
                "많은 참여 부탁드립니다!"
            ),
            "variables": json.dumps(["name", "priceInfo", "totalParticipants"]),
            "category": "tag_based",
            "active": True,
        },
        {
            "key": "tag_2차만",
            "name": "2차만 태그 메시지",
            "content": (
                "{{name}}님 안녕하세요!\n\n"
                "2차 파티만 참여 안내드립니다.\n\n"
                "⏰ 2차 시작: 밤 10시\n"
                "💰 참여비: {{priceInfo}}\n\n"
                "2차부터 편하게 오셔도 됩니다!"
            ),
            "variables": json.dumps(["name", "priceInfo"]),
            "category": "tag_based",
            "active": True,
        },
        {
            "key": "tag_객후1초",
            "name": "객후+1초 태그 메시지",
            "content": (
                "{{name}}님 안녕하세요!\n\n"
                "객실 이용 후 1차 파티 참여 안내드립니다.\n\n"
                "🏨 객실: {{building}}동 {{roomNum}}호\n"
                "🔐 비밀번호: {{password}}\n"
                "⏰ 파티 시작: {{partyTime}}\n"
                "💰 파티 참여비: {{priceInfo}}\n\n"
                "체크인 후 파티 참여 부탁드립니다!"
            ),
            "variables": json.dumps(["name", "building", "roomNum", "password", "partyTime", "priceInfo"]),
            "category": "tag_based",
            "active": True,
        },
        {
            "key": "tag_1초2차만",
            "name": "1초+2차만 태그 메시지",
            "content": (
                "{{name}}님 안녕하세요!\n\n"
                "1차와 2차 파티 모두 참여 안내드립니다.\n\n"
                "⏰ 1차: {{partyTime}}\n"
                "⏰ 2차: {{secondPartyTime}}\n"
                "💰 참여비: {{priceInfo}}\n\n"
                "많은 참여 부탁드립니다!"
            ),
            "variables": json.dumps(["name", "partyTime", "secondPartyTime", "priceInfo"]),
            "category": "tag_based",
            "active": True,
        },
    ]

    for tmpl_data in templates:
        tmpl = MessageTemplate(**tmpl_data)
        db.add(tmpl)

    logger.info(f"Created {len(templates)} message templates")


def create_sample_campaign_logs(db: Session):
    """Create 5 campaign log entries"""
    now = datetime.utcnow()

    campaigns = [
        {
            "campaign_type": "room_guide",
            "target_tag": None,
            "target_count": 8,
            "sent_count": 8,
            "failed_count": 0,
            "sent_at": now - timedelta(days=2, hours=3),
            "completed_at": now - timedelta(days=2, hours=3),
        },
        {
            "campaign_type": "room_guide",
            "target_tag": None,
            "target_count": 6,
            "sent_count": 5,
            "failed_count": 1,
            "sent_at": now - timedelta(days=1, hours=5),
            "completed_at": now - timedelta(days=1, hours=5),
            "error_message": "1건 전송 실패: 번호 오류",
        },
        {
            "campaign_type": "party_guide",
            "target_tag": None,
            "target_count": 12,
            "sent_count": 12,
            "failed_count": 0,
            "sent_at": now - timedelta(days=1, hours=2),
            "completed_at": now - timedelta(days=1, hours=2),
        },
        {
            "campaign_type": "tag_based",
            "target_tag": "객후",
            "target_count": 5,
            "sent_count": 5,
            "failed_count": 0,
            "sent_at": now - timedelta(hours=6),
            "completed_at": now - timedelta(hours=6),
        },
        {
            "campaign_type": "tag_based",
            "target_tag": "1초,2차만",
            "target_count": 3,
            "sent_count": 2,
            "failed_count": 1,
            "sent_at": now - timedelta(hours=2),
            "completed_at": now - timedelta(hours=2),
            "error_message": "1건 전송 실패: 수신거부",
        },
    ]

    for camp_data in campaigns:
        camp = CampaignLog(**camp_data)
        db.add(camp)

    logger.info(f"Created {len(campaigns)} campaign logs")


def create_sample_gender_stats(db: Session):
    """Create gender statistics for 3/3~3/8 matching reservation data"""

    # 예약 데이터 기반 실제 성비 (날짜, 남, 여)
    stats_data = [
        ("2026-03-03", 3, 3),   # 백승호,우진혁,탁재윤 / 차예은,민소희,피수아
        ("2026-03-04", 4, 4),   # 김철수,박민수,최동욱,윤서준 / 이영희,정수진,강미영,장지은
        ("2026-03-05", 5, 5),   # 임태준,한상우,송민호,권태양,황준혁 / 오혜진,배수연,류하은,조윤서,신예린
        ("2026-03-06", 3, 4),   # 안지호,서태민,허성빈 / 문서현,고은비,나윤아,유채원
        ("2026-03-07", 4, 5),   # 김도현,박준영,강민재,장석호 / 정하린,이수빈,최유나,윤지아,한소율
        ("2026-03-08", 4, 4),   # 오태경,송하준,조영훈,신동건 / 배지윤,류민서,권세아,황예지
    ]

    for date_str, male, female in stats_data:
        stat = GenderStat(
            date=date_str,
            male_count=male,
            female_count=female,
            total_participants=male + female,
        )
        db.add(stat)

    logger.info(f"Created {len(stats_data)} gender stat records (3/3~3/8)")


def create_sample_rooms(db: Session):
    """Create initial room configurations"""
    rooms_data = [
        {"room_number": "A101", "room_type": "더블룸", "sort_order": 1},
        {"room_number": "A102", "room_type": "트윈룸", "sort_order": 2},
        {"room_number": "A103", "room_type": "패밀리룸", "sort_order": 3},
        {"room_number": "A104", "room_type": "디럭스룸", "sort_order": 4},
        {"room_number": "A105", "room_type": "스탠다드룸", "sort_order": 5},
        {"room_number": "B201", "room_type": "더블룸", "sort_order": 6},
        {"room_number": "B202", "room_type": "트윈룸", "sort_order": 7},
        {"room_number": "B203", "room_type": "패밀리룸", "sort_order": 8},
        {"room_number": "B204", "room_type": "디럭스룸", "sort_order": 9},
        {"room_number": "B205", "room_type": "스탠다드룸", "sort_order": 10},
    ]

    for room_data in rooms_data:
        room = Room(**room_data, is_active=True)
        db.add(room)

    logger.info(f"Created {len(rooms_data)} rooms")


def create_seed_users(db: Session):
    """Create initial user accounts (upsert — skip if already exists)"""
    seed_users = [
        ("admin", "admin1234", "관리자", UserRole.SUPERADMIN),
        ("staff1", "staff1234", "직원1", UserRole.STAFF),
    ]
    created = 0
    for username, password, name, role in seed_users:
        existing = db.query(User).filter(User.username == username).first()
        if not existing:
            user = User(
                username=username,
                hashed_password=hash_password(password),
                name=name,
                role=role,
                is_active=True,
            )
            db.add(user)
            created += 1
    if created:
        db.flush()
    logger.info(f"Seed users: {created} created, {len(seed_users) - created} already existed")


def seed_all():
    """Run all seed functions"""
    logger.info("Initializing database...")
    init_db()

    logger.info("Seeding data...")
    db = SessionLocal()
    try:
        # Clear existing data
        db.query(Message).delete()
        db.query(Reservation).delete()
        db.query(Rule).delete()
        db.query(Document).delete()
        db.query(MessageTemplate).delete()
        db.query(CampaignLog).delete()
        db.query(GenderStat).delete()
        db.query(Room).delete()
        db.commit()

        # Create seed users (upsert — don't delete existing users)
        create_seed_users(db)

        # Create sample data
        create_sample_rooms(db)  # Create rooms first
        create_sample_messages(db)
        create_sample_reservations(db)
        create_sample_rules(db)
        create_sample_documents(db)
        create_sample_templates(db)
        create_sample_campaign_logs(db)
        create_sample_gender_stats(db)

        db.commit()
        logger.info("✅ Seeding completed successfully!")
    except Exception as e:
        logger.error(f"❌ Seeding failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_all()
