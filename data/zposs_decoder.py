# data/zposs_decoder.py
"""ZPOSS data decoding utilities."""

from myconfig.constants import ZPOSS_SLOPE, ZPOSS_OFFSET, GR8


def decode_zposs(params: list[int]) -> tuple[int, float]:
    """
    Decode ZPOSS a/b parameters into raw ADC value and scaled physical value.
    """
    if len(params) < 5:
        return 0, 0.0

    a, b = params[3], params[4]

    integer_part = 87 - a
    fraction_part = 99 - b
    y = integer_part + fraction_part / 100.0

    x_min, x_max = 647, 1001
    y_min, y_max = 36.54, 87.6

    adc_raw = int(round(x_min + (y - y_min) * (x_max - x_min) / (y_max - y_min)))

    return adc_raw, y


def adc_to_physical(adc_value: int) -> float:
    """Convert raw ADC to calibrated physical value."""
    return (ZPOSS_SLOPE * adc_value) + ZPOSS_OFFSET
