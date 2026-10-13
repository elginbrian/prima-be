from datetime import date, timedelta
from typing import Optional, List, Set


def is_business_day(d: date, holidays: Optional[Set[date]] = None) -> bool:
    """Returns True if date is Monday through Friday and not a holiday."""
    if d.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False
    if holidays and d in holidays:
        return False
    return True


def add_business_days(start_date: date, n_days: int, holidays: Optional[List[date]] = None) -> date:
    """Adds n business days to start_date, skipping weekends and holidays."""
    holiday_set = set(holidays) if holidays else set()
    current = start_date
    added = 0
    step = 1 if n_days >= 0 else -1
    target = abs(n_days)

    while added < target:
        current += timedelta(days=step)
        if is_business_day(current, holiday_set):
            added += 1

    return current


def count_business_days(start_date: date, end_date: date, holidays: Optional[List[date]] = None) -> int:
    """Counts business days between start_date and end_date (inclusive of start, exclusive of end)."""
    holiday_set = set(holidays) if holidays else set()
    if start_date > end_date:
        return -count_business_days(end_date, start_date, holidays)

    current = start_date
    count = 0
    while current < end_date:
        if is_business_day(current, holiday_set):
            count += 1
        current += timedelta(days=1)

    return count
