#!/bin/sh
set -eu

/usr/local/bin/backup.sh

exec crond -f -l 2
