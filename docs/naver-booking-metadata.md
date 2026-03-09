# 네이버 스마트플레이스 예약 API 메타데이터

## API Endpoint
```
GET https://new.smartplace.naver.com/api/booking/v3.0/businesses/{businessId}/bookings
```

## 기본 정보
| 필드 | 타입 | 예시 | 설명 |
|------|------|------|------|
| `bookingId` | int | 1157557256 | 예약 고유 ID |
| `businessId` | int | 3354 | 사업장 ID |
| `businessName` | string | "한담누리 게스트하우스" | 업소명 |
| `name` | string | "주상훈" | 예약자 이름 |
| `phone` | string | "01051176243" | 전화번호 |
| `email` | string | "wntkdgns01@naver.com" | 이메일 |
| `userId` | int | 13771763 | 네이버 사용자 ID (성별/나이 조회용) |
| `isBlacklist` | bool | false | 블랙리스트 여부 |
| `isNonmember` | bool | false | 비회원 여부 |

## 예약 상세
| 필드 | 타입 | 예시 | 설명 |
|------|------|------|------|
| `bizItemId` | int | 4341604 | 방 타입(상품) ID |
| `bizItemName` | string | "[특가] 트윈룸 (2인 기준, 파티 필참)" | 상품명 |
| `bizItemType` | string | "STANDARD" | 상품 타입 |
| `bookingCount` | int | 1 | 예약 수량 |
| `startDate` | string | "2026-03-09" | 체크인 날짜 |
| `endDate` | string | "2026-03-11" | 체크아웃 날짜 |
| `bookingStatusCode` | string | "RC03" | 예약 상태 (RC03=확정, RC04=취소) |
| `adminBookingStatusCode` | string | "AB00" | 관리자 예약 상태 |
| `bookingType` | string | "STANDARD" | 예약 유형 |
| `bookingOrigin` | string | "NAVERBOOKING" | 예약 출처 |

## 상태 코드
| 코드 | 설명 |
|------|------|
| `RC03` | 확정 |
| `RC04` | 취소 |

## 일시 정보
| 필드 | 타입 | 예시 | 설명 |
|------|------|------|------|
| `regDateTime` | string | "2026-02-13T19:01:41+09:00" | 예약 등록 시각 |
| `confirmedDateTime` | string | "2026-02-13T19:02:08+09:00" | 예약 확정 시각 |

## 결제 정보
| 필드 | 타입 | 예시 | 설명 |
|------|------|------|------|
| `price` | int | 95000 | 상품 가격 |
| `couponPrice` | int | 0 | 쿠폰 할인 |
| `totalPrice` | int | 95000 | 총 결제 금액 |
| `refundPrice` | int | 0 | 환불 금액 |
| `isNPayUsed` | bool | true | 네이버페이 사용 여부 |
| `isPostPayment` | bool | false | 후불결제 여부 |

### 결제 상세 (`payments[]`)
| 필드 | 타입 | 예시 | 설명 |
|------|------|------|------|
| `payments[0].amount` | int | 95000 | 결제 금액 |
| `payments[0].method` | string | "NAVER_PAY_MONEY" | 결제 수단 |
| `payments[0].status` | string | "PAID" | 결제 상태 |
| `payments[0].provider` | string | "NAVER_PAY" | 결제 제공자 |

### 일별 가격 (`snapshotJson.bizItemDailyPriceJson`)
```json
[{"2026-03-09": 50000}, {"2026-03-10": 50000}]
```

### 할인 (`extraFeeJson`)
| 필드 | 타입 | 예시 | 설명 |
|------|------|------|------|
| `extraFeeJson.discountPrice` | int | 5000 | 할인 금액 |
| `extraFeeJson.commission` | int | 0 | 수수료 |

## 사용자 입력 (커스텀 폼)
```json
"customFormInputJson": [
  {
    "type": "TEXTAREA",
    "title": "성별과 인원수 남겨주세요 (여자/2명)",
    "value": "남자2",
    "required": "n",
    "perItem": "y"
  }
]
```
- `title`: 질문
- `value`: 사용자가 직접 입력한 값 (성별/인원 등)

## 방문자 정보 (예약자와 다를 때)
| 필드 | 타입 | 설명 |
|------|------|------|
| `hasVisitor` | bool | 방문자 정보 존재 여부 |
| `visitorName` | string | 실제 방문자 이름 |
| `visitorPhone` | string | 실제 방문자 전화번호 |

## 이용 이력
| 필드 | 타입 | 예시 | 설명 |
|------|------|------|------|
| `completedCount` | int | 0 | 이용 완료 횟수 |
| `cancelledCount` | int | 0 | 취소 횟수 |
| `noShowCount` | int | 0 | 노쇼 횟수 |
| `isCompleted` | bool | false | 이용 완료 여부 |

## 예약 옵션 (`bookingOptionJson`)
추가 옵션이 있는 경우 배열로 제공
```json
"bookingOptionJson": [
  { "bookingCount": 2, ... }
]
```

## 스냅샷 (`snapshotJson`)
예약 시점의 전체 데이터 스냅샷. 주요 추가 필드:
- `businessAddressJson`: 업소 주소/좌표
- `bookingPrecautionJson`: 예약 주의사항
- `bookingGuide`: 예약 안내 메시지
- `bizItemThumbImage`: 상품 썸네일 이미지 URL
- `businessThumbImage`: 업소 썸네일 이미지 URL

## 사용자 정보 API (별도 호출)
```
GET https://new.smartplace.naver.com/api/booking/v3.0/businesses/{businessId}/users/{userId}
```
| 필드 | 타입 | 예시 | 설명 |
|------|------|------|------|
| `ageGroup` | string | "20대" | 나이대 |
| `sex` | string | "MALE" / "FEMALE" | 성별 |
| `completedCount` | int | 0 | 이전 방문 횟수 |

## 방 타입 매핑 (bizItemId -> 상품명)
| bizItemId | 상품명 |
|-----------|--------|
| 7358349 | 파티만 |
| 4341604 | 트윈룸 |
| 2579095 | 남성 4인실 |
| 5053141 | 여성 4인실 |
| 10913 | 남성 8인캡슐룸 |
| 4206780 | 남성 2인캡슐룸 |
| 4133363 | 여성 2인캡슐룸 |
| 7093674 | 별관 더블룸 |
| 6960578 | 별관 남성 더블룸 |
| 4368589 | 3인실 |
| 5314854 | 여성 4인캡슐룸 |
| 2792572 | 여성 4인캡슐룸 |
| 3441558 | 여성 파티만 |
| 5501758 | 여성용 트윈룸 |
