"""External signals: free, keyless public APIs as ambient context.

Weather, air quality, public holidays and exchange rates. These are context
signals — they never drive scoring or recommendations, and every call degrades
gracefully (stale cache first, then an honest error state).
"""

from app.integrations.external_signals.service import (  # noqa: F401
    Signal,
    get_air_quality,
    get_fx_rates,
    get_holidays,
    get_weather,
    signal_status,
)
