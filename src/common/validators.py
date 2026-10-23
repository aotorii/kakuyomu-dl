import argparse

from common.errors import ConfigError


def positive_int(value) -> int:
    try:
        value = int(value)
    except ValueError:
        raise ConfigError(f"Invalid integer value: '{value}'")

    if value <= 0:
        raise ConfigError(f"Value must be greater than 0: '{value}'")

    return value


def argparse_positive_int(value) -> int:
    try:
        return positive_int(value)
    except ConfigError as e:
        raise argparse.ArgumentTypeError(str(e))
