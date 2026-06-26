"""支持的目标语言。code=前端值/存库，label=界面显示，en=喂给模型的英文语言名。"""

LANGUAGES = [
    {"code": "zh-Hans", "label": "简体中文", "en": "Simplified Chinese"},
    {"code": "zh-Hant", "label": "繁體中文", "en": "Traditional Chinese"},
    {"code": "en", "label": "English", "en": "English"},
    {"code": "ja", "label": "日本語", "en": "Japanese"},
    {"code": "ko", "label": "한국어", "en": "Korean"},
    {"code": "fr", "label": "Français", "en": "French"},
    {"code": "de", "label": "Deutsch", "en": "German"},
    {"code": "es", "label": "Español", "en": "Spanish"},
    {"code": "pt", "label": "Português", "en": "Portuguese"},
    {"code": "it", "label": "Italiano", "en": "Italian"},
    {"code": "ru", "label": "Русский", "en": "Russian"},
    {"code": "ar", "label": "العربية", "en": "Arabic"},
    {"code": "th", "label": "ภาษาไทย", "en": "Thai"},
    {"code": "vi", "label": "Tiếng Việt", "en": "Vietnamese"},
    {"code": "id", "label": "Bahasa Indonesia", "en": "Indonesian"},
    {"code": "tr", "label": "Türkçe", "en": "Turkish"},
]

LANG_BY_CODE = {l["code"]: l for l in LANGUAGES}
DEFAULT_TARGET = "zh-Hans"


def lang_en(code: str) -> str:
    """code → 模型用的英文语言名；未知则回退简体中文。"""
    return LANG_BY_CODE.get(code, LANG_BY_CODE[DEFAULT_TARGET])["en"]


def lang_label(code: str) -> str:
    return LANG_BY_CODE.get(code, LANG_BY_CODE[DEFAULT_TARGET])["label"]
