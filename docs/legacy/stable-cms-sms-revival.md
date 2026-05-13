# stable-cms-sms 레거시 SMS 서버 부활 가이드

신규 `sms-system`으로 마이그레이션하면서 정지시킨 레거시 Node.js SMS 발송 서버를 백업으로 되살리는 절차.

## 정지 시점 정보

- **정지 일자**: 2026-05-06
- **정지 사유**: 신규 `sms-system`(FastAPI)으로 SMS 발송 기능 완전 대체
- **상태**: PM2 프로세스만 stop, 코드/설정/dump 모두 보존

## 서버 위치

- **AWS Lightsail 인스턴스**: `ip-172-26-15-240` (퍼블릭 IP: `15.164.246.59`)
- **SSH 사용자**: `ubuntu`
- **프로젝트 경로**: `/home/ubuntu/stable-cms-sms/`
- **PM2 dump**: `/home/ubuntu/.pm2/dump.pm2`
- **PM2 로그**: `/home/ubuntu/.pm2/logs/app-out.log`, `app-error.log`

## 정지된 프로세스

| PM2 id | 이름 | 포트 | 파일 | 용도 |
|--------|------|------|------|------|
| 1 | `app` | 3000 | `app.js` | **운영용** SMS/MMS 발송 (Aligo) |
| 2 | `app-test` | 4000 | `app-test.js` | 테스트용 (실제 트래픽 없었음) |

### `app.js`가 노출하는 엔드포인트

- `POST /sendMass` — 일반 SMS/LMS 일괄 발송 (aligoapi 라이브러리 사용)
- `POST /sms_list` — `/sendMass`와 동일 (별칭)
- `POST /sendMass/image` — MMS 일괄 발송. `/home/ubuntu/static/party0{1,2,3}.jpg` 3장 첨부

### Aligo 인증 정보

`app.js` 코드에 평문으로 박혀있음 (`AuthData` 변수):

- `key`: `9srzxlivu4nlr444btvzz7jghwsoxinh`
- `user_id`: `k7d7s7`

> ⚠️ 폐기 시 Aligo 관리자 페이지에서 이 API 키를 회수/재발급 권장. 신규 `sms-system`도 같은 계정을 사용 중이면 키 교체에 영향 있을 수 있으니 확인 필수.

## 호출자 (Google Apps Script)

레거시 Apps Script 코드는 `docs/legacy/stable-clasp-main/`에 보관. 아래 위치에서 `15.164.246.59:3000`을 호출함:

| 파일 | 라인 | 엔드포인트 | 용도 |
|------|------|-----------|------|
| `00_main.js` | 59, 252 | `/sendMass` | 메인 발송 트리거 |
| `01_sns.js` | 62 | `/sendMass` | `sendSmsAndMark` 공통 함수 기본값 |
| `01_sns.js` | 213 | `/sendMass/image` | 파티3 MMS (이미지 3장) |
| `function_sendPartyGuide.js` | 3 | `/sendMass` | 파티 안내 SMS |
| `function_sendStarRoomGuide.js` | 2 | `/sendMass` | 별실 안내 SMS |

## 부활 절차

### 빠른 부활 (1분)

신규 시스템에 문제가 생겨 즉시 SMS 발송을 복구해야 할 때:

```bash
# 1. SSH 접속
ssh ubuntu@15.164.246.59

# 2. 프로세스 시작
pm2 start app          # 운영용 (포트 3000)
pm2 start app-test     # 필요 시 (포트 4000)

# 3. 상태 확인 (online 이어야 함)
pm2 list

# 4. 포트 listen 확인 (3000, 4000 보여야 함)
sudo ss -tlnp | grep -E ':3000|:4000'

# 5. 외부 호출 확인 — Google Apps Script가 호출하면 로그가 흐름
pm2 logs app --lines 30
```

### 검증 (호출이 실제로 들어오는지)

```bash
# 로컬에서 헬스 체크 (404 나오면 정상 — / 라우트는 없음)
curl -I http://localhost:3000/

# 실제 호출자 확인 (Google Apps Script IP는 34.116.x.x 대역)
pm2 logs app --lines 50 --nostream | grep "POST /sendMass"
```

### 부활 후 신규 시스템 멈춰야 할 때

레거시·신규 동시 발송 = 중복 SMS 발송 위험. 신규 `sms-system`의 `TemplateSchedule`을 비활성화하거나 백엔드를 멈춰야 함.

```bash
# (예시) 신규 시스템이 같은 인스턴스에 있다면
sudo systemctl stop sms-system    # 또는 해당 서비스명
```

## 영구 삭제 절차 (1~2주 안정 운영 확인 후)

```bash
# 1. PM2에서 영구 제거
pm2 delete app app-test
pm2 save

# 2. 폴더 백업 (Aligo 키가 들어있으니 안전한 곳에 보관)
tar -czf ~/stable-cms-sms-backup-$(date +%Y%m%d).tar.gz \
  --exclude=node_modules -C /home/ubuntu stable-cms-sms

# 3. 백업을 다른 위치(S3/로컬)로 옮긴 뒤
rm -rf /home/ubuntu/stable-cms-sms

# 4. (선택) 라이트세일 인스턴스가 이 용도뿐이면 스냅샷 후 인스턴스 삭제
#    → AWS Lightsail 콘솔에서 처리. 월 비용 절감.
```

## 주의 사항

### PM2 startup 미등록 = 재부팅 시 백업이 사라짐

현재 PM2가 systemd에 startup 등록되어 있지 않음 (`systemctl list-unit-files | grep pm2` 결과 없음). 즉:

- **인스턴스 재부팅 시**: PM2 자체가 안 뜨고, `app`/`app-test` 둘 다 사라짐
- **백업 의미가 없어짐**: 부활하려면 재부팅 후 `pm2 resurrect` 수동 실행 필요

진짜 백업으로 유지하려면 startup 등록 권장:

```bash
pm2 startup systemd -u ubuntu --hp /home/ubuntu
# ↑ 출력으로 sudo 명령 한 줄 나옴 → 그대로 복붙해서 실행
pm2 save
```

이렇게 해두면 재부팅돼도 PM2는 살아나고, dump 상태(=stopped) 복원되며, 필요할 때 `pm2 start app`만 하면 됨.

### Apps Script 트리거 정리도 잊지 말 것

레거시를 영구 폐기할 때, Google Apps Script 쪽 트리거도 함께 정리해야 매번 실패 알림이 안 옴:

1. https://script.google.com/home → 해당 프로젝트
2. 좌측 **트리거** 탭 → `15.164.246.59:3000`을 호출하는 함수의 트리거 삭제
3. 신규 `sms-system`의 `TemplateSchedule` 목록과 1:1 대조해서 빠진 발송 흐름 없는지 확인
