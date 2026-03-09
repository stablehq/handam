function sendStarRoomGuideInRange(startRow, endRow) {
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
    const sheetName = getdateSheetName(date);
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
    const collectedData = [];
    if (!sheet) {
      Logger.log(`${sheetName}이라는 이름의 시트를 찾을 수 없습니다.`);
    }
    Logger.log(sheet.getSheetName());

    const columnIndex = getDateChannelNameColumn(sheet, date);
    const roomColumn = 2;

    for (let row = startRow; row <= endRow; row++) {
      let memo = sheet.getRange(row, columnIndex + 5).getValue().toString();
      const cellPhone = sheet.getRange(row, columnIndex + 1).getValue();
      const cellName = sheet.getRange(row, columnIndex).getValue().split('(')[0].trim();

      if ((typeof memo === 'string' && memo.includes('별관문자O')) || !(cellPhone && /^\d+$/.test(cellPhone))) {
        continue;
      }

      const cellValue = getMergedCellValue(sheet, row, roomColumn).trim();
      const matchResult = cellValue.match(/^(.*)\s*\(([^)]+)\)$/);
      const roomName = matchResult ? matchResult[1].trim() : null;
      const roomInfo = matchResult ? matchResult[2].trim() : null;

      Logger.log(`roomName: ${roomName} / roomInfo: ${roomInfo}`);

      let roomPasscode = null;

      // 별관 독채 트윈 (101~109) → passcode 생성
      if (roomName === '별관 독채 트윈' && roomInfo.length === 3 && parseInt(roomInfo) >= 101 && parseInt(roomInfo) <= 109) {
        const lastDigit = roomInfo.charAt(2);
        roomPasscode = `622${lastDigit}*`;
      }

      const newData = {
        roomName,
        cellName,
        cellPhone,
        roomPasscode,
        roomInfo
      };

      const isDuplicate = collectedData.some(data =>
        data.roomName === newData.roomName &&
        data.cellName === newData.cellName &&
        data.cellPhone === newData.cellPhone
      );

      if (!isDuplicate) {
        collectedData.push(newData);
      }
    }

    const payload = {
      "msg_type": "LMS",
      "cnt": collectedData.length.toString(),
      "testmode_yn": "N"
    };

    for (let i = 0; i < collectedData.length; i++) {
      const data = collectedData[i];
      let roomMessage = '';

      if (data.roomName.startsWith('별관 더블룸')) {
        roomMessage = `
별관 더블룸(로하스) 객실 안내 문자 입니다.

스테이블 별관(로하스)
체크인 안내 드려요!

스테이블로 오시면 안되고요,
반드시 아래 주소에서 체크인 해주세요.

[별관 주소]
- 주소: 안덕면 사계로 62 로하스
- 체크인 문의 
  T. 01097701418

- 체크인: 오후 5시
- 체크아웃: 낮 12시

[파티장 주소]
- 안덕면 사계북로 109 
스테이블 B동 1층 포차 

- 숙소에서 도보 5분 이내 거리예요 (바로 코너 돌아 3분 걸어오시면 되요)

- 파티 참여 시 8시까지 스테이블 B동 1층 포차로 와주세요

- 파티 후 숙소 들어가실 때 꼭꼭꼭 정숙 부탁 드려요. 온 마을이 조용해요!

- 객실 내 구토나 심한 오염 발생 시 세탁비 10만 원 청구되오니 주의 당부드려요.

- 아울러 객실 내 정해진 인원 외에 입장 시 퇴실 조치 되는점 참고해주세요.

그럼 즐거운 추억이 될 수 
있게 최선을 다할께요!
`;
      } else if (data.roomName.startsWith('별관 독채 트윈')) {
        roomMessage = `
스테이블 별관 독채트윈룸
객실 안내 문자 입니다 :)

- 주소: 제주 서귀포시 안덕면 사계로 187-3 
(현재 모먼트 게스트하우스 간판)

[체크인 안내]
- 체크인: 오후 5시
- 체크아웃: 낮 11시          
* 12시 이후 퇴실 시 30분당 5천원씩 추가 요금 있어요

- 체크인 문의: 01079304243

<금일 객실은 별관 모먼트 ${data.roomInfo}호 - 비밀번호: ${data.roomPasscode}>

- 객실내에서 음주, 흡연, 침구류 훼손, 혼숙(커플 제외)은 절대 금지이고, 적발 시 벌금 10만원이 청구됩니다.

- 객실내에서 편의점 식품 등 간단한 음식 섭취만 가능해요! 

- 펜션 내 편의점이 11시까지 운영되니 이용해주시면 되세요.

- 늦은 시간 귀가 시 조용히 입실해주시고, 취기로 인해 본인 객실말고 타인의 객실 들어가려고 할 시 경찰이 출동할 수 있으니 꼭 본인 객실에 입실해주세요.

- 파티 신청 시 파티장 픽업 문자는 19시30분 전에 문자로 안내 드릴게요.

그럼 조심히 오세요 :)
`;
      } else if (data.roomName.startsWith('별관 독채')) {
        roomMessage = `
별관 독채(펠리체) 객실 안내 문자 입니다.

스테이블 별관(펠리체) 
체크인 안내 드려요. 

스테이블로 오시면 안되고요 ,아래 주소에서 체크인 해주세요.

- 별관 주소: 서귀포시 안덕면 사계북로 117 펠리체 
(스테이블 바로 옆 건물)

- 체크인: 오후 5시 
- 체크아웃: 낮 11시

- 별관 체크인 문의 01040151585 

- 파티장 주소: 서귀포시 안덕면 사계북로 109 스테이블 1층 B동 포차 

- 파티 참여 시 8시까지 스테이블B동 1층 포차로 와주세요

그럼 즐거운 추억이 될 수 있게 최선을 다하겠습니다.`;
      } else if (data.roomName.startsWith('별관 디럭스')) {
        roomMessage = `
별관 디럭스룸(루시드엠) 객실 안내 문자 입니다.

스테이블입니다. 금일 별관(루시드엠) 체크인 안내드려요.

[체크인 안내]
- 체크인: 오후 5시 
- 체크아웃: 오전 11시

- 주소: 서귀포시 안덕면 사계북로 120 루시드엠 (스테이블은 대각선 건물)

- 체크인 문의: 01068689288

- 파티장 주소: 서귀포시 안덕면 사계북로 109 스테이블 1층 포차 

- 별관에서 바로 대각선 건물로 파티 참여 시 스테이블B동 1층으로 8시까지 와주세요

- 1층으로 오전 8시 30분 ~ 9시 사이 오시면 조식 드실 수 있어요

- 퇴실 시 문 열어놓고 가주세요

즐거운 추억이 될 수 있게 
최선을 다하겠습니다!`;
      } else {
        Logger.log(`별관 케이스에 포함되지 않음: ${data.roomName}`);
        continue;
      }

      payload[`rec_${i + 1}`] = data.cellPhone;
      payload[`msg_${i + 1}`] = roomMessage;
    }

    Logger.log(JSON.stringify(payload));

    const options = {
      method: "post",
      payload: JSON.stringify(payload),
      contentType: "application/json",
      muteHttpExceptions: true
    };

    const response = UrlFetchApp.fetch(apiUrl, options);
    const responseData = JSON.parse(response.getContentText());

    if (responseData.result_code == 1) {
      Logger.log(`Message ID: ${responseData.msg_id}`);
      Logger.log(`Message Type: ${responseData.msg_type}`);
      Logger.log(`Success Count: ${responseData.success_cnt}`);
      Logger.log(`Error Count: ${responseData.error_cnt}`);

      for (let row = startRow; row <= endRow; row++) {
        let memo = sheet.getRange(row, columnIndex + 5).getValue().toString();
        const cellPhone = sheet.getRange(row, columnIndex + 1).getValue();
        const cellName = sheet.getRange(row, columnIndex).getValue().split('(')[0].trim();
        const cellValue = getMergedCellValue(sheet, row, roomColumn).trim();
        const matchResult = cellValue.match(/^(.*)\s*\(([^)]+)\)$/);
        const roomName = matchResult ? matchResult[1].trim() : null;

        if (!(cellPhone && /^\d+$/.test(cellPhone))) {
          continue;
        }

        const isMatched = collectedData.some(data =>
          data.roomName === roomName &&
          data.cellName === cellName &&
          data.cellPhone === cellPhone
        );

        if (isMatched) {
          const isByulGwan = roomName && roomName.startsWith('별관');

          // ✅ 별관문자O 추가 (단, memo에 객실문자O가 있으면 건너뜀)
          if (isByulGwan) {
            if (memo.includes('객실문자O')) {
              Logger.log(`별관인데 memo에 객실문자O 발견 → 별관문자O 추가 건너뜀 (row: ${row})`);
            } else {
              if (memo.includes('별관문자X')) {
                memo = memo.replace('별관문자X', '별관문자O');
              } else if (!memo.includes('별관문자O')) {
                memo = '별관문자O ' + memo;
              }
            }
          }

          sheet.getRange(row, columnIndex + 5).setValue(memo);
        }
      }
    } else {
      Logger.log(`Error: ${responseData.message}`);
    }

  } catch (e) {
    Logger.log(`Error: ${e.toString()}`);
  }
}