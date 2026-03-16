function replaceMessage(template, variables) {
  let hasUndefined = false;

  const result = template.replace(/{{(.*?)}}/g, (match, p1) => {
    const key = p1.trim();
    if (variables[key] === undefined) {
      hasUndefined = true;
      return match; // 일단 치환은 안 하지만 플래그만 표시
    }
    return variables[key];
  });

  return hasUndefined ? null : result;
}