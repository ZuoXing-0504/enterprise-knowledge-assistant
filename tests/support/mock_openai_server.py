import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class OpenAIHandler(BaseHTTPRequestHandler):
    server_version = "MockOpenAI/1.0"

    def do_POST(self) -> None:
        if self.path == "/v1/embeddings":
            self._handle_embeddings()
            return
        if self.path == "/v1/chat/completions":
            self._handle_chat_completion()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_embeddings(self) -> None:
        payload = self._read_payload()
        if payload is None:
            return
        try:
            inputs = payload["input"]
            if isinstance(inputs, str):
                inputs = [inputs]
            dimensions = int(payload.get("dimensions", 1536))
        except (KeyError, TypeError, ValueError):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return

        data = []
        for index, _ in enumerate(inputs):
            embedding = [0.0] * dimensions
            embedding[index % dimensions] = 1.0
            data.append({"object": "embedding", "index": index, "embedding": embedding})

        self._send_json(
            {
                "object": "list",
                "data": data,
                "model": payload.get("model", "mock-embedding"),
                "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
            }
        )

    def _handle_chat_completion(self) -> None:
        payload = self._read_payload()
        if payload is None:
            return
        if payload.get("stream") is True:
            self._send_chat_stream(payload)
            return
        self._send_json(
            {
                "id": "chatcmpl-integration-test",
                "object": "chat.completion",
                "model": payload.get("model", "mock-chat"),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "企业年假为十天 [来源1]",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 42,
                    "completion_tokens": 9,
                    "total_tokens": 51,
                },
            }
        )

    def _send_chat_stream(self, payload: dict[str, Any]) -> None:
        model = payload.get("model", "mock-chat")
        events = [
            {
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": {"content": "企业年假为"}}],
            },
            {
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": {"content": "十天 [来源1]"}}],
            },
            {
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [],
                "usage": {
                    "prompt_tokens": 42,
                    "completion_tokens": 9,
                    "total_tokens": 51,
                },
            },
        ]
        response = "".join(f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events)
        response += "data: [DONE]\n\n"
        encoded = response.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_payload(self) -> dict[str, Any] | None:
        content_length = int(self.headers.get("Content-Length", "0"))
        try:
            return json.loads(self.rfile.read(content_length))
        except (TypeError, ValueError):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return None

    def _send_json(self, payload: dict[str, Any]) -> None:
        response = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args()
    server = ThreadingHTTPServer((arguments.host, arguments.port), OpenAIHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
