from typing import Dict, Optional, TypedDict


__all__ = ("ProcessingResult",)


class ProcessingResult(TypedDict):
    """Type definition for processing results"""

    success: bool
    order_id: str
    result_data: Dict
    error_message: Optional[str]
