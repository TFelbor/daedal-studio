# Bambu Lab LAN protocol

What `pythonsrc/operators/bambu_operator.py` speaks, and what was learned building it
(#73). Two channels: **MQTT over TLS on 8883** for control and state, **implicit FTPS on
990** for files. There is no HTTP API in LAN mode, which is why the connection test is
not a `GET`.

> **Built and verified against firmware `01.09.01.00`** on a P1S. The version is
> load-bearing: Bambu has tightened third-party LAN access repeatedly between releases
> and its firmware cannot be downgraded, so "this works" is a claim about a firmware,
> not about a model. An update was offered on that machine and deliberately not taken.

### What was exercised on the machine, and what was not

An earlier draft of this file said the printer had no DHCP lease and that everything
below came from the vendor's documentation and the community reference. That was true
when it was written and is not true now. Measured on 2026-09-17, so the line between
observed and inferred stays visible:

| | Result |
|---|---|
| **8883** MQTT/TLS, `bblp` + access code | `CONNACK Success`; `Not authorized` with a wrong code |
| **990** implicit FTPS, login and `LIST` | `230`, directory listed |
| **6000** camera | open, not used by this operator |
| TLS certificate CN, both services | `<serial>` — discoverable from the network |
| `pushall` report | 63 keys, including every field in *Report shape* below |

**Not exercised on the machine: `STOR` (an FTPS upload), and `stop` / `pause` /
`resume`.** Those paths are covered by the unit tests and by the vendor's documented
behaviour only. The upload path is the one a person is most likely to reach, since it
is what a dispatch would use — except that this repository does not dispatch to Bambu
firmware; see *What file the printer prints*, below.

## Developer Mode — the question, and its answer

The plan asked whether Developer Mode gates third-party LAN access on this firmware.

**There is no separate Developer Mode toggle on the P1S.** The only thing on the screen
is **LAN Only Mode**, and its absence does not close the LAN route: the P1S runs its
local MQTT broker in cloud mode too.

The one question that needed a reachable printer — *does 8883 accept `bblp` + access
code while LAN Only Mode is OFF?* — is **answered: yes.** The session above was opened
with LAN Only Mode off, and the CONNACK carried `Success`. The A/B the plan proposed
(turn LAN Only Mode on and compare) is therefore unnecessary, and the instrument it
would have used — the CONNACK reason code — is what `check_credentials` reads on every
connection test.

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
{"print": {"sequence_id": "1", "command": "stop",   "param": ""}}
{"print": {"sequence_id": "2", "command": "pause",  "param": ""}}
{"print": {"sequence_id": "3", "command": "resume", "param": ""}}
```

`gcode_file` is documented in the next section and is **not** one of the commands this
repository sends. `BambuOperator.start_print` refuses.

## What file the printer prints — we do not start prints on this firmware

The firmware accepts two forms:

* **`gcode_file`** — a plain `.gcode` on the SD card, named by absolute path.
* **`project_file`** — a sliced 3MF, with `url: file:///sdcard/<name>.gcode.3mf` and
  `param: Metadata/plate_1.gcode`.

#73's open question 2 originally chose `gcode_file`, on the grounds that CuraEngine
emits a plain `.gcode` and `gcode_file` prints exactly that. **That decision is
withdrawn.** The dispatch route for Bambu is the 3MF handoff: the person downloads the
3MF and prints it from Bambu Studio.

The refusal is enforced twice, and the order matters. `BambuOperator.starts_prints` is
`False`, which `POST /jobs/{id}/print-dispatch` reads off the class and answers with a
**409 carrying the sentence above** — before it opens a connection, spawns an operator
or records a dispatch. `BambuOperator.start_print` raising `UnsupportedDispatchError` is
the backstop behind that, and only the backstop: by the time `start_print` is reached,
`upload_file` has already written a start-sequence-less `.gcode` to the printer's SD
card, which is the outcome the refusal exists to prevent.

The reason is not a missing purge line. Reading the machine's own Bambu-Studio-sliced
file off its SD card on 2026-09-17 showed how the start sequence actually invokes
levelling:

```gcode
;===== bed leveling ==================================
M1002 judge_flag g29_before_print_flag
M622 J1
    G29 A X{first_layer_print_min[0]} Y{...} I{...} J{...}
    M400
    M500 ; save cali data
M623
```

`M622 J1 … M623` is a **firmware-evaluated conditional** on a flag the *print command*
sets, not something the file decides. The same scaffolding wraps the timelapse block and
the post-wipe re-home. So a raw `gcode_file` runs none of the machine's start behaviour —
no `G29`, no nozzle wipe, no `M970.3` resonance sweep, no `M620`/`M621` AMS handshake,
no `M975` vibration suppression — and the only way to obtain it is to reproduce roughly
250 lines of Bambu's own macro.

That is a licence decision as well as a physical one: BambuStudio is AGPL-3.0 and this
repository is Apache-2.0, and taking the text from a sliced file on our own printer does
not change its provenance — the unrendered `{if filament_type[initial_extruder]=="PLA"}`
placeholders in that file are the proof it is Bambu's template. PR #148 reverted the
first attempt over the physical hazard alone.

`pythonsrc/profiles/bambu_p1s.json` therefore carries **no** `machine_start_gcode` and no
`machine_end_gcode`. It keeps the machine geometry, which is what the printability gate
reads.

**What is still supported, and why the operator is worth having:** the MQTT state feed is
**printer-wide, not session-scoped**. A print a person starts from Bambu Studio is fully
observable here — `gcode_state`, `mc_percent`, `layer_num`, `total_layer_num`, both
temperatures — so the telemetry loop, and with it the fit-verdict and calibration work,
closes without this repository ever starting a print. `cancel_print`, `pause_print` and
`resume_print` act on whatever is running, whoever started it.

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

There is no `BambuCollector` yet, so nothing on this firmware reaches `telemetry_sample`.
`run_operator.collector_for` returns `None` for it deliberately, and says so in the log
rather than opening a socket that stays silent.

What makes that a gap worth closing rather than a dead end: the `report` feed is
**printer-wide, not session-scoped**. A print started from Bambu Studio — which is how
prints start on this firmware, see above — pushes `gcode_state`, `mc_percent`,
`layer_num`, `total_layer_num` and both temperatures to any authenticated subscriber.
Reading that into `telemetry_sample` is the follow-up, and it needs nothing from this
repository's dispatch path, because there is no Bambu dispatch path.

## References

* `github.com/Doridian/OpenBambuAPI` — community protocol documentation. Read, not
  imported; no code from it is in this repository.
* The `bambu-labs` skill in `earthtojake/text-to-cad` (MIT) was named in #73 as a
  reference to **port from, not import**. Nothing was copied, so there is no
  `THIRD-PARTY-NOTICES.md` § 2 entry for it; if any code is taken later, that entry is
  part of taking it.
