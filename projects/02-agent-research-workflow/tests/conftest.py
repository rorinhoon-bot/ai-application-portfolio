"""Shared safety fixtures for ordinary offline tests."""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail fast if an ordinary test attempts network access."""

    def blocked(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("NETWORK_DISABLED: ordinary tests must stay offline")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
