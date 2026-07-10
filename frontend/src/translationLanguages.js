export function targetLanguagesFor(languages, sourceLanguage) {
  if (sourceLanguage === "auto") {
    return languages;
  }
  const source = languages.find((language) => language.code === sourceLanguage);
  if (!source || !Array.isArray(source.targets)) {
    return languages;
  }
  const targetCodes = new Set(source.targets);
  return languages.filter((language) => targetCodes.has(language.code));
}

export function hasTranslationTarget(languages, sourceLanguage, targetLanguage) {
  return targetLanguagesFor(languages, sourceLanguage).some(
    (language) => language.code === targetLanguage
  );
}
