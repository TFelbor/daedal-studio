import pytest
from pythonsrc.operators.printer_factory import PrinterFactory
from pythonsrc.operators.moonraker_operator import MoonrakerOperator
from pythonsrc.operators.octoprint_operator import OctoPrintOperator

def test_printer_factory_moonraker():
    operator = PrinterFactory.create("klipper", "http://localhost:7125", "moonraker_key")
    assert isinstance(operator, MoonrakerOperator)
    assert operator.base_url == "http://localhost:7125"
    assert operator.api_key == "moonraker_key"

def test_printer_factory_octoprint():
    operator = PrinterFactory.create("octoprint", "http://localhost:5001", "octoprint_key")
    assert isinstance(operator, OctoPrintOperator)
    assert operator.base_url == "http://localhost:5001"
    assert operator.api_key == "octoprint_key"

def test_printer_factory_bambu():
    from pythonsrc.operators.bambu_operator import BambuOperator
    op = PrinterFactory.create("bambu", "http://localhost:1234", "bambu_key")
    assert isinstance(op, BambuOperator)
    assert op.base_url == "http://localhost:1234"
    assert op.api_key == "bambu_key"

def test_printer_factory_unknown():
    with pytest.raises(ValueError, match="Unknown firmware type"):
        PrinterFactory.create("unknown", "http://localhost:1234", "key")
