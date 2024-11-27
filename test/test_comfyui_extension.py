import pytest
from unittest.mock import patch, Mock
from comfyui_extension import ComfyUIWebSocketAPI, ComfyUIExtension
import json

# Example JSON for testing workflows
WORKFLOW_JSON = {
    "16": {"inputs": {"text": "default positive"}},
    "19": {"inputs": {"text": "default negative"}},
    "38": {"inputs": {"image": "placeholder"}},
    "36": {"inputs": {"cfg": 7.0, "denoise": 0.75, "steps": 20, "seed": 1234}}
}

# Fixture for the extension
@pytest.fixture
def extension():
    return ComfyUIExtension()

# Fixture for the API class
@pytest.fixture
def api():
    return ComfyUIWebSocketAPI(server_address="127.0.0.1:8188")

# Fixture for loading a mock workflow
@pytest.fixture
def mock_workflow_file(tmp_path):
    workflow_path = tmp_path / "workflow.json"
    with open(workflow_path, "w") as f:
        json.dump(WORKFLOW_JSON, f)
    return str(workflow_path)


def test_load_workflow(extension, mock_workflow_file):
    workflow = extension.load_workflow(mock_workflow_file)
    assert workflow == WORKFLOW_JSON


@patch("comfyui_extension.urllib.request.urlopen")
def test_queue_prompt(mock_urlopen, api):
    mock_response = Mock()
    mock_response.read.return_value = json.dumps({"prompt_id": "1234"}).encode('utf-8')
    mock_urlopen.return_value = mock_response

    result = api.queue_prompt({"prompt": "test"})
    assert result["prompt_id"] == "1234"
    mock_urlopen.assert_called_once()


def test_image_embedding(extension, tmp_path):
    # Mock image data
    image_path = tmp_path / "image.png"
    with open(image_path, "wb") as f:
        f.write(b"fake image data")

    # Generate Base64 image
    with open(image_path, "rb") as f:
        encoded_image = extension.load_image(image_path)
        assert encoded_image is not None


@patch("comfyui_extension.ComfyUIWebSocketAPI.queue_prompt")
@patch("comfyui_extension.ComfyUIWebSocketAPI.get_history")
def test_full_workflow_integration(mock_get_history, mock_queue_prompt, extension, mock_workflow_file):
    mock_queue_prompt.return_value = {"prompt_id": "1234"}
    mock_get_history.return_value = {"1234": {"outputs": {}}}

    workflow = extension.load_workflow(mock_workflow_file)
    assert workflow is not None

    prompt_id = mock_queue_prompt({"prompt": workflow})
    assert prompt_id["prompt_id"] == "1234"

    history = mock_get_history(prompt_id["prompt_id"])
    assert "1234" in history


def test_invalid_workflow_path(extension):
    with pytest.raises(FileNotFoundError):
        extension.load_workflow("/invalid/path/to/workflow.json")


@patch("comfyui_extension.urllib.request.urlopen")
def test_api_error_handling(mock_urlopen, api):
    mock_urlopen.side_effect = Exception("Network error")
    with pytest.raises(Exception, match="Network error"):
        api.queue_prompt({"prompt": "test"})


def test_empty_workflow_file(tmp_path):
    empty_workflow = tmp_path / "empty_workflow.json"
    empty_workflow.write_text("{}")
    with open(empty_workflow, "r") as f:
        data = json.load(f)
    assert data == {}


def test_invalid_image_path(api):
    with pytest.raises(FileNotFoundError):
        api.load_image("/invalid/path/to/image.png")