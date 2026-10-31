"""Compatibility import for the shared calendar-request owner."""
import sys
import calendar_requests as _implementation
sys.modules[__name__] = _implementation
