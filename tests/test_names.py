"""Alternative names and profile file names."""

import pytest

from notarius.aliases import add_alias, load_aliases, remove_alias, resolve_display_name
from notarius.config import profile_base_name, validate_base_name
from notarius.profiles import list_profiles, rename_person


def test_resolve_alias_and_canonical_case(tmp_path):
    path = tmp_path / "apelidos.json"
    add_alias("Odete Prado", "Odete P.", path)
    add_alias("Odete Prado", "odete p.", path)  # duplicate, ignored
    aliases = load_aliases(path)
    assert aliases == {"Odete Prado": ["Odete P."]}
    assert resolve_display_name("ODETE P.", aliases) == "Odete Prado"
    assert resolve_display_name("odete prado", aliases) == "Odete Prado"
    assert resolve_display_name("Vicente", aliases) == "Vicente"
    assert remove_alias("Odete Prado", "Odete P.", path)
    assert load_aliases(path) == {}


def test_profile_names():
    assert profile_base_name("Odete Prado__zoom") == "Odete Prado"
    validate_base_name("Teodoro da Silva")
    for bad in ("", ".x", "a/b", "a__b", "x..y"):
        with pytest.raises(ValueError):
            validate_base_name(bad)


def test_rename_person_moves_variants_and_refuses_merges(tmp_path):
    for stem in ("Odete", "Odete__zoom", "Vicente"):
        (tmp_path / f"{stem}.npy").write_bytes(b"")
    assert rename_person("Odete", "Odete Prado", tmp_path) == 2
    assert list_profiles(tmp_path) == {
        "Odete Prado": ["Odete Prado", "Odete Prado__zoom"],
        "Vicente": ["Vicente"],
    }
    with pytest.raises(ValueError):
        rename_person("Vicente", "Odete Prado", tmp_path)
