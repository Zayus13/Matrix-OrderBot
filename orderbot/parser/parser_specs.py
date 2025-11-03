from dataclasses import dataclass, field
from typing import Callable, List, Tuple, Dict, Optional, Any

@dataclass
class ArgSpec:
    names: Tuple[str, ...]
    kwargs: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CommandSpec:
    name: str
    func: Callable[[List[str]], str]
    help: str
    description: Optional[str] = None
    arguments: List[ArgSpec] = field(default_factory=list)