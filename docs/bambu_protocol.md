# Bambu Lab LAN protocol

What `pythonsrc/operators/bambu_operator.py` speaks, and what was learned building it
(#73). Two channels: **MQTT over TLS on 8883** for control and state, **implicit FTPS on
990** for files. There is no HTTP API in LAN mode, which is why the connection test is
not a `GET`.

> **Built and verified against firmware `01.09.01.00`** on a P1S. The version is
> load-bearing: Bambu has tightened third-party LAN access repeatedly between releases
> and its firmware cannot be downgraded, so "this works" is a claim about a firmware,
> not about a model. An update was offered on that machine and deliberately not taken.

> **Not yet verified on hardware.** The printer had no DHCP lease when this was written
> (its screen showed `0.0.0.0`). Everything below is from the vendor's documented
> behaviour and the community reference; the hardware checklist lives in #73's pull
> request.

## Developer Mode — the question, and its answer

The plan asked whether Developer Mode gates third-party LAN access on this firmware.

**There is no separate Developer Mode toggle on the P1S.** The only thing on the screen
is **LAN Only Mode**, and its absence does not by itself close the LAN route: the P1S
runs its local MQTT broker in cloud mode too. What remains unverified is the one
question that needs a reachable printer — *does 8883 accept `bblp` + access code while
LAN Only Mode is OFF?* If it refuses, turning LAN Only Mode ON is the A/B, and the
instrument for both is the same: the CONNACK reason code.

## Connection

| | |
|---|---|
| Broker | `<printer_ip>:8883`, MQTT over TLS |
| Username | `bblp` — the only one the firmware accepts |
| Password | the LAN access code, from the printer screen under Settings → Network |
| Files | implicit FTPS on `<printer_ip>:990`, same credentials |

**TLS is not verified, and that is a real limitation rather than an oversight.** The
printer presents a self-signed certificate naming its own serial, so there is no chain
to validate against, and `CERT_NONE` is what every third-party client does. It means the
operator trusts whatever answers on that LAN address; the access code is what actually
authenticates. Pinning the certificate on first connect is the improvement, and it is a
follow-up rather than part of #73.

### Authentication is asynchronous, and this matters

`paho`'s `connect()` completes the TCP and TLS handshake and **returns before the
CONNACK arrives**. The CONNACK is what carries the authentication result, and it is
delivered to `on_connect`. An implementation that connects, sleeps and returns `True`
therefore reports success for a wrong access code — which is what this operator did
until #73, and why the connection test in Printer Setup could only report reachability.

`BambuOperator` waits on the CONNACK and reads its reason code:

| Reason code | Meaning | What the operator says |
|---|---|---|
| `0` | accepted | session opens, subscribes to `report` |
| `4`, `5` | credentials refused | "The Bambu printer refused the LAN access code" |
| no CONNACK | reached, never answered | usually LAN Only Mode off with the printer bound to the cloud |
| socket error | not reached | names the address and port it tried |

`check_credentials()` does exactly this and nothing else — no subscription, and **no
serial required**, because a person setting a printer up has typed an address and a code
and wants to know whether those two are right before they have been anywhere near a
serial. It is what `POST /config/test-connection` calls for `service: "bambu"`.

## Topics

Every topic is keyed on the serial, so a printer without one can be reached and not
addressed.

| Purpose | Topic |
|---|---|
| State, pushed by the printer | `device/<serial>/report` |
| Commands | `device/<serial>/request` |

### Serial discovery

The operator does **not** discover it. `BAMBU_SERIAL` is entered in Printer Setup, where
the IP and access code already are, because #73's design rule is that a person connects
their own printer through the app — no IP, code or serial is in any file in this
repository. The serial is not treated as a secret: it is printed on the machine and it
is in the printer's own TLS certificate.

Reading it from that certificate on connect is the obvious improvement and is left for
the Daedal Link helper, alongside SSDP discovery — neither belongs in the hosted web
app, which has no UDP socket to discover with and cannot reach a home LAN at all.

### Command payloads

Wrapped in `{"print": {...}}`, with a `sequence_id` that the firmware requires and
echoes back in the report. Without one the broker accepts the command and the printer
ignores it, which is the worst of both answers.

```json
{"print": {"sequence_id": "1", "command": "gcode_file", "param": "/sdcard/part.gcode"}}
{"print": {"sequence_id": "2", "command": "stop",   "param": ""}}
{"print": {"sequence_id": "3", "command": "pause",  "param": ""}}
{"print": {"sequence_id": "4", "command": "resume", "param": ""}}
```

## What file the printer prints — the decision

The firmware accepts two forms, and #73's open question 2 was which to use.

* **`gcode_file`** — a plain `.gcode` on the SD card, named by absolute path.
* **`project_file`** — a sliced 3MF, with `url: file:///sdcard/<name>.gcode.3mf` and
  `param: Metadata/plate_1.gcode`.

**We use `gcode_file`.** CuraEngine emits a plain `.gcode` and `gcode_file` prints
exactly that; `project_file` would mean building a 3MF container around our own G-code
for no gain.

The cost is real and is paid in the profile. A Bambu Studio project carries the
machine's own bed levelling and purge sequence, and a raw `gcode_file` does not — so
that sequence has to live in `machine_start_gcode` in `pythonsrc/profiles/bambu_p1s.json`.
That profile's start G-code and its temperatures are **marked unconfirmed in the file
itself**: they are conventional values, not vendor-derived ones, and confirming them
against Bambu Studio's stock P1S profile is on the hardware checklist.

## Report shape

The printer sends one full report and then deltas carrying only what changed, so
`BambuOperator` **merges** rather than replaces — otherwise the bed temperature is lost
the moment a layer number arrives on its own.

| Report field | Read as |
|---|---|
| `gcode_state` | `RUNNING` / `PAUSE` / `FINISH` / `FAILED` / `IDLE` |
| `mc_percent` | progress, % |
| `layer_num` | current layer |
| `subtask_name`, `gcode_file` | the file printing |
| `nozzle_temper`, `nozzle_target_temper` | hotend, °C |
| `bed_temper`, `bed_target_temper` | bed, °C |
| `mc_remaining_time` | remaining, minutes |

`pythonsrc/operators/printer_state.py` maps `gcode_state` into the vocabulary the
dispatch monitor reads. A missing one is `UNKNOWN`, and `UNKNOWN` is never an ending —
which is what makes the few seconds between `connect()` and the first report safe.

## Telemetry

There is no `BambuCollector` yet, so a Bambu dispatch runs unmonitored and says so in
the log. `run_operator.collector_for` returns `None` for this firmware deliberately: a
print with no sample stream still runs, still records its dispatch and still waits for a
person's verdict. Reading `report` into `telemetry_sample` is its own issue, once this
one prints.

## References

* `github.com/Doridian/OpenBambuAPI` — community protocol documentation. Read, not
  imported; no code from it is in this repository.
* The `bambu-labs` skill in `earthtojake/text-to-cad` (MIT) was named in #73 as a
  reference to **port from, not import**. Nothing was copied, so there is no
  `THIRD-PARTY-NOTICES.md` § 2 entry for it; if any code is taken later, that entry is
  part of taking it.
