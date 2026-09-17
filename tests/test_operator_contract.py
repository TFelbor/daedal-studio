"""Contract tests: every operator must be callable through BasePrinterOperator alone.

`pipeline.py` talks to printers only through the abstract base class, so any method
whose *required* call shape differs between implementations is a latent TypeError on
whichever firmware the developer did not happen to test with.
"""

import inspect

import pytest

from pythonsrc.operators.bambu_operator import BambuOperator
from pythonsrc.operators.base import BasePrinterOperator
from pythonsrc.operators.moonraker_operator import MoonrakerOperator
from pythonsrc.operators.octoprint_operator import OctoPrintOperator

OPERATORS = [MoonrakerOperator, OctoPrintOperator, BambuOperator]

ABSTRACT_METHODS = [
    "connect",
    "upload_file",
    "start_print",
    "cancel_print",
    "pause_print",
    "resume_print",
    "get_printer_state",
]


@pytest.mark.parametrize("operator_cls", OPERATORS)
@pytest.mark.parametrize("method_name", ABSTRACT_METHODS)
def test_operator_accepts_base_call_signature(operator_cls, method_name):
    """Each implementation must accept the base signature's parameters, unchanged."""
    base_params = list(inspect.signature(getattr(BasePrinterOperator, method_name)).parameters)
    impl_params = list(inspect.signature(getattr(operator_cls, method_name)).parameters)

    assert impl_params[: len(base_params)] == base_params, (
        f"{operator_cls.__name__}.{method_name} does not accept the "
        f"BasePrinterOperator call shape {base_params}"
    )


@pytest.mark.parametrize("operator_cls", OPERATORS)
def test_extra_upload_file_params_are_optional(operator_cls):
    """Extra params beyond the ABC must have defaults, so base-shape calls still work."""
    params = inspect.signature(operator_cls.upload_file).parameters
    base_params = inspect.signature(BasePrinterOperator.upload_file).parameters
    extras = [p for name, p in params.items() if name not in base_params]

    for param in extras:
        assert param.default is not inspect.Parameter.empty, (
            f"{operator_cls.__name__}.upload_file has required extra param "
            f"'{param.name}' — pipeline.py cannot supply it for other firmwares"
        )


def test_pipeline_calls_upload_file_with_base_signature_only():
    """Guard the specific regression: pipeline.py must not pass OctoPrint-only kwargs."""
    import pathlib

    source = pathlib.Path("pythonsrc/pipeline.py").read_text()
    assert "start_print=args.start_print" not in source, (
        "pipeline.py passes OctoPrint's upload-and-print kwarg through the abstract "
        "interface; other firmwares raise TypeError"
    )


@pytest.mark.parametrize("operator_cls", OPERATORS)
@pytest.mark.parametrize("method_name", ABSTRACT_METHODS)
def test_no_operator_method_is_still_a_stub(operator_cls, method_name):
    """Signature checks pass for a body that raises. This is the other half.

    #73 names it directly: "a `NotImplementedError` body passes today, so the contract
    test must grow behaviour assertions for Bambu". Every method of `BambuOperator` was
    such a body, and the contract suite was green the whole time — an operator that
    could be constructed, called with the right arguments, and did nothing.

    Source inspection rather than a call, because calling means a printer. What the
    method actually *does* is held by `tests/test_bambu_operator.py` against a fake
    broker, and on real hardware by the checklist in #73's pull request.
    """
    implementation = getattr(operator_cls, method_name)

    assert implementation is not getattr(BasePrinterOperator, method_name), (
        f"{operator_cls.__name__} does not implement {method_name}"
    )
    assert "NotImplementedError" not in inspect.getsource(implementation), (
        f"{operator_cls.__name__}.{method_name} is still a stub"
    )


@pytest.mark.parametrize("operator_cls", OPERATORS)
def test_every_operator_says_which_firmware_it_is(operator_cls):
    """`firmware` is what replaced `isinstance` in the detector and the collector
    choice (#74). An operator that does not declare one is read as an unknown firmware
    — no collector, and a state nothing can normalise."""
    assert operator_cls.firmware, f"{operator_cls.__name__} declares no firmware"
    assert operator_cls.firmware == operator_cls.firmware.lower()
