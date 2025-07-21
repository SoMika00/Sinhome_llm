from fastapi.testclient import TestClient
from unittest.mock import patch
from src.api.main import app

client = TestClient(app)

@patch('src.api.services.vllm_client.get_chat_completion')
def test_handle_chat_success(mock_get_completion):
    mock_get_completion.return_value = "Ceci est une réponse de test."

    response = client.post(
        "/api/v1/chat/",
        json={"message": "Salut", "history": []}
    )

    assert response.status_code == 200
    assert response.json() == {"response": "Ceci est une réponse de test."}
    mock_get_completion.assert_called_once_with(user_message="Salut", history=[])
