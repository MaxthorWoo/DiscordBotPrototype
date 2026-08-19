import reflex as rx
from datetime import timezone
from shared_lib import crud
from shared_lib.utils.time_utils import format_datetime_beijing

class EventState(rx.State):
    """事件日志状态"""
    events: list[dict] = []

    def load_events(self):
        records = crud.get_recent_events(limit=10)
        self.events = [
            {
                "source": r.event_source,
                "type": r.event_type,
                "msg": r.message,
                "time": self._fmt(r.created_at),
            }
            for r in records
        ]
        crud.add_system_event(source="web", event_type="page_load", message="后台首页被访问")

    @staticmethod
    def _fmt(dt):
        """SystemEvent.created_at 存的是 naive UTC（datetime.utcnow），
        需先标记为 UTC 再转北京时间展示。"""
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return format_datetime_beijing(dt)