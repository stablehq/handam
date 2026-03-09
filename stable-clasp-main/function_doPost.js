function doPost(e) {

  // e는 요청 객체 (POST 데이터, 헤더 등 포함)
  const data = JSON.parse(e.postData.contents);
  const targetDate = data.targetDate;
  const messageContent = (data && data.messageContent) ? data.messageContent : "";

  const now = new Date();
  const hour = now.getHours(); // 현재 시간 (0~23)
  const min = now.getMinutes();

// 트리거 허용 시간 08:59:00 ~ 00:00:00 (한국 시간 기준)
if (hour < 8 || (hour === 8 && min < 59) || (hour === 0 && min > 0)) {
  Logger.log("⏰ 허용된 시간대가 아님: " + hour + "시 " + min + "분");
  return ContentService.createTextOutput("Allowed time: 08:59 ~ 00:00 (KST)");
}

  // 트리거 로그 확인
  var sheet = SpreadsheetApp.openById("1CiWlgDLZCd06UNUf-6zOVO7K7u0-3d0eOkFQHCTQLZw").getSheetByName("test");
  sheet.appendRow([new Date(), data]);

  // targetDate 값에 따라 함수 분기 호출
  switch (targetDate) {

    /**
     * 예약갱신_어제/오늘
     */
    case 'today_tomorrow':
      processToday();
      processTomorrow();
      break;

    /**
     * 파티문자_오늘
     */
    case 'today_party':
      partyGuideSMS();
      break;

    // 파티문자_오늘_주말 가격
    case 'today_party_upgrade':
      sendPartyGuide();
      break;

    /**
     * 객실문자_오늘
     */
    case 'today_room':
      roomGuideSMS();
      sendStarRoomGuide();
      break;

    /**
     * 객실후필_어제
     */
    case 'review_required_yesterday':
      reviewRequiredYesterday(messageContent);
      break;

    /**
     * 객실후필_오늘
     */
    case 'review_required_today':
      reviewRequiredToday(messageContent);
      break;

    /**
     * 1차초대_어제
     */
    case 'invite1_yesterday':
      invite1Yesterday(messageContent);
      break;

    /**
     * 2차초대_어제
     */
    case 'invite2_yesterday':
      invite2Yesterday(messageContent);
      break;

    /**
     * 여자초대_어제
     */
    case 'invite_girl_yesterday':
      inviteGirlYesterday(messageContent);
      break;

    /**
     * 성비_어제
     */
    case 'sex_yesterday':
      sexYesterday(messageContent);
      break;

    /**
     * 더블추2_오늘
     */
    case 'add_double_today':
      addDoubleToday(messageContent);
      break;
    
    /**
     * 추2_오늘
     */    
    case 'add_today':
      addToday(messageContent);
      break;

    /**
     * 추4_오늘
     */    
    case 'add4_today':
      add4Today(messageContent);
      break;

    /**
     * 추6_오늘
     */    
    case 'add6_today':
      add6Today(messageContent);
      break;

    /**
     * 2차안내_오늘
     */    
    case 'party2_today':
      party2Today(messageContent);
      break;

    /**
     * 3차안내_오늘
     */    
    case 'party3_today':
      party3Today();
      break;

    /**
     * 파초_어제
     */
    case 'invite_party_yesterday':
      invitePartyYesterday(messageContent);
      break;

    /**
     * 무연_어제
     */
    case 'free_stay_yesterday':
      freeStayYesterday(messageContent);
      break;

    /**
     * 알림_오늘내일
     */
    case 'activity_tomorrow':
      activityTomorrow(messageContent);
      break;

    default:
      Logger.log("❌ 알 수 없는 targetDate 값: " + targetDate);
      return ContentService.createTextOutput("Unknown targetDate: " + targetDate);
  }

  return ContentService.createTextOutput(`data` + data);
}