function reviewRequiredYesterdayWrapper() {
  return reviewRequiredYesterday(getMessageByType("review_required_yesterday"));
}

function reviewRequiredTodayWrapper() {
  return reviewRequiredToday(getMessageByType("review_required_today"));
}

function invite1YesterdayWrapper() {
  return invite1Yesterday(getMessageByType("invite1_yesterday"));
}

function invite2YesterdayWrapper() {
  return invite2Yesterday(getMessageByType("invite2_yesterday"));
}

function addDoubleTodayWrapper() {
  return addDoubleToday(getMessageByType("add_double_today"));
}

function addTodayWrapper() {
  return addToday(getMessageByType("add_today"));
}

function add4TodayWrapper() {
  return add4Today(getMessageByType("add4_today"));
}

function add6TodayWrapper() {
  return add6Today(getMessageByType("add6_today"));
}

function party2TodayWrapper() {
  return party2Today(getMessageByType("party2_today"));
}

function party3TodayWrapper() {
  return party3Today();
}

function inviteGirlYesterdayWrapper() {
  return inviteGirlYesterday(getMessageByType("invite_girl_yesterday"));
}

function sexYesterdayWrapper() {
  return sexYesterday(getMessageByType("sex_yesterday"));
}

function invitePartyYesterdayWrapper() {
  return invitePartyYesterday(getMessageByType("invite_party_yesterday"));
}

function freeStayYesterdayWrapper() {
  return freeStayYesterday(getMessageByType("free_stay_yesterday"));
}

function UnstableYesterdayWrapper() {
  return UnstableYesterday(getMessageByType("unstable_yesterday"));
}

function activityTomorrowWrapper() {
    return activityTomorrow(getMessageByType("activity_tomorrow"));
}

/**
 * API에서 메시지 템플릿 조회
 * @param {string} templateKey - API 템플릿 키 (snake_case)
 * @return {string} 템플릿 내용
 */
function getMessageByType(templateKey) {
  const template = getMessageTemplate(templateKey);

  if (!template) {
    Logger.log(`⚠️ 템플릿을 찾을 수 없습니다: ${templateKey}`);
    return "";
  }

  return template;
}
