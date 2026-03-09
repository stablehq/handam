function getdateSheetName(date) {
  var month = (date.getMonth() + 1).toString(); // getMonth()는 0부터 11까지의 값을 반환하므로 1을 더한다.
  if (month.length === 1) month = '0' + month; // 월이 한 자리수면 앞에 '0'을 붙여준다.

  var year = date.getFullYear().toString();
  return year + month; // 예: 202308
}