from pydantic import BaseModel, Field
from typing import Optional

# structure the output of llm
class Reference(BaseModel):
    raw_reference: str = Field(
        description="The original reference exactly as extracted from the AI-generated response."
    )

    title: Optional[str] = Field(
        default=None,
        description="Title of the publication if it can be identified from the reference."
    )

    authors: list[str] = Field(
        default_factory=list,
        description="List of authors extracted from the reference."
    )

    year: Optional[int] = Field(
        default=None,
        description="Publication year of the source."
    )

    source: Optional[str] = Field(
        default=None,
        description="Publication source such as journal name, conference name, book title, website, or publisher."
    )

    doi: Optional[str] = Field(
        default=None,
        description="Digital Object Identifier (DOI) of the source if available."
    )

    url: Optional[str] = Field(
        default=None,
        description="Web URL associated with the source if provided in the reference."
    )