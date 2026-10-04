"""Regression tests for the economic-calendar source parsers (JBlanked/FF/Bloomberg).

Fixtures are trimmed excerpts of real markup: the ForexFactory calendar table
(from an archived forexfactory.com/calendar page) and the classic div-based
Investing/forexprostools widget that Bloomberg embeds.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.providers.bloomberg_provider import parse_investing_calendar
from app.providers.forexfactory_provider import parse_forexfactory_calendar
from app.providers.jblanked_provider import _to_event, tz_from_env

FF_HTML = """
<table>
<tr class="calendar__row calendar__row--day-breaker"><td colspan="10" class="calendar__cell">Sun <span>Sep 20</span></td></tr>
<tr data-event-id="147463" data-day-dateline="1789876800" class="calendar__row calendar__row--new-day">
  <td class="calendar__cell calendar__date" rowspan="3"><span class="date">Sun <span>Sep 20</span></span></td>
  <td class="calendar__cell calendar__time">All Day</td>
  <td class="calendar__cell calendar__currency">JPY</td>
  <td class="calendar__cell calendar__impact"><span class="icon icon--ff-impact-gra"></span></td>
  <td class="calendar__cell calendar__event"><div class="calendar__event-wrapper"><span class="calendar__event-title">Bank Holiday</span></div></td>
  <td class="calendar__cell calendar__actual"></td>
  <td class="calendar__cell calendar__forecast"></td>
  <td class="calendar__cell calendar__previous"><span></span></td>
</tr>
<tr data-event-id="147500" class="calendar__row">
  <td class="calendar__cell calendar__time">8:30am</td>
  <td class="calendar__cell calendar__currency">USD</td>
  <td class="calendar__cell calendar__impact"><span class="icon icon--ff-impact-red"></span></td>
  <td class="calendar__cell calendar__event"><span class="calendar__event-title">Core CPI m/m</span></td>
  <td class="calendar__cell calendar__actual">0.4</td>
  <td class="calendar__cell calendar__forecast">0.4</td>
  <td class="calendar__cell calendar__previous">0.2</td>
</tr>
</table>
"""

WIDGET_HTML = """
<section class="day-section">
<header class="article dateRow"><h2 class="theDay" id="theDay1789876800">Sunday, November 10, 2026</h2></header>
<ul>
<li class="item">
  <button aria-expanded="false" type="button" class="article calLine" id="eventRowId_396709"
          event_attr_id="1841" event_timestamp="2026-11-10 13:30:00"
          aria-label="08:30 | USD | High Volatility Expected | Core CPI m/m">
    <time class="time" datetime="2026-11-10 08:30">08:30</time>
    <div class="left flagCur"><span title="United States" class="ceFlags USA">&nbsp;</span>USD</div>
    <div class="sentiment" title="High Volatility Expected"><i class="newSiteIconsSprite redFullBullishIcon"></i></div>
    <div class="left event">Core CPI m/m</div>
    <div class="infoCont">
      <div class="act" title="" id="eventActual_396709">
        <span class="miniLabel">Act:</span><span class="blackFont event-396709-actual">0.4</span>
      </div>
      <div class="fct" id="eventForecast_396709">
        <span class="miniLabel">Fcst:</span><span class="blackFont">0.3</span>
      </div>
      <div class="prev" id="eventPrevious_396709">
        <span class="miniLabel">Prev:</span><span class="blackFont">0.2</span>
      </div>
    </div>
  </button>
</li>
</ul>
</section>
"""


def test_forexfactory_parser_extracts_rows():
    events = parse_forexfactory_calendar(FF_HTML)
    assert len(events) == 2

    holiday, cpi = events
    # Day-breaker date + All Day -> midnight in the FF display timezone (UTC+2 default).
    assert holiday.title == "Bank Holiday"
    assert holiday.currency == "JPY"
    assert holiday.importance.value == "low"
    # Sep 20 00:00 at UTC+2 == Sep 19 22:00 UTC.
    assert holiday.scheduled_at.day == 19
    assert holiday.scheduled_at.hour == 22

    assert cpi.title == "Core CPI m/m"
    assert cpi.currency == "USD"
    assert cpi.country == "US"
    assert cpi.importance.value == "high"
    assert (cpi.actual, cpi.forecast, cpi.prior) == (0.4, 0.4, 0.2)
    assert cpi.source == "ForexFactory"
    assert cpi.id.startswith("ff-")


def test_bloomberg_widget_parser_extracts_rows():
    events = parse_investing_calendar(WIDGET_HTML)
    assert len(events) == 1
    cpi = events[0]
    assert cpi.title == "Core CPI m/m"
    assert cpi.currency == "USD"
    assert cpi.importance.value == "high"
    # event_timestamp is UTC.
    assert cpi.scheduled_at.isoformat() == "2026-11-10T13:30:00+00:00"
    assert (cpi.actual, cpi.forecast, cpi.prior) == (0.4, 0.3, 0.2)
    assert cpi.source == "Bloomberg"
    assert cpi.id.startswith("bbg-")


def test_jblanked_docs_example_maps_to_utc_and_tolerates_placeholders():
    example = {
        "Name": "Core CPI m/m",
        "Currency": "USD",
        "Category": "Consumer Inflation Report",
        "Impact": "High",
        "Date": "2024.02.08 15:30:00",
        "Actual": 0.4,
        "Forecast": 0.4,
        "Previous": 0.2,
        "Outcome": "Actual = Forecast > Previous",
    }
    tz = tz_from_env("JBLANKED_TZ_OFFSET_HOURS", 2)
    event = _to_event(example, tz)
    assert event is not None
    # 15:30 UTC+2 == 13:30 UTC == 08:30 ET, the real release time.
    assert event.scheduled_at.isoformat() == "2024-02-08T13:30:00+00:00"
    assert event.importance.value == "high"
    assert event.country == "US"
    assert (event.actual, event.forecast, event.prior) == (0.4, 0.4, 0.2)

    placeholders = dict(example, Actual="—", Forecast="-", Previous="N/A")
    mapped = _to_event(placeholders, tz)
    assert mapped is not None
    assert (mapped.actual, mapped.forecast, mapped.prior) == (None, None, None)

    assert _to_event({"Name": "", "Date": ""}, tz) is None
