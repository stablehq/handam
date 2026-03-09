function extractGenderCount2(sheetName, date) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
  const columnIndex = getDateChannelNameColumn(sheet, date);

  const value = sheet.getRange(137, columnIndex + 5).getValue().toString();
  const regex = /^(\d+)\s*대\s*(\d+)$/;
  const match = value.match(regex);

  if (!match) {
    return null; // 추출 실패 시 null 반환
  }

  let male = parseInt(match[1], 10);
  let female = parseInt(match[2], 10);

  // 🔧 보정값 적용
  male = isNaN(male) ? 0 : male;
  female = isNaN(female) ? 0 : female - 4;

  return { male, female };
}
