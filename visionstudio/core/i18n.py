"""Two-language text (Vietnamese source, English translation). Qt-free.

Vietnamese is the source language: code writes t("Chuỗi tiếng Việt"). In English mode t() looks the
string up in lang_en.EN and falls back to the Vietnamese text when there is no translation.
For text with values, translate the template and format afterwards:  t("Đã xóa {0} ảnh").format(n)
"""
from __future__ import annotations

LANGUAGES = {"vi": "Tiếng Việt", "en": "English"}
_lang = "vi"


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGUAGES else "vi"


def language() -> str:
    return _lang


def t(text: str) -> str:
    if _lang == "vi" or not text:
        return text
    from .lang_en import EN
    return EN.get(text, text)