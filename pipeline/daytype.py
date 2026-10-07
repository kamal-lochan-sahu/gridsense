"""Public holidays and day classes per country.

Electricity demand on a public holiday behaves like a Sunday, so a model that just looks "one
week back" is wrong on the holiday and again on the same weekday a week later. Only *national*
holidays from the ``holidays`` package are used; regional ones (e.g. some German states) are
ignored on purpose.
"""
from datetime import date
from functools import lru_cache

import holidays

ISO = {"germany": "DE", "france": "FR", "spain": "ES", "poland": "PL"}


@lru_cache(maxsize=None)
def _calendar(country, year: int):
    code = ISO.get(country)
    return holidays.country_holidays(code, years=[year]) if code else {}


def is_holiday(day: date, country) -> bool:
    return day in _calendar(country, day.year)


def day_class(day: date, country) -> str:
    """'sun' for Sundays and Monday-Friday public holidays, 'sat' for Saturdays, else 'wd'.

    A holiday that falls on a Saturday stays 'sat': that day is already a weekend day.
    """
    weekday = day.weekday()
    if weekday == 6 or (weekday < 5 and is_holiday(day, country)):
        return "sun"
    return "sat" if weekday == 5 else "wd"


def is_offday(day: date, country) -> bool:
    """True for weekends and public holidays (what the Prophet weekend curve should cover)."""
    return day_class(day, country) != "wd"
