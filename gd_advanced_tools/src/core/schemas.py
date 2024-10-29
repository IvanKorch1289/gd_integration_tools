import json
from typing import Any, Generic, Mapping, TypeVar

from pydantic import BaseModel, Field, conlist
from pydantic.generics import GenericModel


def to_camelcase(string: str) -> str:
    """The alias generator for PublicModel."""

    resp = "".join(
        word.capitalize() if index else word
        for index, word in enumerate(string.split("_"))
    )
    return resp


class PublicModel(BaseModel):
    class Config:
        extra = 'ignore'
        orm_mode = True
        use_enum_values = True
        validate_assignment = True
        alias_generator = to_camelcase
        allow_population_by_field_name = True
        arbitrary_types_allowed = True

    def encoded_dict(self, by_alias=True):
        return json.loads(self.model_dump_json(by_alias=by_alias))


_PublicModel = TypeVar("_PublicModel", bound=PublicModel)


class ResponseMulti(PublicModel, GenericModel, Generic[_PublicModel]):

    result: list[PublicModel]


class Response(PublicModel, GenericModel, Generic[_PublicModel]):

    result: PublicModel


_Response = Mapping[int | str, dict[str, Any]]


class ErrorResponse(PublicModel):

    message: str = Field(description="This field represent the message")
    path: list = Field(
        description="The path to the field that raised the error",
        default_factory=list,
    )


class ErrorResponseMulti(PublicModel):

    results: conlist(ErrorResponse, min_length=1)