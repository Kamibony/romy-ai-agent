from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class MissionBlock(BaseModel):
    block_id: str
    type: str
    sop_reference_id: Optional[str] = None
    instruction: Optional[str] = None
    inputs: Dict[str, str] = Field(default_factory=dict)
    outputs: List[str] = Field(default_factory=list)

class MissionGraph(BaseModel):
    mission_id: str
    name: str
    blocks: List[MissionBlock]
    execution_order: List[str]

# Real execution will require more integration but this parses the structure
