import json
import logging
from datetime import datetime, timezone

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message"
        }
        
        log_payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "filename": record.filename,
            "lineno": record.lineno,
        }
        
        # Add correlation ID
        from shared.logging.logger import get_correlation_id
        corr_id = get_correlation_id()
        if corr_id:
            log_payload["correlation_id"] = corr_id
            
        # Add exception info
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)
            
        # Add any extra passed arguments
        for key, value in record.__dict__.items():
            if key not in standard_attrs:
                log_payload[key] = value
                
        return json.dumps(log_payload)
