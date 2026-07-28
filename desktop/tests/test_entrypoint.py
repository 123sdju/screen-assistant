from app.main import INSTANCE_NAME, self_test


def test_entrypoint_imports_qt_local_ipc_and_self_test_passes() -> None:
    assert INSTANCE_NAME == "screen-assistant-desktop-v1"
    assert self_test() == 0
