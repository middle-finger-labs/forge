#!/bin/bash
cd /Users/homebase/forge
source .venv/bin/activate
export $(grep -v '^#' .env | grep -v '^$' | xargs)
exec python -m worker
