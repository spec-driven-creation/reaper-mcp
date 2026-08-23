import ast
import socket
import threading
import unittest
from pathlib import Path

from reaper_mcp import server


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_bridge_receive_request():
    bridge_path = REPOSITORY_ROOT / "reaper" / "mcp_bridge.py"
    bridge_tree = ast.parse(bridge_path.read_text(encoding="utf-8"))
    receive_function = next(
        node
        for node in bridge_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "receive_request"
    )
    module = ast.Module(body=[receive_function], type_ignores=[])
    namespace = {
        "socket": socket,
        "REQUEST_CHUNK_SIZE": 4096,
        "MAX_REQUEST_BYTES": 4 * 1024 * 1024,
    }
    exec(compile(module, str(bridge_path), "exec"), namespace)
    return namespace["receive_request"]


class TransportTests(unittest.TestCase):
    def test_bridge_receives_request_larger_than_one_chunk(self):
        receive_request = load_bridge_receive_request()
        sender, receiver = socket.socketpair()
        payload = b"{" + (b"x" * 12000) + b"}"

        try:
            sender.sendall(payload)
            sender.shutdown(socket.SHUT_WR)
            receiver.settimeout(1)
            self.assertEqual(receive_request(receiver), payload)
        finally:
            sender.close()
            receiver.close()

    def test_client_half_closes_request_and_reads_chunked_response(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        received = []

        def serve_once():
            connection, _ = listener.accept()

            with connection:
                chunks = []

                while True:
                    chunk = connection.recv(4096)

                    if not chunk:
                        break

                    chunks.append(chunk)

                received.append(b"".join(chunks))
                connection.sendall(b'{"value":')
                connection.sendall(b"123}")

        worker = threading.Thread(target=serve_once)
        worker.start()
        original_port = server.PORT

        try:
            server.PORT = port
            response = server.send_reaper_command(
                "bulk_test", notes=[{"value": "x" * 12000}]
            )
        finally:
            server.PORT = original_port
            worker.join(timeout=2)
            listener.close()

        self.assertFalse(worker.is_alive())
        self.assertGreater(len(received[0]), 4096)
        self.assertEqual(response, {"value": 123})


if __name__ == "__main__":
    unittest.main()
