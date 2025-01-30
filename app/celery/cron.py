from celery.schedules import crontab
from dataclasses import dataclass


__all__ = ("CronPresets",)


@dataclass
class CronPreset:
    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"

    @property
    def schedule(self):
        return crontab(minute=self.minute, hour=self.hour, day_of_week=self.day_of_week)


class CronPresets:
    HOURLY = CronPreset(minute="0")
    DAILY = CronPreset(minute="0", hour="0")
    WORKDAYS = CronPreset(minute="0", hour="9", day_of_week="mon-fri")
