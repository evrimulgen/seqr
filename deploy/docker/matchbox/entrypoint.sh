#!/usr/bin/env bash

set -x

env

cd /matchbox_deployment

java -jar -Dexomiser.data-directory=/root/reference_data/data matchbox-0.1.0.jar &

sleep 10000000000