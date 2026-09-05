"""Domain models for data processing tutorial."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DataRecord(BaseModel):
    """Single unit of processed data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(gt=0, description="Record identifier")
    val: float = Field(description="Numerical value")


class SummaryResult(BaseModel):
    """Summary statistics aggregated from records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    count: int = Field(ge=0, description="Total count")
    mean: float = Field(description="Mean value")
    total: float = Field(description="Total sum")

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate math consistency."""
        if self.count > 0:
            expected = round(self.total / self.count, 4)
            if round(self.mean, 4) != expected:
                msg = f"Mean {self.mean} does not match total/count {expected}"
                raise ValueError(msg)
        return self


__all__ = [
    "DataRecord",
    "SummaryResult",
]
