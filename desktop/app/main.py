from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from app.config import ConfigStore
from app.main_window import MainWindow
from app.pairing import PairingManager


INSTANCE_NAME = "screen-assistant-desktop-v1"


def notify_existing_instance() -> bool:
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_NAME)
    if not socket.waitForConnected(250):
        return False
    socket.write(b"show")
    socket.flush()
    socket.waitForBytesWritten(250)
    socket.disconnectFromServer()
    return True


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if notify_existing_instance():
        return 0
    QLocalServer.removeServer(INSTANCE_NAME)
    server = QLocalServer()
    if not server.listen(INSTANCE_NAME):
        return 1
    window = MainWindow(ConfigStore())

    def show_existing() -> None:
        connection = server.nextPendingConnection()
        if connection:
            connection.waitForReadyRead(100)
            connection.readAll()
            connection.disconnectFromServer()
        window.show_from_instance()

    server.newConnection.connect(show_existing)
    window.show()
    exit_code = app.exec()
    server.close()
    QLocalServer.removeServer(INSTANCE_NAME)
    return exit_code


def self_test() -> int:
    """Exercise packaged imports, portable config and token hashing without opening a window."""
    try:
        with tempfile.TemporaryDirectory() as folder:
            store = ConfigStore(Path(folder) / "config.json")
            store.save()
            pairing = PairingManager(store)
            code, _ = pairing.issue_code()
            result = pairing.pair(code, "self-test", "Self Test")
            if pairing.authenticate(result["token"]) is None:
                return 2
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
