function getDateChannelNameColumn(sheet, targetDate) {
  // 매개변수로 받은 날짜 포맷하기
  var formattedDate = Utilities.formatDate(targetDate, "GMT+9", "M월 d일"); // "M월 d일" 형식으로 날짜 포맷하기
  Logger.log(formattedDate)

  // 첫 번째 행의 값을 가져와서 지정된 날짜의 위치를 찾기
  var firstRow = sheet.getRange(1, 1, 1, sheet.getMaxColumns()).getValues()[0];
  var dateColumnIndex = -1;

  for (var i = 0; i < firstRow.length; i++) {
    var cellValue = firstRow[i];

    // 날짜 데이터인 경우 포맷을 맞춰서 비교
    if (cellValue instanceof Date) {
      var cellFormattedDate = Utilities.formatDate(cellValue, "GMT+9", "M월 d일");
      if (cellFormattedDate === formattedDate) {
        dateColumnIndex = i + 1;
        break;
      }
    } else if (cellValue === formattedDate) { // 문자열 데이터인 경우 직접 비교
      dateColumnIndex = i + 1;
      break;
    }
  }

  // 지정된 날짜를 찾지 못한 경우
  if (dateColumnIndex === -1) {
    Logger.log('지정된 날짜의 셀을 찾을 수 없습니다.');
    return -1;
  }

  // 2행의 값을 가져와서 지정된 날짜 이후로부터 "이름" 컬럼 위치 찾기
  var secondRow = sheet.getRange(2, 1, 1, sheet.getMaxColumns()).getValues()[0];
  var channelNameColumnIndex = -1;
  for (var i = dateColumnIndex - 1; i < secondRow.length; i++) { // dateColumnIndex는 1부터 시작하므로 배열 인덱스로 맞추기 위해 -1
    if (secondRow[i] === "이름") {
      channelNameColumnIndex = i + 1;
      break;
    }
  }

  if (channelNameColumnIndex === -1) {
    Logger.log('이름 컬럼을 찾을 수 없습니다.');
    return -1;
  }

  return channelNameColumnIndex;
}