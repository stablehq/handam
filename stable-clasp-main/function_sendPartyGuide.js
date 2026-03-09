function sendPartyGuide() {
  // 주말 가격
  var apiUrl = "http://15.164.246.59:3000/sendMass";

  var date = new Date();

  // 날짜를 YYYY-MM-DD 포맷으로 변경한다
  function formatDate(date) {
    var d = new Date(date),
      month = '' + (d.getMonth() + 1),
      day = '' + d.getDate(),
      year = d.getFullYear();

    if (month.length < 2)
      month = '0' + month;
    if (day.length < 2)
      day = '0' + day;

    return [year, month, day].join('-');
  }

  try {
    var sheetName = getdateSheetName(date);
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
    if (!sheet) {
      Logger.log(sheetName + "이라는 이름의 시트를 찾을 수 없습니다.");
    }
    Logger.log(sheet.getSheetName())

    var columnIndex = getDateChannelNameColumn(sheet, date);
    var startRow = 3;
    var endRow = 68; // 파티만 제외하고

    var roomColumn = 2;
    var uniquePhoneNumbers = new Set();
    var totalParticipants = 0;

    // 3행부터 67까지 연락처를 모은다.
    for (var row = startRow; row <= endRow; row++) {
      cellPhone = sheet.getRange(row, columnIndex + 1).getValue();
      participate = sheet.getRange(row, columnIndex + 3).getValue();
      memo = sheet.getRange(row, columnIndex + 5).getValue().toString();
      roomInfo = sheet.getRange(row, roomColumn).getValue();

      var matches = participate.trim().match(/(\d+)/);
      if (matches) {
        totalParticipants += parseInt(matches[1]);  // 추출한 숫자를 더하기
      }

      if (typeof memo === 'string' && (memo.includes('파티문자O') || roomInfo.includes('파티만'))) {
        continue;
      }

      // cellPhone 값이 공백이 아니고 숫자만 포함된 경우에만 추가
      if (cellPhone && /^\d+$/.test(cellPhone)) {
        uniquePhoneNumbers.add(cellPhone);
      }
    }

    // Set을 배열로 변환
    var uniquePhoneNumbersArray = Array.from(uniquePhoneNumbers);
    Logger.log(uniquePhoneNumbersArray);
    Logger.log("Unique phone numbers count: " + uniquePhoneNumbersArray.length);
  } catch (e) {
    Logger.log('Error: ' + e.toString());
  }

  totalParticipants = Math.ceil(totalParticipants / 10) * 10;
  Logger.log("Ceil(TotalParticipants) : " + totalParticipants)

  partyPrice = `
  [1차 파티]
  - 오후8시~10시30분 
  - 흑돼지바베큐 무제한(90분), 설탕토마토, 고구마샐러드, 물만두, 과일안주, 팝콘, 토닉워터 등
  - 주류 1병(1인당) 
  - 남자 3만 원, 여자 2만 원

  [2차 파티]
  - 오후10시30분~12시30분
  - 치킨, 시원한 콩나물국, 과자, 샐러드
  - 주류 1병(2인당)
- 남자 2.5만 원, 여자 2만 원

- 1차+2차 신청 시 남자 5.5만원 / 여자 4만원 
(금일 인원이 많아 1차 이후 현장 2차 신청이 안될 수 있으니 꼭 동시 신청해주세요!) 
`

  var partyMessage = `
  스테이블 게하입니다 :)

  금일 파티 참여 시 아래 계좌로 파티비 입금 후

  성함/성별/인원/참여파티
  회신 주시면 예약 확정 돼요.
  (예:김태희/여자/2명/1차2차)
 
  농협 351 1289 2410 23
  주식회사 스테이블

  *연박하시는 분 중에서 이미 신청/입금완료하셨다면, 안보내셔도 됩니다.

  ${partyPrice}

  - 파티장 입장은 19시 50분 부터 가능합니다.
  (입장시 신분증/여권/운전면허증 꼭 지참해주세요)

  - 이번 달 생일, 승진, 취업, 이별 등 축하/위로해 드릴 일 있으면 간단히 문자 회신 부탁요. 한 팀 선정해서 2차 파티 때 축하해 드려요.

  - 음식이 소진될 수 있어 정시 참여 부탁 드려요.

  - 파티 신청은 음식 준비로 4시까지만 되고, 정원 도달 시 마감될 수 있어요.

  - 금일 파티 인원은 ${totalParticipants}명+ 예상됨으로 빠르게 신청 부탁드려요.(마감 시 신청 불가)

  - 파티를 하다보면 더울 수 있으니, 투숙객들은 외투를 객실에 두고 오시는걸 추천드려요.

  - 파티 참여는 초상권 동의로 간주돼요.

  - 파티비는 환불 불가합니다!

  [체크인 안내]
  - 체크인: 오후 5시에 비밀번호 문자 받으면 연락 없이 바로 입실하시면 돼요.(얼리 체크인 불가)
  - 체크아웃: 낮 12시

  [주의 사항]
  1. 전 객실 금연이며, 흡연은 1층 야외 지정구역 이용해 주세요.(적발 시 벌금 10만 원)

  2. 객실 내 취사 / 배달음식 절대 금지입니다. 

  3. 퇴실 시 이용하신 수건과 베개 피는 엘베 앞 바구니에 담아 주시고, 문은 열어 놓아 주세요.

  4. 물은 1층 정수기 이용해 주시고, 생수, 칫솔, 음료, 면도기 등 B동 자판기에서 유료 구매 가능해요.

  5. 타인의 방 출입이 엄격히 제한됩니다. 적발 시 즉각 퇴실 조치 되오니 꼭 지켜주세요! (CCTV 촬영 중)

  6. 실내에 구토하거나 침구류 오염 시 청소비/세탁비 10만 원 청구 되오니 주량까지만 즐겨주세요.

  7. 수건, 휴지 부족할 경우 A, B동 1층 정수기 옆에서 가져 가주시면 돼요.

  8. 체크인 전에 일행과 함께 네이버 플레이스에서 "스테이블 게스트하우스" 저장하기 (초록색 별표) 해주시면 파티 입장시 생수 서비스 드려요.

  9. 그 외 궁금한 점(주차 등)은 아래 자주묻는질문 링크를 참고해 주세요.
  http://pf.kakao.com/_xggCxcG
  
  10. 여성 뚜벅이 분들을 위한 이벤트가 있어요. 인스타 디엠으로 “성함/연락처/인원수/내일목적지/게하출발시간” 보내주시면 카풀 가능한분 매칭해서 회신드릴께요!

  그럼 조심히 오세요 :)
  `

  if (!uniquePhoneNumbersArray) {
    Logger.log("Error: uniquePhoneNumbersArray is undefined!");
    return; // 함수를 종료
  }


  // POST 데이터 설정
  var payload = {
    "msg_type": "LMS",
    "cnt": uniquePhoneNumbersArray.length.toString(),
    "testmode_yn": "N"
  };

  for (var i = 0; i < uniquePhoneNumbersArray.length; i++) {
    payload["rec_" + (i + 1)] = uniquePhoneNumbersArray[i];
    payload["msg_" + (i + 1)] = partyMessage;
  }

  // API 호출 옵션 설정
  var options = {
    "method": "post",
    "payload": JSON.stringify(payload),
    "contentType": "application/json",
    "muteHttpExceptions": true
  };

  var response = UrlFetchApp.fetch(apiUrl, options);
  var data = JSON.parse(response.getContentText());

  if (data.result_code == 1) {
    // 성공적으로 문자가 발송된 경우
    Logger.log('Message ID: ' + data.msg_id);
    Logger.log('Message Type: ' + data.msg_type);
    Logger.log('Success Count: ' + data.success_cnt);
    Logger.log('Error Count: ' + data.error_cnt);

    // 성공하면 해당 전화번호에 해당하는 입금 예정 셀에 파티안내O 라고 표기해준다.
    for (var row = startRow; row <= endRow; row++) {
      cellPhone = sheet.getRange(row, columnIndex + 1).getValue();
      memo = sheet.getRange(row, columnIndex + 5).getValue().toString();

      // 실제로 발송된 전화번호인지 확인
      if (uniquePhoneNumbersArray.includes(cellPhone)) {
        if (typeof memo === 'string' && memo.includes('파티문자X')) {
          // 파티문자X를 파티문자O로 변경
          memo = memo.replace('파티문자X', '파티문자O');
        } else if (typeof memo === 'string' && !memo.includes('파티문자O')) {
          // 파티문자O를 셀 내용 맨 앞에 추가
          memo = '파티문자O ' + memo;
        } else if (typeof memo === 'string' && !memo.includes('파티문자O')) {
          continue;
        }
        // 변경된 메모를 시트에 업데이트
        sheet.getRange(row, columnIndex + 5).setValue(memo);
      }
    }
  } else {
    // 문자 발송 실패
    Logger.log('Error: ' + data.message);
  }
}