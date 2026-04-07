from dataclasses import dataclass, field
from typing import Optional, Any
import time

@dataclass(slots=True)
class Sample:
    sensor_name: str
    sensor_kind: str
    t_monotonic: float = field(default_factory=time.perf_counter)
    t_wall: float = field(default_factory=time.time)
    raw_value: Any = None  
    value: float = None       
    units: str = ""                    
    status: str = "ok"   
    filtered_value: Optional[float] = None