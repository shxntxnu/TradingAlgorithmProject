import os
import json
from datetime import datetime

class AuditLogger:
    """Manages append-only JSON audit logs of all trading decisions, signals, and executions."""
    
    def __init__(self, filepath: str = "audit.log"):
        self.filepath = os.path.abspath(filepath)
        # Ensure log file exists
        if not os.path.exists(self.filepath):
            with open(self.filepath, "w") as f:
                pass # Create file

    def log_event(self, event_type: str, details: dict):
        """Append a timestamped JSON event to the audit log."""
        event = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type,
            'details': details
        }
        
        # Append to log file
        try:
            with open(self.filepath, "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            print(f"Error writing to audit log: {e}")
            
    def read_events(self, event_type: str = None) -> list:
        """Read all logged events, optionally filtered by event_type."""
        events = []
        if not os.path.exists(self.filepath):
            return events
            
        try:
            with open(self.filepath, "r") as f:
                for line in f:
                    if line.strip():
                        evt = json.loads(line)
                        if event_type is None or evt['event_type'] == event_type:
                            events.append(evt)
        except Exception as e:
            print(f"Error reading audit log: {e}")
            
        return events
