
/**
 * 메모에 targetTag가 포함되어 있고, markText가 없는 사람만 전화번호 추출
 */
function collectPhonesByTagAndMark(sheet, columnIndex, startRow, endRow, targetTag, markText) {
  const phoneNumbersToSend = new Set();

  const multiTagMap = {
    '1,2,2차만': ['1', '2', '2차만'],
    '2차만': ['2차만']
  };

  const memoColumnOffset = (targetTag === '2차만' || targetTag === '1,2,2차만') ? 2 : 4;
  const targetTags = multiTagMap[targetTag] || [targetTag];

  for (let row = startRow; row <= endRow; row++) {
    const cellPhone = sheet.getRange(row, columnIndex + 1).getValue();
    const memo = sheet.getRange(row, columnIndex + memoColumnOffset).getValue().toString();
    const mark = sheet.getRange(row, columnIndex + 5).getValue().toString();

    const hasTag = targetTags.some(tag => memo.includes(tag));

    if (hasTag) {
      if (typeof mark !== 'string' || !mark.includes(markText)) {
        if (cellPhone && /^\d+$/.test(cellPhone)) {
          phoneNumbersToSend.add(cellPhone);
        }
      }
    }
  }

  return Array.from(phoneNumbersToSend);
}

/**
 * 발송한 전화번호에 markText 추가
 */
function markSentPhoneNumbers(sheet, phoneNumbers, columnIndex, startRow, endRow, markText) {
  for (var row = startRow; row <= endRow; row++) {
    var cellPhone = sheet.getRange(row, columnIndex + 1).getValue();
    var memo = sheet.getRange(row, columnIndex + 5).getValue().toString();

    if (phoneNumbers.includes(cellPhone)) {
      if (typeof memo === 'string' && memo.includes(markText)) {
        continue; // 이미 표시되어 있으면 건너뛰기
      }
      var updatedMemo = memo + ' ' + markText;

      const richText = SpreadsheetApp.newRichTextValue()
      .setText(updatedMemo)
      .setTextStyle(0, updatedMemo.length, SpreadsheetApp.newTextStyle().setBold(true).build())
      .build();

      sheet.getRange(row, columnIndex + 5).setRichTextValue(richText);
    }
  }
}

/**
 * 문자 발송 로직 + 마킹 (공통 흐름)
 */
function sendSmsAndMark(date, targetTag, markText, message, apiUrl = "http://15.164.246.59:3000/sendMass") {
  try {
    var sheetName = getdateSheetName(date);
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
    if (!sheet) {
      Logger.log(sheetName + " 시트를 찾을 수 없습니다.");
      return;
    }

    var columnIndex = getDateChannelNameColumn(sheet, date);
    var startRow = 3;
    var endRow = 99; // 파티까지만

    var phonesToSend = collectPhonesByTagAndMark(sheet, columnIndex, startRow, endRow, targetTag, markText);
    Logger.log("발송 대상: " + phonesToSend.join(", "));

    if (phonesToSend.length === 0) {
      Logger.log("발송 대상자가 없습니다.");
      return;
    }

    // ===============================
    //        문자 발송 로직
    // ===============================
    var payload = {
      "msg_type": "LMS",
      "cnt": phonesToSend.length.toString(),
      "testmode_yn": "N"
    };

    for (var i = 0; i < phonesToSend.length; i++) {
      payload["rec_" + (i + 1)] = phonesToSend[i];
      payload["msg_" + (i + 1)] = message;
    }

    var options = {
      "method": "post",
      "payload": JSON.stringify(payload),
      "contentType": "application/json",
      "muteHttpExceptions": true
    };

    var response = UrlFetchApp.fetch(apiUrl, options);
    var data = JSON.parse(response.getContentText());

    // ===============================
    //       발송 성공 시 마킹
    // ===============================
    if (data.result_code == 1) {
      Logger.log('Message ID: ' + data.msg_id);
      Logger.log('Success Count: ' + data.success_cnt);
      Logger.log('Error Count: ' + data.error_cnt);

      markSentPhoneNumbers(sheet, phonesToSend, columnIndex, startRow, endRow, markText);
      Logger.log("마킹 완료: " + markText);
    } else {
      Logger.log('발송 실패: ' + data.message);
    }

  } catch (e) {
    Logger.log('Error: ' + e.toString());
  }
}

/**
 * 객실후필_어제
 */
function reviewRequiredYesterday(message) {
  var date = new Date();
  date.setDate(date.getDate()-1); // 어제 날짜 설정
  sendSmsAndMark(date, "객후", "객후", message);
}

/**
 * 객실업글_오늘
 */
function reviewRequiredToday(message) {
  var date = new Date();
  date.setDate(date.getDate());
  sendSmsAndMark(date, "객후", "객후", message);
}

/**
 * 1차초대_어제
 */
function invite1Yesterday(message) {
  var date = new Date();
  date.setDate(date.getDate()-1);
  sendSmsAndMark(date, "1초", "1초", message);
}

/**
 * 2차초대_어제
 */
function invite2Yesterday(message) {
  var date = new Date();
  date.setDate(date.getDate()-1);
  sendSmsAndMark(date, "2초", "2초", message);
}

/**
 * 더블추2_오늘
 */
function addDoubleToday(message) {
  var date = new Date();
  date.setDate(date.getDate());
  sendSmsAndMark(date, "더블추2", "더블추2", message);
}

/**
 * 추2_오늘
 */
function addToday(message) {
  var date = new Date();
  date.setDate(date.getDate());
  sendSmsAndMark(date, "추2", "추2", message);
}

/**
 * 추4_오늘
 */
function add4Today(message) {
  var date = new Date();
  date.setDate(date.getDate());
  sendSmsAndMark(date, "추4", "추4", message);
}

/**
 * 추6_오늘
 */
function add6Today(message) {
  var date = new Date();
  date.setDate(date.getDate());
  sendSmsAndMark(date, "추6", "추6", message);
}

/**
 * 2차만_오늘
 */
function party2Today(message) {
  var date = new Date();
  date.setDate(date.getDate());
  sendSmsAndMark(date, "2차만", "2안", message);
}

/**
 * 3차안내_오늘
 */
function party3Today() {
  var date = new Date();
  date.setDate(date.getDate());
  sendSmsAndMark(date, "1,2,2차만", "3안", party3Message(), "http://15.164.246.59:3000/sendMass/image");
}

// 3차 안내 고정 문자
function party3Message() {

    message = `
스테이블 포차파티가 곧 종료됩니다~ 

아쉬운분들을 위해 소중한 인연 이어가시거나 
새로운 인연 만들 수 있는 애프터파티가 준비 되어 있습니다!

- 장소: 언스테이블 혼술바 (도보 5초거리, 스테이블A동 1층)
- 시간: 지금부터 새벽3시까지

감사합니다.
`

    var date = new Date();
    var dayOfWeek = date.getDay();
    // 금요일과 토요일인지 확인
    if (dayOfWeek === 5 || dayOfWeek === 6) {
      // 금요일 또는 토요일은 남자 가격 5천 원 인상
      message = `
스테이블 포차파티가 곧 종료됩니다~ 

아쉬운분들을 위해 소중한 인연 이어가시거나 
새로운 인연 만들 수 있는 애프터파티가 준비 되어 있습니다!

- 장소: 언스테이블 혼술바 (도보 5초거리, 스테이블A동 1층)
- 시간: 지금부터 새벽3시까지
- 수용인원이 협소함으로 미리 가서 자리 잡으시는게 좋습니다

감사합니다.
`
    }

  return message;
}

/* 여자초대_어제 */
function inviteGirlYesterdayWrapper() {
  const template = getMessageByType("inviteGirlYesterday");

  return inviteGirlYesterday(template);
}

function inviteGirlYesterday(template) {
  const today = new Date();
  const message = inviteGirlMessage2(today, template, 4)
  if (message == null) {
    return;
  }

  let date = new Date();
  date.setDate(date.getDate()-1);
  sendSmsAndMark(date, "여초", "여초", message);
}

// 성비 추출하는 함수
function inviteGirlMessage2(date, template, number) {
  const sheetName = getdateSheetName(date);
  const genderCounts = extractGenderCount2(sheetName, date);

  // ✅ null 체크 추가
  if (!genderCounts) {
    Logger.log("성별 데이터 추출 실패 → 메시지 전송 안 함");
    return null;
  }

  const maleCount = Math.round(genderCounts.male);
  const femaleCount = Math.round(genderCounts.female + number);

  if (maleCount === 0 && femaleCount === number) {
    Logger.log('남자, 여자 인원이 모두 0 → 메시지 보내지 않음');
    return null;
  }

  const variables = {
    maleCount,
    femaleCount
  };

  return replaceMessage(template, variables);
}

/**
 * 여자초대_어제 (기존버전/임시로주석처리)
 */
// function inviteGirlYesterday(template) {
//   const today = new Date();
//   const message = inviteGirlMessage(today, template, 4)
//   if (message == null) {
//     return;
//   }

//   let date = new Date();
//   date.setDate(date.getDate()-1);
//   sendSmsAndMark(date, "여초", "여초", message);
// }

/**
 * 성비_어제
 */
function sexYesterday(template) {
  const today = new Date();
  const message = inviteGirlMessage(today, template, 0)
  if (message == null) {
    return;
  }

  let date = new Date();
  date.setDate(date.getDate()-1);
  sendSmsAndMark(date, "성비", "성비", message);
}

// 성비 추출하는 함수
function inviteGirlMessage(date, template, number) {
  const sheetName = getdateSheetName(date);
  const genderCounts = extractGenderCount(sheetName, date);

  const maleCount = Math.round(genderCounts.male);
  const femaleCount = Math.round(genderCounts.female + number);

  if (maleCount === 0 && femaleCount === number) {
    Logger.log('남자, 여자 인원이 모두 0 → 메시지 보내지 않음');
    return null;
  }

  const variables = {
    maleCount: maleCount,
    femaleCount: femaleCount
  }

  return replaceMessage(template, variables);
}

/**
 * 파초_어제
 */
function invitePartyYesterday(message) {
  var date = new Date();
  date.setDate(date.getDate()-1); // 어제 날짜 설정
  sendSmsAndMark(date, "파초", "파초", message);
}

/**
 * 무연_어제
 */
function freeStayYesterday(message) {
  var date = new Date();
  date.setDate(date.getDate()-1); // 어제 날짜 설정
  sendSmsAndMark(date, "무연", "무연", message);
}

/**
 * 언스_어제
 */
function UnstableYesterday(message) {
  var date = new Date();
  date.setDate(date.getDate()-1); // 어제 날짜 설정
  sendSmsAndMark(date, "언스", "언스", message);
}


/**
 * 투어_오늘 내일
 */
function activityTomorrow(message) {
  var date = new Date();
  date.setDate(date.getDate());
  sendSmsAndMark(date, "", "투어", message);

  date.setDate(date.getDate()+1);
  sendSmsAndMark(date, "", "투어", message);
}