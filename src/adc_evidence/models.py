from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LinkerType(StrEnum):
    CLEAVABLE = "cleavable"
    NON_CLEAVABLE = "non-cleavable"
    UNKNOWN = "unknown"


class DevelopmentStatus(StrEnum):
    APPROVED = "approved"
    INVESTIGATIONAL = "investigational"
    DISCONTINUED = "discontinued"
    UNKNOWN = "unknown"


class ReviewStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"


class ADCRecord(BaseModel):
    """Validated representation of one ADC seed record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    adc_id: str = Field(min_length=1)
    adc_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    target: str = Field(min_length=1)
    antibody: str | None = None
    linker_name: str | None = None
    linker_type: LinkerType = LinkerType.UNKNOWN
    payload_name: str | None = None
    payload_class: str | None = None
    dar: float | None = Field(default=None, ge=0, le=20)
    indication: str | None = None
    development_status: DevelopmentStatus = DevelopmentStatus.UNKNOWN
    company: str | None = None
    source_url: str | None = None
    data_review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW

    @field_validator("aliases", mode="before")
    @classmethod
    def split_aliases(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split("|") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raise ValueError("aliases must be a list or a pipe-separated string")

    @field_validator(
        "antibody",
        "linker_name",
        "payload_name",
        "payload_class",
        "indication",
        "company",
        "source_url",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("dar", mode="before")
    @classmethod
    def empty_dar_to_none(cls, value: object) -> object:
        return None if value == "" else value

