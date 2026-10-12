"""Cooperative cancellation shared by model analysis passes."""
from __future__ import annotations


def check_cancelled(cancelled):
    if cancelled():
        raise InterruptedError('Обработка отменена')
