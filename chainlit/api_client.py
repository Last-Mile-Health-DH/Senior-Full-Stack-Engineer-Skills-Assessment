import os

import httpx
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

BACKEND_API_BASE_URL = os.environ.get("BACKEND_API_BASE_URL", "http://localhost:6100")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _extract_error_message(body: object, fallback: str) -> str:
    if isinstance(body, dict) and "detail" in body:
        detail = body["detail"]
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            messages = [item.get("msg") for item in detail if isinstance(item, dict) and item.get("msg")]
            if messages:
                return "; ".join(messages)
    return fallback


async def post_chat(question: str, num_results: int | None = None) -> dict:
    payload: dict = {"question": question}
    if num_results is not None:
        payload["num_results"] = num_results

    async with httpx.AsyncClient(base_url=BACKEND_API_BASE_URL, timeout=60.0) as client:
        try:
            response = await client.post("/chat", json=payload)
        except httpx.RequestError as exc:
            raise ApiError("Could not reach the backend — is it running?", status=0) from exc

    if response.status_code >= 500:
        raise ApiError("Something went wrong processing that — please try again.", status=response.status_code)

    if response.status_code >= 400:
        try:
            body = response.json()
        except ValueError:
            body = None
        raise ApiError(
            _extract_error_message(body, f"Request failed ({response.status_code})."),
            status=response.status_code,
        )

    return response.json()
