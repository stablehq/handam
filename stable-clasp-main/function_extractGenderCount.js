function extractGenderCount(sheetName, date) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
  const columnIndex = getDateChannelNameColumn(sheet, date);
  
  const value = sheet.getRange(134, columnIndex + 5).getValue().toString();
  
  const regex = /^남:\s*(\d+)\s*\/\s*여:\s*(\d+)$/;
  const match = value.match(regex);
  
  let male = 0;
  let female = 0;
  
  if (match) {
    male = parseInt(match[1], 10);
    female = parseInt(match[2], 10);
  }
  
  return {
    male: isNaN(male) ? 0 : male,
    female: isNaN(female) ? 0 : female
  };
}