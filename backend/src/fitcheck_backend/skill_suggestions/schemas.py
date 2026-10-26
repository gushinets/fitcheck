from pydantic import StrictStr
from ..contracts.domain import DTO


class RawSuggestions(DTO):
    skills: list[StrictStr]
