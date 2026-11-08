"""Brand, naming and identifier-stability tests (v0.11.0 rebrand).

The member-visible name is "Club Roulez Électrique". The DOMAIN, the folder
name and every entity unique_id must NOT change: doing so would orphan every
existing install's entities, history and automations.
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "roulezelectrique"
BRAND = COMPONENT / "brand"
NAME = "Club Roulez Électrique"
BARE = re.compile(r"(?<!Club )Roulez Électrique")


def _strings(node):
    """Yield every string value of a JSON document."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", data[16:24])


JSON_FILES = [
    COMPONENT / "strings.json",
    COMPONENT / "translations" / "fr.json",
    COMPONENT / "translations" / "en.json",
    COMPONENT / "manifest.json",
    ROOT / "hacs.json",
]


def test_names_in_manifest_and_hacs():
    assert json.loads((COMPONENT / "manifest.json").read_text())["name"] == NAME
    assert json.loads((ROOT / "hacs.json").read_text())["name"] == NAME


@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.name if p.parent.name != "translations" else f"translations/{p.name}")
def test_no_bare_brand_name_in_user_visible_strings(path):
    for value in _strings(json.loads(path.read_text(encoding="utf-8"))):
        assert not BARE.search(value), f"{path.name}: bare brand name in {value!r}"


@pytest.mark.parametrize("path", JSON_FILES[:3], ids=lambda p: p.parent.name + "/" + p.name)
def test_translations_use_full_name_somewhere(path):
    assert any(NAME in s for s in _strings(json.loads(path.read_text(encoding="utf-8"))))


def test_no_bare_brand_name_in_python_and_readmes():
    files = [*COMPONENT.glob("*.py"), ROOT / "README.md", ROOT / "README-FR.md", ROOT / "README-EN.md"]
    for path in files:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not BARE.search(line), f"{path.name}:{n}: bare brand name"


def test_domain_and_folder_unchanged():
    from custom_components.roulezelectrique.const import DOMAIN

    assert DOMAIN == "roulezelectrique"
    assert json.loads((COMPONENT / "manifest.json").read_text())["domain"] == "roulezelectrique"
    assert COMPONENT.name == "roulezelectrique"


def test_account_device_name_and_identifier():
    from custom_components.roulezelectrique.const import DOMAIN
    from custom_components.roulezelectrique.sensor import RoulezElectriqueAccountSensor

    source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    assert f'name="{NAME}"' in source
    assert 'identifiers={(DOMAIN, "account")}' in source
    assert DOMAIN == "roulezelectrique"
    assert RoulezElectriqueAccountSensor  # class name kept


def test_unique_id_formats_are_pinned():
    """Every `_attr_unique_id` assignment in the integration, verbatim."""
    found = set()
    for path in COMPONENT.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "_attr_unique_id =" in line:
                found.add((path.name, line.split("=", 1)[1].strip()))
    assert found == {
        ("binary_sensor.py", 'f"{charger_id}_{description.key}"'),
        ("button.py", 'f"{charger_id}_refresh"'),
        ("button.py", 'f"{charger_id}_reboot"'),
        ("switch.py", 'f"{charger_id}_charge_switch"'),
        ("switch.py", 'f"{charger_id}_lock_switch"'),
        ("switch.py", 'f"{charger_id}_plug_and_charge"'),
        ("number.py", 'f"{charger_id}_max_current"'),
        ("number.py", 'f"{charger_id}_evduty_max_current"'),
        ("select.py", 'f"{charger_id}_time_zone"'),
        ("sensor.py", 'f"{charger_id}_{description.key}"'),
        ("sensor.py", "description.key"),
    }


def test_icon_is_square_and_sized():
    assert _png_size(BRAND / "icon.png") == (256, 256)
    assert _png_size(BRAND / "icon@2x.png") == (512, 512)


@pytest.mark.parametrize(
    "name,short",
    [("logo.png", 128), ("logo@2x.png", 256), ("dark_logo.png", 128), ("dark_logo@2x.png", 256)],
)
def test_logos_are_landscape_with_brand_size(name, short):
    width, height = _png_size(BRAND / name)
    assert height == short
    assert width > height
