"""Voice profiles on disk: enroll, load, list, delete.

Each profile is one ``.npy`` embedding in the profiles folder, named after
the person (``Odete Prado.npy``) or a variant of them recorded under other
conditions (``Odete Prado__zoom.npy``).  Matching groups variants by person
and takes the best score across them.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from notarius.config import (
    EMBEDDING_DIM,
    SpeakerProfile,
    profile_base_name,
    validate_profile_name,
)

log = logging.getLogger(__name__)


def enroll_from_files(
    name: str, audio_paths: list[str | Path], profiles_dir: Path, device: str = "cpu"
) -> SpeakerProfile:
    """Create (or overwrite) a profile from one or more audio files.

    One embedding per file; the profile is their average.
    """
    if not audio_paths:
        raise ValueError("audio_paths must not be empty")
    for p in audio_paths:
        if not Path(p).is_file():
            raise FileNotFoundError(f"Audio file not found: {p}")

    from notarius.embedding import EmbeddingModel

    with EmbeddingModel(device) as emb:
        embeddings = [emb.extract(p) for p in audio_paths]
    profile = SpeakerProfile(name=name, embedding=np.mean(embeddings, axis=0))
    profile.save(profiles_dir)
    return profile


def load_all_profiles(profiles_dir: Path) -> list[SpeakerProfile]:
    """Load every profile in *profiles_dir* (non-recursive).

    Files whose embedding size is not ``EMBEDDING_DIM`` are skipped with a
    warning: a profile from another embedding model must never be compared.
    """
    if not profiles_dir.is_dir():
        return []
    profiles: list[SpeakerProfile] = []
    for npy_path in sorted(profiles_dir.glob("*.npy")):
        profile = SpeakerProfile.load(npy_path)
        if profile.embedding.shape != (EMBEDDING_DIM,):
            log.warning(
                "Skipping %s: embedding shape %s, expected (%d,)",
                npy_path, profile.embedding.shape, EMBEDDING_DIM,
            )
            continue
        profiles.append(profile)
    return profiles


def group_profiles_by_person(
    profiles: list[SpeakerProfile],
) -> dict[str, list[SpeakerProfile]]:
    """``{person: [profile, variant, ...]}``."""
    groups: dict[str, list[SpeakerProfile]] = {}
    for p in profiles:
        groups.setdefault(profile_base_name(p.name), []).append(p)
    return groups


def list_profiles(profiles_dir: Path) -> dict[str, list[str]]:
    """``{person: [profile names, sorted]}`` without loading embeddings."""
    groups: dict[str, list[str]] = {}
    if profiles_dir.is_dir():
        for p in sorted(profiles_dir.glob("*.npy")):
            groups.setdefault(profile_base_name(p.stem), []).append(p.stem)
    return groups


def delete_profile(name: str, profiles_dir: Path) -> bool:
    """Delete one profile file (exact name).  True if it existed."""
    validate_profile_name(name)
    path = profiles_dir / f"{name}.npy"
    if path.is_file():
        path.unlink()
        return True
    return False


def delete_person(name: str, profiles_dir: Path) -> int:
    """Delete a person's profile and all its variants.  Returns the count."""
    validate_profile_name(name)
    count = 0
    if profiles_dir.is_dir():
        for npy_path in sorted(profiles_dir.glob("*.npy")):
            if profile_base_name(npy_path.stem) == name:
                npy_path.unlink()
                count += 1
    return count


def rename_person(old: str, new: str, profiles_dir: Path) -> int:
    """Rename a person's profile and variants.  Returns the count renamed.

    Refuses when the new name already has profiles, so two people are never
    merged by accident.
    """
    validate_profile_name(old)
    validate_profile_name(new)
    if list_profiles(profiles_dir).get(new):
        raise ValueError(f"There are already voice profiles named {new!r}.")
    count = 0
    for npy_path in sorted(profiles_dir.glob("*.npy")):
        if profile_base_name(npy_path.stem) == old:
            suffix = npy_path.stem[len(old):]
            npy_path.rename(profiles_dir / f"{new}{suffix}.npy")
            count += 1
    return count
