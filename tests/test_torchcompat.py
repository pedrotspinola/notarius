"""The checkpoint-loading patch must survive nesting.

Setup patches torch.load for its whole run and loads the voice model, which
patches again inside.  The inner block used to restore the originals on
exit, so the diarization check that followed failed on Windows with
"Weights only load failed".
"""

import torch

from notarius.torchcompat import (
    _original_serial_load,
    _original_torch_load,
    trusted_checkpoints,
)


def test_nested_blocks_keep_the_patch_until_the_outer_one_ends():
    assert torch.load is _original_torch_load
    with trusted_checkpoints():
        with trusted_checkpoints():
            assert torch.load is not _original_torch_load
        assert torch.load is not _original_torch_load  # still patched
        assert torch.serialization.load is not _original_serial_load
    assert torch.load is _original_torch_load
    assert torch.serialization.load is _original_serial_load


def test_patch_is_restored_after_an_error():
    try:
        with trusted_checkpoints():
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert torch.load is _original_torch_load


def test_patched_load_forces_full_unpickling(tmp_path):
    path = tmp_path / "x.pt"
    torch.save({"version": torch.torch_version.TorchVersion("2.0")}, path)
    with trusted_checkpoints():
        assert str(torch.load(path)["version"]) == "2.0"
        assert str(torch.load(path, weights_only=None)["version"]) == "2.0"
