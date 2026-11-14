#!/bin/sh
# Diagnostic: pretend to read back a sensor's calibration. $1 is the sensor tag.
echo "sensor calibration check for: $1"
echo "zero=0.00 span=2.00 drift=+0.01 status=OK"
