#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility layer for OpenFlex motor-manager maintenance scripts."""

try:
    from openflex_driver._lib.can_utils import *  # noqa: F401,F403
except ImportError as exc:
    raise ImportError(
        "openflex_driver is required. Install ../openflex_drivers/openflex_driver.deb "
        "with install_openflex_drivers_and_build.sh."
    ) from exc
