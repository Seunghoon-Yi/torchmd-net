import pytest
from pytest import mark
import pickle
from os.path import exists, dirname, join
import torch
from torch.testing import assert_allclose
import pytorch_lightning as pl
from torchmdnet import models
from torchmdnet.models.model import create_model
from torchmdnet.models import output_modules

from utils import load_example_args, create_example_batch


@mark.parametrize("model_name", models.__all__)
@mark.parametrize("use_batch", [True, False])
def test_forward(model_name, use_batch):
    z, pos, batch = create_example_batch()
    model = create_model(load_example_args(model_name, prior_model=None))
    if use_batch:
        model(z, pos, batch)
    else:
        model(z, pos)


@mark.parametrize("model_name", models.__all__)
@mark.parametrize("output_model", output_modules.__all__)
def test_forward_output_modules(model_name, output_model):
    z, pos, batch = create_example_batch()
    args = load_example_args(model_name, remove_prior=True, output_model=output_model)
    model = create_model(args)
    model(z, pos, batch=batch)


@mark.parametrize("model_name", models.__all__)
@mark.parametrize("derivative", [True, False])
def test_forward_torchscript(model_name, derivative):
    if model_name == "equivariant-transformer":
        # TODO: also test equivariant Transformer after the release of
        # https://github.com/rusty1s/pytorch_geometric/commit/673f94729b6a520b994699da5aa8dd3d1a1f670b
        pytest.skip("currently only works on the torch-geometric main branch")

    z, pos, batch = create_example_batch()
    model = torch.jit.script(
        create_model(
            load_example_args(model_name, remove_prior=True, derivative=derivative)
        )
    )
    model(z, pos, batch=batch)


@mark.parametrize("model_name", models.__all__)
@mark.parametrize("derivative", [True, False])
@mark.parametrize("call_with_batch", [True, False])
def test_forward_trace(model_name, derivative, call_with_batch):
    z, pos, batch = create_example_batch()
    model = create_model(
        load_example_args(model_name, remove_prior=True, derivative=derivative)
    )

    if call_with_batch:
        y_before, dy_before = model(z, pos, batch)
    else:
        y_before, dy_before = model(z, pos)

    model.network = torch.jit.trace(model.network, [z, pos, batch])

    if call_with_batch:
        y_after, dy_after = model(z, pos, batch)
    else:
        y_after, dy_after = model(z, pos)

    assert_allclose(y_before, y_after), "Prediction changed after torch.jit.trace."
    if derivative:
        assert_allclose(
            dy_before, dy_after
        ), "Gradient of prediction changed after torch.jit.trace."


@mark.parametrize("model_name", models.__all__)
def test_seed(model_name):
    args = load_example_args(model_name, remove_prior=True)
    pl.seed_everything(1234)
    m1 = create_model(args)
    pl.seed_everything(1234)
    m2 = create_model(args)

    for p1, p2 in zip(m1.parameters(), m2.parameters()):
        assert (p1 == p2).all(), "Parameters don't match although using the same seed."


@mark.parametrize("model_name", models.__all__)
@mark.parametrize(
    "output_model", output_modules.__all__,
)
def test_forward_output(model_name, output_model, overwrite_reference=False):
    pl.seed_everything(1234)

    # create model and sample batch
    derivative = output_model in ["Scalar", "EquivariantScalar"]
    args = load_example_args(
        model_name, remove_prior=True, output_model=output_model, derivative=derivative,
    )
    model = create_model(args)
    z, pos, batch = create_example_batch(n_atoms=5)

    # run step
    pred, deriv = model(z, pos, batch)

    # load reference outputs
    expected_path = join(dirname(__file__), "expected.pkl")
    assert exists(expected_path), "Couldn't locate reference outputs."
    with open(expected_path, "rb") as f:
        expected = pickle.load(f)

    if overwrite_reference:
        # this overwrites the previous reference outputs and shouldn't be executed during testing
        if model_name in expected:
            expected[model_name][output_model] = dict(pred=pred, deriv=deriv)
        else:
            expected[model_name] = {output_model: dict(pred=pred, deriv=deriv)}

        with open(expected_path, "wb") as f:
            pickle.dump(expected, f)
        assert (
            False
        ), f"Set new reference outputs for {model_name} with output model {output_model}."

    # compare actual ouput with reference
    assert_allclose(pred, expected[model_name][output_model]["pred"])
    if derivative:
        assert_allclose(deriv, expected[model_name][output_model]["deriv"])
