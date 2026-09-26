import json

import pytest

from playstore_scraper.input_parser import InvalidAppInputError, resolve_app_input, resolve_app_id


def test_package_id():
    assert resolve_app_id("com.oakever.meowdoku") == "com.oakever.meowdoku"


def test_url_with_params():
    url = "https://play.google.com/store/apps/details?id=com.oakever.meowdoku&hl=en&gl=US"
    result = resolve_app_input(url)
    assert result.app_id == "com.oakever.meowdoku"
    assert result.lang_from_url == "en"
    assert result.country_from_url == "us"


def test_market_url():
    result = resolve_app_input("market://details?id=com.oakever.meowdoku")
    assert result.app_id == "com.oakever.meowdoku"


def test_missing_id():
    with pytest.raises(InvalidAppInputError, match="id="):
        resolve_app_id("https://play.google.com/store/apps/details")


def test_invalid_package():
    with pytest.raises(InvalidAppInputError):
        resolve_app_id("not-a-package")


def test_quoted_input():
    assert resolve_app_id('"com.oakever.meowdoku"') == "com.oakever.meowdoku"
