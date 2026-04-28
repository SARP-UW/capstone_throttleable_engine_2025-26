from dataclasses import dataclass
from typing import Any, Optional

@dataclass(slots=True)
class RawSample:
    sensor_name: str
    sensor_kind: str
    channel: int
    t_monotonic: float
    t_wall: float
    raw_count: int
    raw_diff_1: Optional[int] = None
    raw_diff_2: Optional[int] = None
    conversion_type: str = ""


@dataclass(slots=True)
class Sample:
    sensor_name: str
    sensor_kind: str
    t_monotonic: float
    t_wall: float
    raw_value: Any = None
    value: Optional[float] = None
    units: str = ""
    V_diff_1: Optional[float] = None
    V_diff_2: Optional[float] = None
    filtered_value: Optional[float] = None
    status: str = "OK"
    message: str = ""
    sequence: Optional[int] = None
    source: str = ""