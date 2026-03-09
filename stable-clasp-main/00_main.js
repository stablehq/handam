function partyGuideSMS() {
    const startRow = 3;
    const endRow = 68; // 별관 디럭스 (루시드엠)
    partyGuideInRange(startRow, endRow)
}

function roomGuideSMS() {
    const startRow = 3;
    const endRow = 46; // A103/105 (스위트)
    roomGuideInRange(startRow, endRow)
}

function sendStarRoomGuide() {
    const startRow = 49; // 별관 더블룸 (형제)
    const endRow = 68;   // 별관 디럭스 (루시드엠)
    sendStarRoomGuideInRange(startRow, endRow);
}

function fetchNaverSmartPlace(date) {
  const rowConfig = {
    startRow: 3,
    endRow: 68, // 별관 디럭스 (루시드엠)     
    excludeRows: [46], // 제이슨방
    freeStartRow: 100 // 미배정(1)
  };

  fetchDataAndFillSheetWithDate(date, rowConfig)
}

function processToday() {
  var today = new Date();
  fetchNaverSmartPlace(today)
}

function processTomorrow() {
  var today = new Date();
  var tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);

  fetchNaverSmartPlace(tomorrow)
}

function getMergedCellValue(sheet, row, col) {
  var cellValue = sheet.getRange(row, col).getValue();

  while (!cellValue && row > 1) { // 첫 번째 행에 도달할 때까지 계속
    row--;
    cellValue = sheet.getRange(row, col).getValue();
  }

  return cellValue;
}

function isDataMatched(dataList, name, phone, roomNum) {
  return dataList.some(item => item.cellName === name && item.cellPhone === phone && item.roomNumber === roomNum);
}

function roomGuideInRange(startRow, endRow) {
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
    var collectedData = [];
    if (!sheet) {
      Logger.log(sheetName + "이라는 이름의 시트를 찾을 수 없습니다.");
    }
    Logger.log(sheet.getSheetName())

    var columnIndex = getDateChannelNameColumn(sheet, date);

    var roomColumn = 2;
    var uniquePhoneNumbers = new Set();

    // 룸 번호에 알맞는 메시지
    for (var row = startRow; row <= endRow; row++) {
      memo = sheet.getRange(row, columnIndex + 5).getValue().toString();
      cellPhone = sheet.getRange(row, columnIndex + 1).getValue();
      cellName = sheet.getRange(row, columnIndex).getValue().split('(')[0].trim();

      if (typeof memo === 'string' && memo.includes('객실문자O') || !(cellPhone && /^\d+$/.test(cellPhone))) {
        continue;
      }

      var matchResult = getMergedCellValue(sheet, row, roomColumn).trim().match(/^([A-Za-z]{1}\d+).+\(([^)]+)\)/);
      var roomNumber = matchResult ? matchResult[1] : null;
      var roomInfo = matchResult ? matchResult[2] : null;

      var roomPasscode;
      if (roomNumber) {
        var letter = roomNumber.charAt(0);
        var number = parseInt(roomNumber.slice(1));
        if (letter === 'A') {
          roomPasscode = number * 4;
        } else if (letter === 'B') {
          roomPasscode = number * 5;
        }

        // 0-9 사이의 랜덤한 한자리 숫자를 생성합니다.
        var randomDigit = Math.floor(Math.random() * 10);

        // 랜덤한 한자리 숫자와 0을 roomPasscode 앞에 추가합니다.
        roomPasscode = randomDigit + "0" + roomPasscode;
      }

      Logger.log(roomNumber + " : " + roomPasscode)

      var newData = {
        roomNumber: roomNumber,
        cellName: cellName,
        cellPhone: cellPhone,
        roomPasscode: roomPasscode,
        roomInfo: roomInfo
      };

      // 이전 데이터 중 roomNumber, cellName, cellPhone이 겹치는 데이터가 있는지 확인
      var isDuplicate = collectedData.some(data =>
        data.roomNumber === newData.roomNumber &&
        data.cellName === newData.cellName &&
        data.cellPhone === newData.cellPhone
      );

      // 겹치는 데이터가 없으면 추가
      if (!isDuplicate) {
        collectedData.push(newData);
      }
    }

    // 결과를 로깅
    for (var i = 0; i < collectedData.length; i++) {
      var data = collectedData[i];
      Logger.log(data.roomNumber + " :: " + data.cellName + " :: " + data.cellPhone + " :: " + data.roomPasscode + " :: " + data.roomInfo);
    }
  } catch (e) {
    Logger.log('Error: ' + e.toString());
  }

  if (!collectedData) {
    Logger.log("Error: collectedData is undefined!");
    return; // 함수를 종료
  }

  // POST 데이터 설정
  var payload = {
    "msg_type": "LMS",
    "cnt": collectedData.length.toString(),
    "testmode_yn": "N"
  };

  for (var i = 0; i < collectedData.length; i++) {
    var data = collectedData[i];
    if (!data.roomNumber) {
      // roomNumber가 없는 데이터에 대한 처리 (예: 오류 메시지 출력, 반복문 건너뛰기 등)
      console.log(`Invalid data at index ${i}: ${JSON.stringify(data)}`);
      continue;  // 다음 반복으로 넘어가기
    }

    var buildingNumber = data.roomNumber.charAt(0);
    var roomNumber = data.roomNumber.slice(1);

    var roomMessage = `
    금일 객실은 스테이블 ${buildingNumber}동 ${roomNumber}호 - ${data.roomInfo}룸입니다.(비밀번호: ${data.roomPasscode}*)

무인 체크인이라서 바로 입실하시면 됩니다.
객실내에서(발코니포함) 음주, 흡연, 취식, 혼숙 절대 금지입니다.(적발시 벌금 10만원 또는 퇴실)

파티 참여 시 저녁 8시에 B동 1층 포차로 내려와 주시면 되세요.

차량번호 회신 반드시 해주시고, 주차는 아래 자주묻는질문 링크를 참고하여 타차량 통행 가능하도록 해주세요.
자주묻는질문: https://bit.ly/3Ej6P9A
  `
    Logger.log(data.cellPhone)

    payload["rec_" + (i + 1)] = data.cellPhone;
    payload["msg_" + (i + 1)] = roomMessage;

    Logger.log(data.cellName + " ::: " + roomMessage)
  }

  Logger.log(JSON.stringify(payload));

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
      memo = sheet.getRange(row, columnIndex + 5).getValue().toString();
      cellPhone = sheet.getRange(row, columnIndex + 1).getValue();
      cellName = sheet.getRange(row, columnIndex).getValue().split('(')[0].trim();
      var matchResult = getMergedCellValue(sheet, row, roomColumn).trim().match(/^([A-Za-z]{1}\d+).+\(([^)]+)\)/);
      var roomNumber = matchResult ? matchResult[1] : null;
      var roomInfo = matchResult ? matchResult[2] : null;

      if (typeof memo === 'string' && memo.includes('객실문자O') || !(cellPhone && /^\d+$/.test(cellPhone))) {
        continue;
      }

      // 실제로 발송된 전화번호인지 확인
      if (isDataMatched(collectedData, cellName, cellPhone, roomNumber)) {
        if (typeof memo === 'string' && memo.includes('객실문자X')) {
          // 파티문자X를 파티문자O로 변경
          memo = memo.replace('객실문자X', '객실문자O');
        } else if (typeof memo === 'string' && !memo.includes('객실문자O')) {
          // 파티문자O를 셀 내용 맨 앞에 추가
          memo = '객실문자O ' + memo;
        } else if (typeof memo === 'string' && !memo.includes('객실문자O')) {
          continue;
        }

        sheet.getRange(row, columnIndex + 5).setValue(memo);
      }
    }
  } else {
    // 문자 발송 실패
    Logger.log('Error: ' + data.message);
  }
}

function partyGuideInRange(startRow, endRow) {
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
    var roomColumn = 2;
    var uniquePhoneNumbers = new Set();
    var totalParticipants = 0;

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

  totalParticipants = Math.ceil(totalParticipants / 10) * 10 + 10;
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

  var dayOfWeek = date.getDay();

  // 금요일과 토요일인지 확인
  if (dayOfWeek === 5 || dayOfWeek === 6) {
    // 금요일 또는 토요일은 남자 가격 5천 원 인상
    Logger.log("Today is either Friday or Saturday.");
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
  }

  var partyMessage = `
  스테이블 게하입니다 :)

  금일 파티 참여 시 아래 계좌로 파티비 입금 후

  성함/성별/인원/참여파티/MBTI
  회신 주시면 예약 확정 돼요.
  (예:김태희/여자/2명/1차2차/E)
 
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
    var sheet = SpreadsheetApp.openById("1CiWlgDLZCd06UNUf-6zOVO7K7u0-3d0eOkFQHCTQLZw").getSheetByName("test");
    sheet.appendRow([new Date(), data]);
    Logger.log('Error: ' + data.message);
  }
}

function getPhoneNumber() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var cell = sheet.getActiveCell();
  return cell.getValue();
}

function fetchUserInfo(userId) {
  userId = String(userId);
  Logger.log(userId)

  // URL 구성
  var url = "https://partner.booking.naver.com/v3.0/businesses/819409/users/" + userId + "?revisitPeriod=%27%27&noCache=" + new Date().getTime();

  // 요청 옵션 설정
  var options = {
    "method": "GET",
    "headers": {
      "Accept": "application/json; charset=UTF-8",
      "Content-Type": "application/json; charset=UTF-8",
      "Referer": "https://partner.booking.naver.com/bizes/819409/booking-list-view/users/" + userId,
      "Sec-Ch-Ua": '"Chromium";v="116", "Not)A;Brand";v="24", "Google Chrome";v="116"',
      "Sec-Ch-Ua-Mobile": "?0",
      "Sec-Ch-Ua-Platform": "macOS",
      "Sec-Fetch-Dest": "empty",
      "Sec-Fetch-Mode": "cors",
      "Sec-Fetch-Site": "same-origin",
      "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
      "X-Booking-Naver-Role": "OWNER",
      // 쿠키 정보를 추가합니다.
      //'Cookie': 'NNB=HT7EARW6DTQGI; nx_ssl=2; nid_inf=-1570933744; NID_AUT=K3qDSqlga2+m1SlMBr8q0bwIfsTjqG97xWpVk+xMY0Z7UgJkQIMoO63pFhpIhwDY; NID_JKL=ne8/ChcuGUepzQJH6VCagFH74pFjpLS/+wiYHiQ0rpY=; NV_WETR_LAST_ACCESS_RGN_M="MTQxMTAyNTM="; NV_WETR_LOCATION_RGN_M="MTQxMTAyNTM="; ASID=d322fc780000018a277f45430000005d; page_uid=iMYlYsprvh8ssOX04f0ssssssV4-213600; ba_access_token=bgv7fvHy6arUVsYYBYFwExBqUG%2BQfEv8zqGmZVOd6OyPIfXZvgndb29VbNjbIfrrsLBCKuc4UinwcdydQXS0rowJlVasRb5UdikhlqJrJ793VLf6yKfrDVcD%2Fs2ANSwO7tLGS%2BBbuFzkKejL%2FTxpcIeEsJ3XRIRncYBJZuKk%2Fduoz%2BvijJgn8BCBMegr3ByIQahV8ghyid165F%2FqwRBZD7PqWV3qwN0BvsZFDUNRzdTRS2p5BKvVSUM%2FZ2TjIHBxcn8Rn31tcvMGpsEXqRx2Z687S4BQx%2FXTt%2BXsWwYRfXomNCjZso9rl6u%2BFfDysXfzY2BUNMT%2BTvKQ6%2BV%2B8o6ih5fY3hvSeK%2B8gvZOvXwEBeU%3D; NID_SES=AAAB0QleqJc113m3U1ooegERPoQ2WS61bVs2AH17O5yRiiY0eHhwdvm9s3iok62wm99DE7e47ryN6Lyv14arV/0mWN84oIMuXbMeiq7LgByfCEKnqyLODuv+cgJFJe3CEpua8fDRkOGDo5iFU1oywXzd4PMhBpe8MnJ4KXoI2BBayyuWtDg8SnPTneL4TNvWDWebW5/lbTrFh5Tik6nsQiAz1FPmgJNCI2aeFCpykpwhI021q2QpHa1cRewEGlKSW9XOAY6N9x4Dm3xGexzReCREzFQytnoU2xoA8L1IUS7RFetunHMW/qOU+D0F+X/TZwybqFvl+Tkh2kZRSNvKXv6LWpzNoPqeomfQcxWkIkvFh6Z37UE/OR/2LWF64tEUxPcLpeu2G7krSB8F56QTSwRdp81/nakvdE4syxY7Gd4G3jNwJXbdYG3IcWS3gEbOHY/7mbLXCR8g1HJHE0ZBL6WOVmlunSNBiZ3vWxJHtzbtfUFi56ip66egDIIswF8MIJibPIwSOCSTJACKSXwt2yY98+1V5QFP0Cr74EX37SIlDyK7U1gKpXCfAbAJgEC9IDVu8jyvm+iszzEL30j26K0nM2q/ZG67Q9rmkLAMhFH7rqcG9l9rnLO4CSnS73Z+ZvJf3w==; csrf_token=0529d7445b89d611feb02feade78164860e97aa732d904129e19bb4a1e8606cc7eacfaa664ee8ead94ef12730c40512e79c05e16496e9e65e5c5c2c184e8cf1c' // 여기에 Cookie 정보를 넣어주세요.
      'Cookie': 'NAC=omaWBggZmKe0A; NNB=N6KW6QVASG4GO; NFS=2; page_uid=i8CA8spzL8wssdO72xsssssstbN-323643; NACT=1; SRT30=1741581331; SRT5=1741581331; nid_inf=351543061; NID_AUT=BajoX5x7B1w/4704Wk3q6WRgjBFIaRZX2ZuW0Zzm3M/2qNPwIKmpixyPSSoTa6aw; NID_SES=AAAB4CASju9oqd3pecEktU4KFBH9XiwxWZ5cmQ9Ombjz6S9dxnQyumTnxO8hGB5V5L7RSp8z/hBZKVfCQdkrZ27I/+hpX6sQDSPWr0Or4LtFU6wDD84IhqK18UwvZuCbZ6MeyNWv5llUyIUc0iBBozGJzmey7DuUwr0d/0cvbKFDoUCeeCOHSk7LnGHFNLep/L9/Curk7Drr4yR/wI/RZba9FNCpH0u59SxBfyoRSy6l3Ut5zKW/xwvu+tw3tWiCC0Xoe1XCY9eI1dShhSMpaISPj6HkgPf4ohDA9LEfY7RoFIqI198F0Vw712k6buwCuTQk7/sb7z7/jeUB57Nlek80+005nDEdhu/et9stn6iL1Qv4HpB/nFoL4xC12gMBlc81B+pojmr7LtYkbJccyFLIFec3E4rvUdaMAGoVWM0gN6hnjXv76XR9RqznVb7kZ4SxXmpz+Q7W4wyYDZNQIsvqDGCKvJLzGlXCPR1hiwVaJFXm2Hf97RcEEyct/IYrRo/FhxfLpfWRRxNCVpFcKsEeLHXDmIEzXYTXm3T/QZDVvX6CkX7u+ziDZCtN0ll1FucyTBoZbz+o6JnVO0BpQV0noMJc/+oGOJUqa0VQTajAN3vKssBkhgeKw803rZfxjgy6bA==; NID_JKL=8TawxzD5kDxI9Zdd44kzJCzCjMoJPD4+wO9wiIuXHsk=; BUC=MURoaThwVPozih9HIsJz6Ay-11P51Op2BG7VOv-ufAw='
    },
  }

  try {
    // URL로 요청 보내기
    var response = UrlFetchApp.fetch(url, options);

    // 응답을 JSON 형태로 파싱
    var userInfo = JSON.parse(response.getContentText());

    let ageMatch = userInfo.ageGroup.match(/\d+/);
    let ageString = '';
    if (ageMatch) {
      if (ageMatch[0] === '19') {
        ageString = '20';
      } else {
        ageString = ageMatch[0];
      }
    }

    // "sex"를 기반으로 '남' 또는 '여' 결정
    let sexString = '';
    if (userInfo.sex === "MALE") {
      sexString = '남';
    } else if (userInfo.sex === "FEMALE") {
      sexString = '여';
    }

    return (userInfo.completedCount + 1) + "번/" + ageString + sexString;
  } catch (e) {
    Logger.log('UserInfo JSON 파싱 오류: ' + e.toString());
  }
}

function fetchDataAndFillSheetWithDate(date, rowConfig) {
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

  var startDateTime = formatDate(date) + "T01%3A03%3A09.198Z";
  var endDateTime = formatDate(date) + "T01%3A03%3A09.198Z";

  Logger.log(startDateTime);
  Logger.log(endDateTime);

  // URL 업데이트
  var url = "https://partner.booking.naver.com/api/businesses/819409/bookings?bizItemTypes=STANDARD&bookingStatusCodes=&dateDropdownType=TODAY&dateFilter=USEDATE&endDateTime=" + endDateTime + "&maxDays=31&nPayChargedStatusCodes=&orderBy=&orderByStartDate=ASC&paymentStatusCodes=&searchValue=&searchValueCode=USER_NAME&startDateTime=" + startDateTime + "&page=0&size=200&noCache=1694307842200";

  var options = {
    method: 'GET',
    headers: {
      'Accept': '*/*',
      'Accept-Encoding': 'gzip, deflate, br',
      'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
      'Referer': 'https://partner.booking.naver.com/bizes/819409/booking-list-view',
      'Sec-Ch-Ua': '"Chromium";v="116", "Not)A;Brand";v="24", "Google Chrome";v="116"',
      'Sec-Ch-Ua-Mobile': '?0',
      'Sec-Ch-Ua-Platform': '"macOS"',
      'Sec-Fetch-Dest': 'empty',
      'Sec-Fetch-Mode': 'cors',
      'Sec-Fetch-Site': 'same-origin',
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
      //'Cookie': 'NNB=HT7EARW6DTQGI; nx_ssl=2; nid_inf=-1570933744; NID_AUT=K3qDSqlga2+m1SlMBr8q0bwIfsTjqG97xWpVk+xMY0Z7UgJkQIMoO63pFhpIhwDY; NID_JKL=ne8/ChcuGUepzQJH6VCagFH74pFjpLS/+wiYHiQ0rpY=; NV_WETR_LAST_ACCESS_RGN_M="MTQxMTAyNTM="; NV_WETR_LOCATION_RGN_M="MTQxMTAyNTM="; ASID=d322fc780000018a277f45430000005d; page_uid=iMYlYsprvh8ssOX04f0ssssssV4-213600; ba_access_token=bgv7fvHy6arUVsYYBYFwExBqUG%2BQfEv8zqGmZVOd6OyPIfXZvgndb29VbNjbIfrrsLBCKuc4UinwcdydQXS0rowJlVasRb5UdikhlqJrJ793VLf6yKfrDVcD%2Fs2ANSwO7tLGS%2BBbuFzkKejL%2FTxpcIeEsJ3XRIRncYBJZuKk%2Fduoz%2BvijJgn8BCBMegr3ByIQahV8ghyid165F%2FqwRBZD7PqWV3qwN0BvsZFDUNRzdTRS2p5BKvVSUM%2FZ2TjIHBxcn8Rn31tcvMGpsEXqRx2Z687S4BQx%2FXTt%2BXsWwYRfXomNCjZso9rl6u%2BFfDysXfzY2BUNMT%2BTvKQ6%2BV%2B8o6ih5fY3hvSeK%2B8gvZOvXwEBeU%3D; NID_SES=AAAB0QleqJc113m3U1ooegERPoQ2WS61bVs2AH17O5yRiiY0eHhwdvm9s3iok62wm99DE7e47ryN6Lyv14arV/0mWN84oIMuXbMeiq7LgByfCEKnqyLODuv+cgJFJe3CEpua8fDRkOGDo5iFU1oywXzd4PMhBpe8MnJ4KXoI2BBayyuWtDg8SnPTneL4TNvWDWebW5/lbTrFh5Tik6nsQiAz1FPmgJNCI2aeFCpykpwhI021q2QpHa1cRewEGlKSW9XOAY6N9x4Dm3xGexzReCREzFQytnoU2xoA8L1IUS7RFetunHMW/qOU+D0F+X/TZwybqFvl+Tkh2kZRSNvKXv6LWpzNoPqeomfQcxWkIkvFh6Z37UE/OR/2LWF64tEUxPcLpeu2G7krSB8F56QTSwRdp81/nakvdE4syxY7Gd4G3jNwJXbdYG3IcWS3gEbOHY/7mbLXCR8g1HJHE0ZBL6WOVmlunSNBiZ3vWxJHtzbtfUFi56ip66egDIIswF8MIJibPIwSOCSTJACKSXwt2yY98+1V5QFP0Cr74EX37SIlDyK7U1gKpXCfAbAJgEC9IDVu8jyvm+iszzEL30j26K0nM2q/ZG67Q9rmkLAMhFH7rqcG9l9rnLO4CSnS73Z+ZvJf3w==; csrf_token=0529d7445b89d611feb02feade78164860e97aa732d904129e19bb4a1e8606cc7eacfaa664ee8ead94ef12730c40512e79c05e16496e9e65e5c5c2c184e8cf1c' // 여기에 Cookie 정보를 넣어주세요.
      'Cookie': 'NAC=omaWBggZmKe0A; NNB=N6KW6QVASG4GO; NFS=2; page_uid=i8CA8spzL8wssdO72xsssssstbN-323643; NACT=1; SRT30=1741581331; SRT5=1741581331; nid_inf=351543061; NID_AUT=BajoX5x7B1w/4704Wk3q6WRgjBFIaRZX2ZuW0Zzm3M/2qNPwIKmpixyPSSoTa6aw; NID_SES=AAAB4CASju9oqd3pecEktU4KFBH9XiwxWZ5cmQ9Ombjz6S9dxnQyumTnxO8hGB5V5L7RSp8z/hBZKVfCQdkrZ27I/+hpX6sQDSPWr0Or4LtFU6wDD84IhqK18UwvZuCbZ6MeyNWv5llUyIUc0iBBozGJzmey7DuUwr0d/0cvbKFDoUCeeCOHSk7LnGHFNLep/L9/Curk7Drr4yR/wI/RZba9FNCpH0u59SxBfyoRSy6l3Ut5zKW/xwvu+tw3tWiCC0Xoe1XCY9eI1dShhSMpaISPj6HkgPf4ohDA9LEfY7RoFIqI198F0Vw712k6buwCuTQk7/sb7z7/jeUB57Nlek80+005nDEdhu/et9stn6iL1Qv4HpB/nFoL4xC12gMBlc81B+pojmr7LtYkbJccyFLIFec3E4rvUdaMAGoVWM0gN6hnjXv76XR9RqznVb7kZ4SxXmpz+Q7W4wyYDZNQIsvqDGCKvJLzGlXCPR1hiwVaJFXm2Hf97RcEEyct/IYrRo/FhxfLpfWRRxNCVpFcKsEeLHXDmIEzXYTXm3T/QZDVvX6CkX7u+ziDZCtN0ll1FucyTBoZbz+o6JnVO0BpQV0noMJc/+oGOJUqa0VQTajAN3vKssBkhgeKw803rZfxjgy6bA==; NID_JKL=8TawxzD5kDxI9Zdd44kzJCzCjMoJPD4+wO9wiIuXHsk=; BUC=MURoaThwVPozih9HIsJz6Ay-11P51Op2BG7VOv-ufAw='
    },
    muteHttpExceptions: true,
    followRedirects: true
  };

  var response = UrlFetchApp.fetch(url, options);
  var responseText = response.getContentText();

  Logger.log("응답 코드: " + response.getResponseCode());
  Logger.log("응답 내용: " + response.getContentText());

/** 시작 */
try {
  var data = JSON.parse(responseText);

  var sheetName = getdateSheetName(date);
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
  if (!sheet) {
    Logger.log(sheetName + "이라는 이름의 시트를 찾을 수 없습니다.");
  }
  Logger.log(sheet.getSheetName());

  var columnIndex = getDateChannelNameColumn(sheet, date);

  var confirmData = data.filter(item => {
    return item.bookingStatusCode === 'RC03' && formatDate(new Date(item.endDate)) !== formatDate(date);
  });

  var cancelData = data.filter(item => {
    return item.bookingStatusCode === 'RC04' && formatDate(new Date(item.endDate)) !== formatDate(date);
  });

  Logger.log("컨펌데이터 갯수 : " + confirmData.length);
  Logger.log("캔슬데이터 갯수 : " + cancelData.length);

  var NaverBizItemIdColumn = 4;
  var ReservationCountColumn = 5;

  var startRow = rowConfig.startRow;
  var endRow = rowConfig.endRow;
  var startingUnprocessedRow = rowConfig.freeStartRow;

  for (var i = cancelData.length - 1; i >= 0; i--) {
    for (var j = 0; j < confirmData.length; j++) {
      if (cancelData[i].bizItemId == confirmData[j].bizItemId &&
          cancelData[i].name == confirmData[j].name &&
          cancelData[i].phone == confirmData[j].phone) {
        Logger.log("삭제 완료" + cancelData[i].bizItemId + cancelData[i].name + cancelData[i].phone);
        cancelData.splice(i, 1);
        break;
      }
    }
  }

  Logger.log("삭제 후 캔슬데이터 갯수 : " + cancelData.length);

  // ✅ 동일 예약자(name+phone) 2건 이상 bookingId만 추출
  var multiBookingIds = new Set();
  var bookingCountMap = {};
  for (var i = 0; i < confirmData.length; i++) {
    var key = confirmData[i].name + "_" + confirmData[i].phone;
    if (!bookingCountMap[key]) {
      bookingCountMap[key] = [];
    }
    bookingCountMap[key].push(confirmData[i].bookingId);
  }
  for (var key in bookingCountMap) {
    if (bookingCountMap[key].length > 1) {
      bookingCountMap[key].forEach(function(id) {
        multiBookingIds.add(id);
      });
    }
  }

  for (var i = 0; i < confirmData.length; i++) {
    confirmData[i].flag = false;
  }

  for (var row = startRow; row <= endRow; row++) {
    if (rowConfig.excludeRows.includes(row)) continue;

    var bizItemIdFromSheet = sheet.getRange(row, NaverBizItemIdColumn).getValue();
    var name = sheet.getRange(row, columnIndex).getValue();
    var cellPhone = sheet.getRange(row, columnIndex + 1).getValue();
    var existingBookingId = sheet.getRange(row, columnIndex + 5).getValue();
    existingBookingId = existingBookingId ? existingBookingId.toString().match(/\[(\d+)\]/)?.[1] : null;

    if (cellPhone) {
      for (var j = 0; j < confirmData.length; j++) {
        var dataPhone = confirmData[j].phone;
        var dataVisitorPhone = confirmData[j].visitorName && confirmData[j].visitorPhone ? confirmData[j].visitorPhone : null;

        if (multiBookingIds.size > 0 && multiBookingIds.has(confirmData[j].bookingId)) {
          if (existingBookingId == confirmData[j].bookingId) {
            Logger.log("시트에 동일 bookingId 존재함: " + confirmData[j].bookingId);
            confirmData[j].flag = true;
            continue;
          }
        }

        if (cellPhone == dataPhone || (dataVisitorPhone && cellPhone == dataVisitorPhone)) {
          Logger.log("시트에 bizItemId와 phone/visitorPhone 동일한 데이터 존재함: " + confirmData[j].name);
          confirmData[j].flag = true;
          break;
        }
      }
    }
  }

  for (var row = startRow; row <= endRow; row++) {
    if (rowConfig.excludeRows.includes(row)) continue;

    var bizItemIdFromSheet = sheet.getRange(row, NaverBizItemIdColumn).getValue();
    var nameValue = sheet.getRange(row, columnIndex).getValue();
    if (nameValue) continue;

    for (var i = 0; i < confirmData.length; i++) {
      if (confirmData[i].bizItemId === bizItemIdFromSheet && !confirmData[i].flag) {
        var userInfo = fetchUserInfo(String(confirmData[i].userId));
        var phoneToUse = confirmData[i].visitorName && confirmData[i].visitorPhone ? confirmData[i].visitorPhone : confirmData[i].phone;
        var nameWithVisitor = confirmData[i].name;
        if (confirmData[i].visitorName) nameWithVisitor += "[" + confirmData[i].visitorName + "]";

        sheet.getRange(row, columnIndex + 1).setValue("'" + phoneToUse);
        sheet.getRange(row, columnIndex).setValue(nameWithVisitor + "(" + userInfo + ")");

        var peopleNumber = sheet.getRange(row, ReservationCountColumn).getValue();
        if (confirmData[i].bookingOptionJson && confirmData[i].bookingOptionJson.length > 0) {
          for (let j = 0; j < confirmData[i].bookingOptionJson.length; j++) {
            if (confirmData[i].bookingOptionJson[j].bookingCount === 1) {
              peopleNumber = confirmData[i].bookingOptionJson[j].bookingCount;
            } else {
              peopleNumber = confirmData[i].bookingOptionJson[j].bookingCount;
            }
            break;
          }
        } else {
          const isSingle = confirmData[i].bookingCount == 1;
          if (isSingle) {
            peopleNumber = getMaxPeopleByRoomId(confirmData[i].bizItemId)
          } else {
            peopleNumber = confirmData[i].bookingCount;
          }
        }
        
        const isDormitory = [4779029, 4779028].includes(confirmData[i].bizItemId)
        if (isDormitory) {
          const sexText = confirmData[i].bizItemId == 4779029 ? "여" : "남"
          sheet.getRange(row, columnIndex + 3).setValue(sexText + peopleNumber);  
        } else {
          sheet.getRange(row, columnIndex + 3).setValue(userInfo.slice(-1) + peopleNumber);
        }

        sheet.getRange(row, columnIndex + 4).setValue(confirmData[i].bookingCount);

        if (multiBookingIds.size > 0 && multiBookingIds.has(confirmData[i].bookingId)) {
          sheet.getRange(row, columnIndex + 5).setValue('중복체크id[' + confirmData[i].bookingId + ']');
        }

        sheet.getRange(row, columnIndex).setHorizontalAlignment('center').setVerticalAlignment('middle');
        sheet.getRange(row, columnIndex + 1).setHorizontalAlignment('center').setVerticalAlignment('middle');
        sheet.getRange(row, columnIndex + 3).setHorizontalAlignment('center').setVerticalAlignment('middle');

        confirmData[i].flag = true;
        break;
      }
    }
  }

  for (var i = 0; i < confirmData.length; i++) {
    if (!confirmData[i].flag) {
      if (multiBookingIds.size > 0 && multiBookingIds.has(confirmData[i].bookingId)) {
        var alreadyExists = false;
        for (var row = 3; row <= endRow; row++) {
          if (rowConfig.excludeRows.includes(row)) continue;
          var existingBookingId = sheet.getRange(row, columnIndex + 5).getValue();
          existingBookingId = existingBookingId ? existingBookingId.toString().match(/\[(\d+)\]/)?.[1] : null;

          if (existingBookingId == confirmData[i].bookingId) {
            alreadyExists = true;
            break;
          }
        }
        if (alreadyExists) continue;
      }

      var userInfo = fetchUserInfo(String(confirmData[i].userId));
      var nameWithVisitor = confirmData[i].name;
      if (confirmData[i].visitorName) nameWithVisitor += "[" + confirmData[i].visitorName + "]";

      sheet.getRange(startingUnprocessedRow, columnIndex).setValue(nameWithVisitor + "(" + userInfo + ")");
      var phoneToUse = confirmData[i].visitorName && confirmData[i].visitorPhone ? confirmData[i].visitorPhone : confirmData[i].phone;
      sheet.getRange(startingUnprocessedRow, columnIndex + 1).setValue("'" + phoneToUse);

      var peopleNumber = sheet.getRange(row, ReservationCountColumn).getValue();
      if (confirmData[i].bookingOptionJson && confirmData[i].bookingOptionJson.length > 0) {
        for (let j = 0; j < confirmData[i].bookingOptionJson.length; j++) {
          if (confirmData[i].bookingOptionJson[j].bookingCount === 1) {
            peopleNumber = confirmData[i].bookingOptionJson[j].bookingCount;
          } else {
            peopleNumber = confirmData[i].bookingOptionJson[j].bookingCount;
          }
          break;
        }
      } else {
        const isSingle = confirmData[i].bookingCount == 1;
        if (isSingle) {
          peopleNumber = getMaxPeopleByRoomId(confirmData[i].bizItemId)
        } else {
          peopleNumber = confirmData[i].bookingCount;
        }
      }

      var existingValue3 = sheet.getRange(startingUnprocessedRow, columnIndex + 3).getValue();
      if (!existingValue3) {
        const isDormitory = [4779029, 4779028].includes(confirmData[i].bizItemId)
        if (isDormitory) {
          const sexText = confirmData[i].bizItemId == 4779029 ? "여" : "남"
          sheet.getRange(startingUnprocessedRow, columnIndex + 3).setValue(sexText + peopleNumber);
        } else {
          sheet.getRange(startingUnprocessedRow, columnIndex + 3).setValue(userInfo.slice(-1) + peopleNumber);
        }  
      }

      var existingValue4 = sheet.getRange(startingUnprocessedRow, columnIndex + 4).getValue();
      if (!existingValue4) {
        sheet.getRange(startingUnprocessedRow, columnIndex + 4).setValue(
          confirmData[i].bookingCount + " (" + getRoomName(confirmData[i].bizItemId) + ")"
        );
      }

      if (multiBookingIds.size > 0 && multiBookingIds.has(confirmData[i].bookingId)) {
        sheet.getRange(startingUnprocessedRow, columnIndex + 5).setValue('중복체크id[' + confirmData[i].bookingId + ']');
      }

      sheet.getRange(startingUnprocessedRow, columnIndex).setHorizontalAlignment('center').setVerticalAlignment('middle');
      sheet.getRange(startingUnprocessedRow, columnIndex + 1).setHorizontalAlignment('center').setVerticalAlignment('middle');
      sheet.getRange(startingUnprocessedRow, columnIndex + 3).setHorizontalAlignment('center').setVerticalAlignment('middle');

      confirmData[i].flag = true;
      startingUnprocessedRow++;
    }
  }
} catch (e) {
  Logger.log('JSON 파싱 오류: ');
  Logger.log(e);
}

/** 끝 */

  sheet.setColumnWidth(columnIndex, 120);
  sheet.autoResizeColumn(columnIndex + 1);
  sheet.setColumnWidth(columnIndex + 3, 50);

  sheet.getRange(row, columnIndex).setHorizontalAlignment('center').setVerticalAlignment('middle');

}
