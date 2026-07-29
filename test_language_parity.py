"""Regression coverage for WiM/Lavrentiy language parity."""

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
API = ROOT / "wim" / "api"
sys.path.insert(0, str(API))

import prompt_builder as PB  # noqa: E402


PIPELINE_LANGUAGES = {
    "en", "es", "ru", "pt", "fr", "ar", "de", "hi", "it", "ja", "ko", "zh",
}
TRANSLATED_INTERFACES = {"en", "es", "ru", "pt", "fr"}
PIPELINE_ONLY = {"ar", "de", "hi", "it", "ja", "ko", "zh"}


def test_dashboard_exposes_all_pipeline_languages_in_one_picker():
    dashboard = (ROOT / "dashboard.html").read_text(encoding="utf-8")
    picker = re.search(
        r'<button[^>]+id="ui-language-select".*?</button>',
        dashboard,
        re.DOTALL,
    )
    assert picker, "Missing interface-language picker"
    menu = re.search(
        r'<div[^>]+id="ui-language-menu".*?</div>',
        dashboard,
        re.DOTALL,
    )
    assert menu, "Missing full language menu"
    options = set(re.findall(r'data-lang="([a-z]{2})"', menu.group(0)))
    assert options == PIPELINE_LANGUAGES
    names = dict(re.findall(
        r'data-lang="([a-z]{2})" data-name="([^"]+)"',
        menu.group(0),
    ))
    assert set(names) == PIPELINE_LANGUAGES
    assert all(name in menu.group(0) for name in names.values())
    assert "lang-option-tooltip" in menu.group(0)
    assert (
        "const APP_LANGUAGES=['en','es','ru','pt','fr','ar','de','hi','it','ja','ko','zh'];"
        in dashboard
    )
    assert "const UI_LANGUAGES=['en','es','ru','pt','fr'];" in dashboard
    assert "UI_LANGUAGES.includes(lang)?lang:'en'" in dashboard
    assert "body:JSON.stringify({language:lang})" in dashboard


def test_translated_interfaces_are_complete_and_markup_safe():
    pack = json.loads(
        (ROOT / "lang_packs" / "dashboard_i18n_multilang.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(pack["_meta"]["interface_locales"]) == TRANSLATED_INTERFACES
    assert set(pack["_meta"]["pipeline_only_locales"]) == PIPELINE_ONLY

    markup = re.compile(
        r"<[^>]+>|&(?:[A-Za-z][A-Za-z0-9]+|#[0-9]+|#x[0-9A-Fa-f]+);"
    )
    for key, entry in pack.items():
        if key == "_meta":
            continue
        for language in TRANSLATED_INTERFACES:
            value = entry.get(language)
            assert isinstance(value, str) and value.strip(), (key, language)
            assert not value.startswith(f"[{language}]"), (key, language)
            if language in {"es", "fr", "pt"}:
                assert markup.findall(value) == markup.findall(entry["en"]), (
                    key,
                    language,
                    "translated markup drifted",
                )


def test_translation_pack_matches_current_dashboard_english():
    dashboard = (ROOT / "dashboard.html").read_text(encoding="utf-8")
    start = dashboard.index("const I18N=") + len("const I18N=")
    end = dashboard.index("\n};", start) + 2
    javascript = dashboard[start:end]
    node = (
        "const fs=require('fs'),vm=require('vm');"
        "const source=fs.readFileSync(0,'utf8');"
        "const data=vm.runInNewContext('('+source+')');"
        "process.stdout.write(JSON.stringify(data));"
    )
    current = json.loads(
        subprocess.check_output(
            ["node", "-e", node],
            input=javascript,
            text=True,
            encoding="utf-8",
        )
    )
    pack = json.loads(
        (ROOT / "lang_packs" / "dashboard_i18n_multilang.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(current) == set(pack) - {"_meta"}
    current_english = {key: value["en"] for key, value in current.items()}
    packed_english = {
        key: value["en"] for key, value in pack.items() if key != "_meta"
    }
    mismatches = {
        key: (current_english.get(key), packed_english.get(key))
        for key in current_english.keys() | packed_english.keys()
        if current_english.get(key) != packed_english.get(key)
    }
    assert not mismatches, mismatches


def test_all_pipeline_language_packs_are_present_in_both_runtimes():
    for code in PIPELINE_LANGUAGES - {"en"}:
        desktop_path = ROOT / "lang_packs" / f"{code}.json"
        cloud_path = API / "lang_packs" / f"{code}.json"
        assert desktop_path.exists(), code
        assert cloud_path.exists(), code
        desktop = json.loads(desktop_path.read_text(encoding="utf-8"))
        cloud = json.loads(cloud_path.read_text(encoding="utf-8"))
        assert desktop["language_code"] == code
        assert cloud == desktop


def test_russian_pack_matches_latest_wim_rules():
    pack = json.loads(
        (ROOT / "lang_packs" / "ru.json").read_text(encoding="utf-8")
    )
    onsets = {
        item["onset"]: item["difficulty_weight"]
        for item in pack["hard_onsets"]["data"]
    }
    assert onsets == {
        "/p/": 0.85,
        "/t/": 0.82,
        "/k/": 0.80,
        "/str/": 0.78,
        "/vz/": 0.74,
    }
    assert pack["script_unicode_ranges"] == [[32, 126], [1024, 1279]]
    assert {"всё всё", "давай давай"} <= set(pack["natural_repeats"])
    assert {"рас-", "недо-", "анти-"} <= set(pack["productive_prefixes"])


def test_russian_layer4_prompt_uses_russian_specific_guidance():
    prompt = PB.build_prompt(
        "Я-я-я хотел сказать про встречу",
        layer=4,
        language_code="ru",
    )
    expected = (
        "DISFLUENCY EXAMPLES (Russian)",
        "CLUSTER CORRUPTION",
        "Russian ты/Вы register",
        "Russian is stress-timed",
        "no Russian-specific published weights located",
        "Сссспасибо",
    )
    for marker in expected:
        assert marker in prompt


def test_lavrentiy_declares_the_same_twelve_spoken_languages():
    source = (ROOT / "lavrentiy.py").read_text(encoding="utf-8")
    block = re.search(r"DICTATION_LANGUAGES = \{(.*?)\}", source, re.DOTALL)
    assert block
    codes = set(re.findall(r'"([a-z]{2})"', block.group(1)))
    assert codes == PIPELINE_LANGUAGES


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
    print(f"\n{len(tests)} language parity tests passed.")
