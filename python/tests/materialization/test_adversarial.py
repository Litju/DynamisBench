"""DB-3.3A adversarial source, path, authority and SUT-boundary tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from dynamisbench.domain.spec.realizations import AssetReference, RealizationDefinition
from dynamisbench.identity import semantic_sha256
from dynamisbench.materialization import (
    InputManifest,
    MaterializationError,
    MaterializationRefusalCode,
    MaterializationStore,
    materialize_inputs,
)
from dynamisbench.materialization.schema import ManifestLimits
from tests.materialization.conftest import ReferenceBundle
from tests.workspace.links import make_directory_link, require_directory_link


def _with_realization(
    bundle: ReferenceBundle,
    realization: RealizationDefinition,
) -> ReferenceBundle:
    """Return the same bundle with its RunSpec realization ref rebound to the edit."""
    updated = bundle.run_spec.model_copy(
        update={
            "realization": bundle.run_spec.realization.model_copy(
                update={"semantic_digest": semantic_sha256(realization)}
            )
        }
    )
    return ReferenceBundle(
        workspace=bundle.workspace,
        run_spec=updated,
        benchmark=bundle.benchmark,
        scenario=bundle.scenario,
        realization=realization,
        system_under_test=bundle.system_under_test,
        environment=bundle.environment,
    )


def _materialize(bundle: ReferenceBundle) -> object:
    return materialize_inputs(
        bundle.workspace,
        bundle.run_spec,
        benchmark=bundle.benchmark,
        scenario=bundle.scenario,
        realization=bundle.realization,
        system_under_test=bundle.system_under_test,
        environment=bundle.environment,
    )


def test_changed_source_bytes_are_refused_after_materialization(
    reference_bundle: ReferenceBundle,
) -> None:
    asset = reference_bundle.realization.assets[0]
    path = reference_bundle.workspace.source_root / asset.path
    path.write_bytes(b"changed source bytes")

    with pytest.raises(MaterializationError) as caught:
        _materialize(reference_bundle)

    assert caught.value.code is MaterializationRefusalCode.INPUT_SOURCE_CHANGED


def test_missing_source_asset_is_refused(reference_bundle: ReferenceBundle) -> None:
    asset = reference_bundle.realization.assets[0]
    (reference_bundle.workspace.source_root / asset.path).unlink()

    with pytest.raises(MaterializationError) as caught:
        _materialize(reference_bundle)

    assert caught.value.code is MaterializationRefusalCode.INPUT_SET_INCOMPLETE


def test_asset_without_a_declared_digest_is_refused(
    reference_bundle: ReferenceBundle,
) -> None:
    original = reference_bundle.realization.assets[0]
    realization = reference_bundle.realization.model_copy(
        update={"assets": (original.model_copy(update={"sha256": None}),)}
    )
    bundle = _with_realization(reference_bundle, realization)

    with pytest.raises(MaterializationError) as caught:
        _materialize(bundle)

    assert caught.value.code is MaterializationRefusalCode.INPUT_SET_INCOMPLETE


def test_source_symlink_is_refused_when_the_host_can_create_one(
    reference_bundle: ReferenceBundle,
    tmp_path: Path,
) -> None:
    asset = reference_bundle.realization.assets[0]
    source_path = reference_bundle.workspace.source_root / asset.path
    outside = tmp_path / "outside.xml"
    outside.write_bytes(b"outside bytes")
    source_path.unlink()
    try:
        os.symlink(outside, source_path)
    except OSError:
        pytest.skip("this host does not permit a file symlink for the refusal probe")

    with pytest.raises(MaterializationError) as caught:
        _materialize(reference_bundle)

    assert caught.value.code is MaterializationRefusalCode.INPUT_LINK_REFUSED


def test_source_directory_link_is_refused(
    reference_bundle: ReferenceBundle,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-directory"
    outside.mkdir()
    original_asset = reference_bundle.realization.assets[0]
    original_bytes = (reference_bundle.workspace.source_root / original_asset.path).read_bytes()
    (outside / "pendulum.xml").write_bytes(original_bytes)
    link = reference_bundle.workspace.source_root / "models" / "linked"
    mechanism = make_directory_link(link, outside)
    require_directory_link(mechanism, "a source directory-link escape is refused")

    original = reference_bundle.realization.assets[0]
    realization = reference_bundle.realization.model_copy(
        update={"assets": (original.model_copy(update={"path": "models/linked/pendulum.xml"}),)}
    )
    bundle = _with_realization(reference_bundle, realization)

    with pytest.raises(MaterializationError) as caught:
        _materialize(bundle)

    assert caught.value.code is MaterializationRefusalCode.INPUT_LINK_REFUSED


def test_source_hardlink_is_refused_when_the_host_can_create_one(
    reference_bundle: ReferenceBundle,
    tmp_path: Path,
) -> None:
    asset = reference_bundle.realization.assets[0]
    source_path = reference_bundle.workspace.source_root / asset.path
    outside = tmp_path / "hardlink-source.xml"
    outside.write_bytes(source_path.read_bytes())
    source_path.unlink()
    try:
        os.link(outside, source_path)
    except OSError:
        pytest.skip("this host does not permit a hardlink for the refusal probe")

    with pytest.raises(MaterializationError) as caught:
        _materialize(reference_bundle)

    assert caught.value.code is MaterializationRefusalCode.INPUT_LINK_REFUSED


def test_traversal_path_is_refused_even_when_the_model_is_constructed_raw(
    reference_bundle: ReferenceBundle,
) -> None:
    original = reference_bundle.realization.assets[0]
    raw = AssetReference.model_construct(
        asset_id=original.asset_id,
        path="../outside.xml",
        description=original.description,
        sha256=original.sha256,
    )
    realization = reference_bundle.realization.model_copy(update={"assets": (raw,)})
    bundle = _with_realization(reference_bundle, realization)

    with pytest.raises(MaterializationError) as caught:
        _materialize(bundle)

    assert caught.value.code is MaterializationRefusalCode.INPUT_PATH_REFUSED


@pytest.mark.parametrize(
    "path",
    (
        "models\\reference\\pendulum.xml",
        "models/reference/file.txt:stream",
        "models/reference/CON",
        "models/reference/foo.",
        "models/reference/a<b",
        "/".join(["a"] * 33),
    ),
)
def test_nonportable_materialized_paths_are_refused_before_publication(
    reference_bundle: ReferenceBundle,
    path: str,
) -> None:
    original = reference_bundle.realization.assets[0]
    raw = AssetReference.model_construct(
        asset_id=original.asset_id,
        path=path,
        description=original.description,
        sha256=original.sha256,
    )
    realization = reference_bundle.realization.model_copy(update={"assets": (raw,)})
    bundle = _with_realization(reference_bundle, realization)

    with pytest.raises(MaterializationError) as caught:
        _materialize(bundle)

    assert caught.value.code is MaterializationRefusalCode.INPUT_PATH_REFUSED
    assert not (reference_bundle.workspace.evidence_root / "cache" / "inputs" / "objects").exists()


def test_asset_count_is_bounded_before_any_publication(
    reference_bundle: ReferenceBundle,
) -> None:
    digest = hashlib.sha256(b"").hexdigest()
    assets = tuple(
        AssetReference(
            asset_id=f"asset-{index}",
            path=f"models/reference/asset-{index}.xml",
            description="bounded asset",
            sha256=digest,
        )
        for index in range(65)
    )
    realization = reference_bundle.realization.model_copy(update={"assets": assets})
    bundle = _with_realization(reference_bundle, realization)

    with pytest.raises(MaterializationError) as caught:
        _materialize(bundle)

    assert caught.value.code is MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED
    assert not (reference_bundle.workspace.evidence_root / "cache" / "inputs" / "objects").exists()


def test_domain_path_bound_is_256_characters() -> None:
    with pytest.raises(ValidationError):
        AssetReference(
            asset_id="asset",
            path="a" * 257,
            description="path too long",
            sha256="0" * 64,
        )


def test_manifest_limits_cannot_be_widened_by_a_reader() -> None:
    with pytest.raises(ValidationError):
        ManifestLimits(max_assets=1)


def test_manifest_object_key_cannot_name_another_digest(
    reference_bundle: ReferenceBundle,
) -> None:
    result = reference_bundle.materialize()
    asset = result.manifest.assets[0]
    object_key = "sha256/" + ("0" * 64)
    corrupted = asset.model_copy(update={"object": object_key})

    with pytest.raises(ValidationError):
        InputManifest(
            execution_refs=result.manifest.execution_refs,
            definitions=result.manifest.definitions,
            assets=(corrupted,),
            limits=ManifestLimits(),
        )


def test_store_root_is_not_a_reference_in_the_manifest(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
) -> None:
    result = reference_bundle.materialize()
    text = result.manifest.model_dump_json()
    assert str(materialization_store.root) not in text
    assert str(reference_bundle.workspace.source_root) not in text
    assert str(reference_bundle.workspace.evidence_root) not in text
