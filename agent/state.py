from typing import TypedDict, Annotated, Literal
import operator


class IncidentState(TypedDict):
    # Input
    alert: dict

    # Gathered evidence 
    logs: Annotated[list, operator.add]    
    metrics: Annotated[list, operator.add]   

    # Reasoning
    root_cause: str
    confidence: float                        
    confidence_history: Annotated[list, operator.add]  
    severity: Literal["P0", "P1", "P2", "P3"]
    affected_services: list[str]
    hypothesis: str                         

    # Runbook 
    runbook_title: str
    runbook_content: str

    # Actions taken 
    remediation_attempted: bool
    remediation_result: str
    team_paged: str
    slack_thread: str
    ticket_id: str

    # Memory
    similar_past_incidents: list[dict]   

    # Output 
    incident_report: str
    status: Literal["investigating", "mitigating", "resolved", "escalated"]

    # Control flow 
    retry_count: int
    needs_escalation: bool
    max_retries: int                      