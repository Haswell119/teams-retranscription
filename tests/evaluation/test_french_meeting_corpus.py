from pathlib import Path

import numpy as np
import soundfile as sf

from hansard.evaluation.prepare import (
    FRENCH_MEETING_RECIPES,
    MEETING_RECIPES,
    MLS_FRENCH_SPEAKERS,
    _collect_mls_speakers,
    synthesise_meeting,
)


def _corpus(root: Path, speakers: tuple[str, ...], per_speaker: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    lines = []
    for speaker in speakers:
        for index in range(per_speaker):
            identifier = f"{speaker}_1000_{index:06d}"
            sf.write(
                str(root / f"{identifier}.flac"),
                np.zeros(16_000, dtype=np.float32),
                16_000,
            )
            lines.append(f"{identifier}\tvoici la phrase numéro {index} du locuteur {speaker}")
    (root / "transcripts.txt").write_text("\n".join(lines), encoding="utf-8")


def test_every_french_recipe_has_a_distinct_speaker_bundle_available():
    required = max(recipe.speakers for recipe in FRENCH_MEETING_RECIPES)
    bundles = {name.split("_")[0] for name in MLS_FRENCH_SPEAKERS}
    assert len(bundles) >= required


def test_collect_mls_speakers_groups_by_speaker_identifier(tmp_path):
    _corpus(tmp_path, ("101", "202"), per_speaker=3)
    speakers = _collect_mls_speakers(tmp_path)
    assert sorted(speakers) == ["101", "202"]
    assert all(len(items) == 3 for items in speakers.values())
    path, text = speakers["101"][0]
    assert path.exists()
    assert text.startswith("voici la phrase")


def test_collect_mls_speakers_ignores_transcripts_without_audio(tmp_path):
    _corpus(tmp_path, ("101",), per_speaker=2)
    (tmp_path / "transcripts.txt").write_text("999_1000_000000\tphrase orpheline", encoding="utf-8")
    assert _collect_mls_speakers(tmp_path) == {}


def test_french_recipes_are_tagged_french_and_english_recipes_are_not():
    assert {recipe.language for recipe in FRENCH_MEETING_RECIPES} == {"fr"}
    assert {recipe.language for recipe in MEETING_RECIPES} == {"en"}
    assert not {recipe.name for recipe in FRENCH_MEETING_RECIPES} & {
        recipe.name for recipe in MEETING_RECIPES
    }


def test_synthesised_meeting_records_its_language(tmp_path):
    import json

    corpus = tmp_path / "corpus"
    _corpus(corpus, ("101", "202", "303"), per_speaker=4)
    recipe = FRENCH_MEETING_RECIPES[0]
    synthesise_meeting(recipe, _collect_mls_speakers(corpus), tmp_path)
    reference = json.loads((tmp_path / "synthetic" / f"{recipe.name}.ref.json").read_text(encoding="utf-8"))
    assert reference["language"] == "fr"
    assert len(reference["speakers"]) == recipe.speakers
    assert reference["segments"]
