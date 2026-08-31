import { createContext, useContext } from "react";
import type { LanguagePreference } from "../desktop-api";
import { en } from "./locales/en";
import { zhCN } from "./locales/zh-CN";

export type TranslationKey = keyof typeof en;
export const resources = { en, "zh-CN": zhCN } as const satisfies Record<LanguagePreference, Record<TranslationKey, string>>;
export function translate(language: LanguagePreference, key: TranslationKey): string { return resources[language][key]; }
const LanguageContext = createContext<LanguagePreference>("zh-CN");
export const LanguageProvider = LanguageContext.Provider;
export function useTranslation() { const language = useContext(LanguageContext); return { language, t: (key: TranslationKey) => translate(language, key) }; }
