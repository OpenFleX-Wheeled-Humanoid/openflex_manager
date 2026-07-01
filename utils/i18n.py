"""i18n loader backed by YAML config."""

from pathlib import Path
from typing import Any

import yaml


def _load_translations() -> dict[str, dict[str, Any]]:
    """
    加载所有语言的翻译文件

    从 config/translations/ 目录加载各语言的独立YAML文件：
    - zh_CN.yaml: 中文
    - en_US.yaml: 英文
    - ja_JP.yaml: 日文
    - ru_RU.yaml: 俄文

    返回:
        dict: {language_code: {key: value, ...}, ...}
    """
    translations_dir = Path(__file__).resolve().parent.parent / "config" / "translations"

    # 支持的语言列表
    supported_languages = ["zh_CN", "en_US", "ja_JP", "ru_RU"]

    translations = {}

    for lang in supported_languages:
        yaml_path = translations_dir / f"{lang}.yaml"

        if not yaml_path.exists():
            print(f"Warning: Translation file not found: {yaml_path}")
            translations[lang] = {}
            continue

        try:
            with yaml_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            if not isinstance(data, dict):
                raise ValueError(f"Invalid {lang}.yaml format: root must be a mapping")

            translations[lang] = data

        except Exception as e:
            print(f"Error loading {lang}.yaml: {e}")
            translations[lang] = {}

    return translations


TRANSLATIONS = _load_translations()


class Translator:
    def __init__(self, language: str = "zh_CN"):
        self.language = language

    def set_language(self, language: str) -> None:
        if language not in TRANSLATIONS:
            raise ValueError(f"Unsupported language: {language}")
        self.language = language

    def get(self, key: str, **kwargs: Any) -> Any:
        lang_map = TRANSLATIONS[self.language]
        text = lang_map.get(key, TRANSLATIONS["zh_CN"].get(key, key))
        if isinstance(text, str) and kwargs:
            return text.format(**kwargs)
        return text


translator = Translator()


def t(key: str, **kwargs: Any) -> Any:
    return translator.get(key, **kwargs)
