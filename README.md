# Aegis Field for Kali Linux

An editable Python desktop edition of Aegis Field. It scans real Bluetooth advertisements through BlueZ and nearby Wi-Fi access points through NetworkManager. There is no account, server, subscription gate, or simulated data in normal operation.

## Install on your Kali laptop

Clone the repository and install:

```sh
git clone https://github.com/BooMSainT/Force-field.git
cd Force-field
bash install.sh
./run.sh
```

Use a current Kali installation with Python 3.10 or later and a graphical desktop. Internet is needed for installation. The installer uses sudo for distribution packages and starting Bluetooth; the app itself runs as your normal desktop user. Keep the project folder in place because the application-menu shortcut points to it. No Apple developer account is needed.

## What works

* **Bluetooth:** continuous BLE advertisement scanning; timestamped RSSI; source names updated when scan-response names arrive; known devices and custom labels; service-based device hints; signal history graph; first/last encounters; persistent baseline learning.
* **Improved interpretation:** median-per-second samples, robust slope calculation, fast reversal detection, gap handling, noise-aware confidence, two-second label confirmation, steady strength bands, and 90-second approach-alert cooldowns. Strength is a rough ordering cue, never a distance measurement.
* **Defense:** turn on Defense alerts to collect a 15-second baseline. Baseline sources are placed in the review list. Choose Mark known or Unrecognized. Known sources stay out of the immediate unknown view. Confirm stationary placement only when the laptop really is stationary. Unknown motion reduces confidence and prevents qualifying approach alerts; basic new-source notices still work.
* **Wi-Fi networks:** nearby SSIDs, BSSIDs, channel, signal percentage, security label, and current connection; refresh every 30 seconds. NetworkManager may perform ordinary active discovery scans.
* **Local devices:** the kernel's IPv4/IPv6 neighbor cache, including IP, address, interface, and reachability state. This is not a complete inventory of every connected router client; stale cache entries are labeled.
* **Searching devices:** automatic live probe-request header observations, request counts, last-seen times, and RSSI when supplied by the adapter. Addresses are converted to session-specific IDs, held in memory for ten minutes, and capped at 1,000 entries. Searched SSIDs and packet files are not saved. These observations are kept separate from BLE and are never merged into a person's identity.
* **History:** SQLite saves known choices, labels, learned baselines, encounters, and events across launches. Raw RSSI is retained 24 hours with a 100,000-sample cap; events seven days; encounters 30 days. CSV exports contain hashed source IDs and encounter times. The hashes are pseudonyms, not a guarantee of anonymity.
* **Health:** separate sensor errors, Bluetooth retry, bounded ingestion queue, dropped-observation count, and truthful missing-capability states.

## Wi-Fi probe requests

This edition assumes a dedicated monitor-mode Wi-Fi adapter is part of every installation. Probe detection starts automatically: it discovers active monitor interfaces and selects the first by name. Hot-plugging or capture failures trigger a retry every ten seconds. Capture permission through Wireshark's `dumpcap` is still required. It only sees the adapter's current channel, not all bands at once. It does not disconnect the laptop's normal Wi-Fi, change interface modes, inject frames, or deauthenticate devices.

No launch flag is required. To override automatic selection when several adapters are present (replace `mon0` with its actual name):

```sh
./run.sh --probe-interface mon0
```

The app checks the interface mode before capture. If permission or hardware is missing, Health & data reports the failure. Configure capture privileges using your Kali/Wireshark installation's supported process; do not run the whole app as root. Use scanning only where you have authorization. Address randomization and intermittent probes mean request counts are not a count of people or unique physical devices.

## Bluetooth adapter selection

```sh
./run.sh --adapter hci0
```

Bluetooth-off, missing adapter, missing permissions, and unavailable BlueZ are reported with automatic retry. Ordinary Wi-Fi discovery requires NetworkManager to manage a Wi-Fi interface. A desktop notification daemon is needed for pop-up alerts; all alerts also appear in Activity.

## Limits and platform differences

This edition ports the monitoring/learning/history workflow, not every Apple-only module. Motion is explicitly user-confirmed: most laptops do not expose the phone's CoreMotion sensors. GPS, RoomPlan, Visual Scout, Apple Multipeer pairing, router quarantine, and cloud sync are not implemented. AEGIS Blue-style detail text explains the observed signal and its uncertainty; the full Swift investigation engine remains in the iPhone/Mac project.

Minimizing the app keeps monitoring active. Closing it or suspending the laptop stops observation. No device discovery proves a person is present, and no quiet result proves the area is safe. BLE names are self-reported. The app only suggests a type when advertised services support that description; a manufacturer identifier alone does not prove a model or ownership.

## Development and checks

```sh
python3 -m unittest discover -s tests -p test_core.py -v
# Requires a graphical session; fixtures are explicitly synthetic and use no radio:
python3 -m unittest discover -s tests -v
# On a Linux CI host with xvfb installed:
xvfb-run -a python3 -m unittest discover -s tests -v
```

Data defaults to `~/.local/share/aegis-field/observations.sqlite3`, or `$XDG_DATA_HOME/aegis-field`. `--data-dir PATH` can isolate a test run. Files are created with owner-only permissions. One app instance owns each data folder.

## Verification — November 9, 2026

Eight tests passed on the development Mac, including real Tk widget creation and table updates using isolated synthetic fixtures. Tests cover trends, isolated spikes, indoor flutter, rapid reversal, gaps, duplicate-time bursts, invalid samples, 1,000 random traces, SQLite restart persistence, baseline review, alert cooldowns, and Wi-Fi/probe parsers. Python compilation and shell syntax checks pass. Bleak 3.1.0 availability was verified.

Live BlueZ, NetworkManager, monitor-adapter capture, notifications, and the installer have **not** been tested on your Kali laptop. This package is ready to transfer and test; a successful physical Kali installation is not claimed.

Implementation references: [Bleak scanner](https://bleak.readthedocs.io/en/latest/api/scanner.html), [Bleak Linux](https://bleak.readthedocs.io/en/latest/backends/linux.html), [NetworkManager nmcli](https://networkmanager.dev/docs/api/latest/nmcli.html), [Wireshark WLAN fields](https://www.wireshark.org/docs/dfref/w/wlan.html).
