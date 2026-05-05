"""Web3-коннекторы (opt-in `gdi[web3]`) — C10.

EVM JSON-RPC через пакет `web3` (web3.py).
"""

__all__ = ("is_web3_available",)


def is_web3_available() -> bool:
    try:
        import web3  # noqa: F401

        return True
    except ImportError:
        return False
