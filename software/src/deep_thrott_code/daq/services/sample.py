from dataclasses import dataclass, field
from typing import Optional, Any
import time

@dataclass(slots=True)
class RawSample:
    sensor_name: str
    sensor_kind: str
    conversion_type: str
    channel: int
    t_monotonic: float
    t_wall: float
    raw_count: int


@dataclass(slots=True)
class Sample:
    sensor_name: str
    sensor_kind: str = ""
    t_monotonic: float
    t_wall: float 
    raw_value: Any = None  
    value: float = None       
    units: str = ""
    filtered_value: Optional[float] = None