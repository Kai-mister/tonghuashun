#!/bin/sh
# Run from an extracted release upgrade bundle on a computer with ADB.
set -eu
cd "$(dirname "$0")/.."
command -v adb >/dev/null
adb -d shell 'test -x /data/local/tmp/ths-sim/python && test -s /data/local/tmp/ths-sim/state/manager.key'
adb -d install -r android/dist/sim-manager.apk
adb -d shell 'mkdir -p /data/local/tmp/ths-sim/upgrade/phone /data/local/tmp/ths-sim/upgrade/ths'
for file in strategy_settings.py premarket.py strategy_worker.py phone/manager.py phone/local.py ths/simulator.py; do
    adb -d push "$file" "/data/local/tmp/ths-sim/upgrade/$file"
done
adb -d shell '
set -eu
cd /data/local/tmp/ths-sim
for service in worker manager; do
    if [ -s "state/$service.pid" ]; then
        pid=$(cat "state/$service.pid")
        if [ -r "/proc/$pid/cmdline" ] && tr "\000" " " <"/proc/$pid/cmdline" | grep -Fq "phone/"; then
            kill "$pid"
        fi
    fi
done
sleep 1
for file in strategy_settings.py premarket.py strategy_worker.py phone/manager.py phone/local.py ths/simulator.py; do
    mv "upgrade/$file" "$file"
done
sh phone/background.sh
'
