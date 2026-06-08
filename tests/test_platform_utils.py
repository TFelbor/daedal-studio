import sys
import pytest
from unittest.mock import patch, MagicMock

from pythonsrc.platform_utils import get_execution_strategy, get_phase1_command, _docker_has_nvidia_runtime

@pytest.fixture
def mock_torch_mps():
    with patch.dict(sys.modules, {'torch': MagicMock()}):
        import torch
        torch.backends.mps.is_available.return_value = True
        yield torch

@pytest.fixture
def mock_torch_no_mps():
    with patch.dict(sys.modules, {'torch': MagicMock()}):
        import torch
        torch.backends.mps.is_available.return_value = False
        yield torch

def test_mps_native(mock_torch_mps):
    with patch("sys.platform", "darwin"):
        assert get_execution_strategy() == "mps_native"

def test_nvidia_docker():
    with patch("sys.platform", "linux"), \
         patch("shutil.which", return_value="/usr/bin/nvidia-smi"), \
         patch("subprocess.run") as mock_run:
        
        mock_result = MagicMock()
        mock_result.stdout = "nvidia runc"
        mock_run.return_value = mock_result
        
        assert get_execution_strategy() == "nvidia_docker"

def test_cpu_docker_fallback_linux_no_nvidia_smi():
    with patch("sys.platform", "linux"), \
         patch("shutil.which", return_value=None):
        assert get_execution_strategy() == "cpu_docker"

def test_cpu_docker_fallback_linux_no_docker_runtime():
    with patch("sys.platform", "linux"), \
         patch("shutil.which", return_value="/usr/bin/nvidia-smi"), \
         patch("subprocess.run") as mock_run:
        
        mock_result = MagicMock()
        mock_result.stdout = "runc"
        mock_run.return_value = mock_result
        
        assert get_execution_strategy() == "cpu_docker"

def test_cpu_docker_fallback_mac_no_mps(mock_torch_no_mps):
    with patch("sys.platform", "darwin"), \
         patch("shutil.which", return_value=None):
        assert get_execution_strategy() == "cpu_docker"

def test_get_phase1_command_mps(mock_torch_mps):
    with patch("sys.platform", "darwin"):
        cmd = get_phase1_command("a test prompt", "/out/path", 4)
        assert cmd == ["bash", "run_phase1_native.sh", "a test prompt"]

def test_get_phase1_command_nvidia():
    with patch("sys.platform", "linux"), \
         patch("shutil.which", return_value="/usr/bin/nvidia-smi"), \
         patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "nvidia runc"
        mock_run.return_value = mock_result
        
        cmd = get_phase1_command("a test prompt", "/out/path", 4)
        assert "docker" in cmd
        assert "compose" in cmd
        assert "infra/docker-compose.gpu.yml" in cmd
        assert "--rm" in cmd

def test_get_phase1_command_cpu():
    with patch("sys.platform", "linux"), \
         patch("shutil.which", return_value=None):
        cmd = get_phase1_command("a test prompt", "/out/path", 4)
        assert "docker" in cmd
        assert "compose" in cmd
        assert "infra/docker-compose.yml" in cmd
        assert "infra/docker-compose.gpu.yml" not in cmd
        assert "--rm" in cmd
