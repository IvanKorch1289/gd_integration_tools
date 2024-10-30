import json
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, conlist


def to_camelcase(string: str) -> str:
    resp = "".join(
        word.capitalize() if index else word
        for index, word in enumerate(string.split("_"))
    )
    return resp


class PublicModel(BaseModel):
    class Config:
        extra = 'ignore'
        from_attributes = True
        use_enum_values = True
        validate_assignment = True
        alias_generator = to_camelcase
        populate_by_name = True
        arbitrary_types_allowed = True
        from_attributes = True

    def encoded_dict(self, by_alias=True):
        return json.loads(self.model_dump_json(by_alias=by_alias))


_PublicModel = TypeVar("_PublicModel", bound=PublicModel)


class ResponseMulti(PublicModel, Generic[_PublicModel]):
    """Generic response model that consist multiple results."""

    result: list[_PublicModel]


class Response(PublicModel, Generic[_PublicModel]):

    result: _PublicModel


class ErrorResponse(PublicModel):

    message: str = Field(description="This field represent the message")
    path: list = Field(
        description="The path to the field that raised the error",
        default_factory=list,
    )


class ErrorResponseMulti(PublicModel):

    results: conlist(ErrorResponse, min_length=1)
