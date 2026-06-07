import pytest
import responses
import requests
import json
from pythonsrc.operators.moonraker_operator import MoonrakerOperator, PrinterConnectionError

@pytest.fixture
def operator():
    return MoonrakerOperator(base_url="http://localhost:7125", api_key="test_key")

@responses.activate
def test_connect_success(operator):
    responses.add(
        responses.GET,
        "http://localhost:7125/printer/info",
        json={"result": {"state": "ready"}},
        status=200
    )
    assert operator.connect() is True
    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["X-Api-Key"] == "test_key"

@responses.activate
def test_connect_failure(operator):
    responses.add(
        responses.GET,
        "http://localhost:7125/printer/info",
        status=500
    )
    with pytest.raises(PrinterConnectionError):
        operator.connect()

@responses.activate
def test_retry_on_connection_error(operator):
    responses.add(
        responses.GET,
        "http://localhost:7125/printer/info",
        body=requests.exceptions.ConnectionError("Connection Refused")
    )
    responses.add(
        responses.GET,
        "http://localhost:7125/printer/info",
        json={"result": {"state": "ready"}},
        status=200
    )
    assert operator.connect() is True
    assert len(responses.calls) == 2

@responses.activate
def test_retry_fails(operator):
    responses.add(
        responses.GET,
        "http://localhost:7125/printer/info",
        body=requests.exceptions.ConnectionError("Connection Refused")
    )
    responses.add(
        responses.GET,
        "http://localhost:7125/printer/info",
        body=requests.exceptions.ConnectionError("Connection Refused")
    )
    with pytest.raises(PrinterConnectionError):
        operator.connect()
    assert len(responses.calls) == 2

@responses.activate
def test_upload_file(operator, tmp_path):
    # Create a temporary file to upload
    test_file = tmp_path / "test.gcode"
    test_file.write_text("G28\nG1 Z10")

    responses.add(
        responses.POST,
        "http://localhost:7125/server/files/upload",
        json={"result": {"item": {"path": "test.gcode"}}},
        status=200
    )
    assert operator.upload_file(str(test_file), "test.gcode") is True
    assert len(responses.calls) == 1
    req = responses.calls[0].request
    assert b"gcodes" in req.body

@responses.activate
def test_start_print(operator):
    responses.add(
        responses.POST,
        "http://localhost:7125/printer/print/start",
        json={"result": "ok"},
        status=200
    )
    assert operator.start_print("test.gcode") is True
    assert len(responses.calls) == 1
    req_body = json.loads(responses.calls[0].request.body)
    assert req_body["filename"] == "test.gcode"

@responses.activate
def test_cancel_print(operator):
    responses.add(responses.POST, "http://localhost:7125/printer/print/cancel", json={"result": "ok"}, status=200)
    assert operator.cancel_print() is True

@responses.activate
def test_pause_print(operator):
    responses.add(responses.POST, "http://localhost:7125/printer/print/pause", json={"result": "ok"}, status=200)
    assert operator.pause_print() is True

@responses.activate
def test_resume_print(operator):
    responses.add(responses.POST, "http://localhost:7125/printer/print/resume", json={"result": "ok"}, status=200)
    assert operator.resume_print() is True

@responses.activate
def test_get_printer_state(operator):
    mock_response = {
        "result": {
            "status": {
                "print_stats": {
                    "state": "printing",
                    "filename": "test.gcode",
                    "info": {"progress": 0.45}
                },
                "toolhead": {
                    "position": [10.0, 20.0, 5.5, 0.0]
                },
                "heater_bed": {
                    "temperature": 60.1,
                    "target": 60.0
                },
                "extruder": {
                    "temperature": 210.5,
                    "target": 210.0
                }
            }
        }
    }
    
    responses.add(
        responses.GET,
        "http://localhost:7125/printer/objects/query?print_stats&toolhead&heater_bed&extruder",
        json=mock_response,
        status=200
    )
    
    state = operator.get_printer_state()
    assert state["state"] == "printing"
    assert state["z_height"] == 5.5
    assert state["hotend_actual"] == 210.5
    assert state["hotend_target"] == 210.0
    assert state["bed_actual"] == 60.1
    assert state["bed_target"] == 60.0
    assert state["gcode_file"] == "test.gcode"
    assert state["progress"] == 0.45
