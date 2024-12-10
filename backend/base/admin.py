from typing import List


__all__ = ("BaseAdmin",)


class BaseAdmin:
    page_size: int = 20
    page_size_options: List[int] = [25, 50, 100, 200]
