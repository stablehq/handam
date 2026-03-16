function onOpen() {
  var ui = SpreadsheetApp.getUi();

  var menu = ui.createMenu('스테이블 CMS');
  menu.addItem('오늘 데이터 업데이트하기', 'processToday')
    .addItem('내일 데이터 업데이트하기', 'processTomorrow')
    .addItem('오늘 파티 안내 문자', 'partyGuideSMS')
    .addItem('오늘 객실 안내 문자', 'roomGuideSMS')
    .addItem('오늘 별관 객실 안내 문자', 'sendStarRoomGuide')
    .addToUi();

  var menu2 = ui.createMenu('트리거 수동 전송');
  menu2
    .addItem('[어제] 객실후필', 'reviewRequiredYesterdayWrapper')
    .addItem('[어제] 1차초대', 'invite1YesterdayWrapper')
    .addItem('[어제] 2차초대', 'invite2YesterdayWrapper')
    .addItem('[어제] 여자초대', 'inviteGirlYesterdayWrapper')
    .addItem('[어제] 성비', 'sexYesterdayWrapper')
    .addItem('[어제] 파티초대', 'invitePartyYesterdayWrapper')
    .addItem('[어제] 무료연박', 'freeStayYesterdayWrapper')
    .addItem('[오늘] 객실후필', 'reviewRequiredTodayWrapper')
    .addItem('[오늘] 더블추2', 'addDoubleTodayWrapper')
    .addItem('[오늘] 추2', 'addTodayWrapper')
    .addItem('[오늘] 추4', 'add4TodayWrapper')
    .addItem('[오늘] 추6', 'add6TodayWrapper')
    .addItem('[오늘] 2차만', 'party2TodayWrapper')
    .addItem('[오늘] 3차안내', 'party3TodayWrapper')
    .addItem('[내일] 액티비티 알림', 'activityTomorrowWrapper')
    .addToUi();
}