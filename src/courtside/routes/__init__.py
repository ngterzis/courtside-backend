from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


class CamelRouter(APIRouter):
    def add_api_route(
        self, path: str, endpoint: Callable[..., Any], **kwargs: Any
    ) -> None:
        kwargs.setdefault("response_model_by_alias", True)
        super().add_api_route(path, endpoint, **kwargs)
