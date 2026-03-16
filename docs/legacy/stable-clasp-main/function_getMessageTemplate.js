/**
 * Next.js API에서 메시지 템플릿 조회
 * @param {string} templateKey - 템플릿 키 (예: 'review_required_today')
 * @return {string|null} 템플릿 내용 또는 null
 */
function getMessageTemplate(templateKey) {
  const props = PropertiesService.getScriptProperties();
  const apiUrl = props.getProperty('NEXT_JS_API_URL');
  const apiKey = props.getProperty('NEXT_JS_API_KEY');

  if (!apiUrl || !apiKey) {
    Logger.log('❌ Error: API URL 또는 API Key가 설정되지 않았습니다.');
    Logger.log('Script Properties에서 NEXT_JS_API_URL과 NEXT_JS_API_KEY를 확인하세요.');
    return null;
  }

  const url = `${apiUrl}/api/message-templates?key=${templateKey}`;

  try {
    const response = UrlFetchApp.fetch(url, {
      method: 'GET',
      headers: {
        'x-api-key': apiKey
      },
      muteHttpExceptions: true
    });

    const statusCode = response.getResponseCode();
    const content = response.getContentText();

    if (statusCode === 200) {
      const data = JSON.parse(content);
      Logger.log(`✅ 템플릿 조회 성공: ${templateKey}`);
      return data.template.content;
    } else {
      Logger.log(`❌ Error ${statusCode}: ${content}`);
      return null;
    }
  } catch (error) {
    Logger.log(`❌ Request failed: ${error}`);
    return null;
  }
}
