# Synergy gate processing

One `serverSynergy` process listens on a separate TCP port for each lane.
Synergy connects to Akira on each port; commands and replies use that same
connection. Transport remains compact UTF-8 JSON, one message per LF-terminated
line. Each port accepts one active controller; additional connections are
closed until that controller disconnects.

## Port configuration

Configure the server alongside `driverSynergy` in `etc/akira.cfg`:

```json
"serverSynergy": {
  "bind": "0.0.0.0",
  "lanePorts": {"06": 2070, "07": 2071}
}
```

This object belongs under `driverConfig`. The existing
`driversServer: ["serverSynergy"]` still starts one server process. Port mapping
keys must match configured lane strings. Every served lane requires a port;
unknown lanes, duplicate ports, missing mappings, and ports outside 1–65535
fail startup. All ports are bound before any local dispatch is enabled, so a
bind failure does not start a partially configured service.

The local Unix socket remains `synergy/live.sock`. The driver sends `laneID`
as before; the server selects that lane's connection and bounded queue.
Each lane independently handshakes, polls, retries and reconnects. A missing,
slow or disconnected controller affects only its own lane. Disconnect cleanup
and new submissions are serialized per lane so queued commands cannot cross
into a replacement connection. Commands are never replayed after reconnect.

The server reads the configured map by default. For isolated testing,
`--lane-ports 06=32070,07=32071` overrides it. Server `--lanes 07` selects only
lane 07 and its configured port. Server `--port 32071` (or `AKIRA_PORT`) is
allowed only when exactly one lane is selected. `--bind`/`AKIRA_BIND` overrides
the server bind address. The test client uses the single-port interface below.

## Lane identifiers

Every outgoing command retains `laneID`, including `NOP`, `addQueue`,
`setSignMsg`, and `closeGate`. Replies may omit `laneID`: the receiving port
provides it internally for the driver and status records. Use the exact configured string, preserving leading
zeros: `"06"` and `"07"` are different from `"6"` and `"7"`.

The reader determines the lane from the reader/antenna mapping in `akira.cfg`.
The server and local test client load supported IDs from the same file's `lanes`
list. Server `--lanes 06,07` (or `AKIRA_LANES`) explicitly overrides its supported
IDs when testing another configuration. The test client serves one configured
lane, inferred from its required port argument or specified with `--lane`.

The server rejects local commands with missing or unknown lanes. There is no
broadcast or fallback to another lane. If a reply supplies `laneID`, it must
exactly match the port's lane; a mismatched reply cannot complete an exchange or
update either lane's state. This also applies to unsolicited lane-state updates.

## Commands and responses

For example, a no-tag event in lane 07 sends:

```json
{"op":"setSignMsg","laneID":"07","signMsg":"Tiada Tag","dateTime":"2026-09-05T13:44:02.886+08:00"}
```

The controller responds with lane 07's state:

```json
{"laneID":"07","laneState":1,"gateState":0,"signMsg":"Tiada Tag","queueCount":0}
```

`closeGate` has the same fields as `setSignMsg`, with `op: "closeGate"`. It closes
and clears only the specified lane. `addQueue` retains its transaction metadata
and affects only that lane's queue, gate, and sign.

Heartbeats are also scoped to a lane:

```json
{"op":"NOP","laneID":"06"}
```

The server polls the single lane assigned to a new connection before accepting
local commands for it. It subsequently polls that lane after 200 ms without an
exchange, independently of traffic or timeouts on other connections.

Responses carry the fields shown above, with `laneID` optional on the wire. Each lane has its own
queue, gate, sign, vehicle-passage timers, and duplicate-transaction state in
the test client. Server and test-client status files expose a `lanes` map;
the server's `lastLaneState` is only the most recently received lane snapshot.
Each lane entry also includes its port, connection state, counters, and (on the
server) handshake readiness and current operation. Server top-level `connected`
means all configured lanes are ready; `anyConnected` means at least one TCP
connection exists. Route decisions use the individual lane's readiness, so a
false aggregate `connected` does not disable the other lanes. The test client's
`connected` describes its single socket.

Each `clientSynergyTest.py` process connects to exactly one server port. `--port`
is required; there is no implicit default or multi-port client mode. Run these
in separate terminals after stopping any older multi-port test client:

```bash
bin/clientSynergyTest.py --port 2070
bin/clientSynergyTest.py --port 2071
```

The configured `lanePorts` map supplies the lane ID, so no lane argument is
needed for normal use. For an isolated test port, supply one lane explicitly,
for example `--port 32070 --lane 06`. A configured port cannot be assigned a
different lane, and multiple lane IDs are rejected. `--lanes` remains an alias
for `--lane` but accepts only one ID. Each process reconnects only to its chosen
port and retains only that lane's simulation state.

Default status files are `synergy/client-status-2070.json` and
`synergy/client-status-2071.json`; default locks are
`/tmp/clientSynergyTest-2070.lock` and `/tmp/clientSynergyTest-2071.lock`.
`--status-file` and `--lock-file` can override them. Console records retain the
direction labels, separators, lane and port. `--omit-lane-id` exercises V3
lane-less replies; the response log shows exactly the wire payload.

## Driver calls

```python
driverSynergy.setSignMsg("Tiada Tag", lane="07")
driverSynergy.closeGate(lane="06")
driverSynergy.noTag("07", antenna=1)
```

The driver also includes the original read's lane when a lookup is ineligible
or fails. `noTag` preserves the lane supplied by the reader. The default lane
ID remains empty; omitting a lane does not select another configured lane.

## Activation and limits

Restart `serverSynergy` and the test client to activate the per-lane ports.
This transport change does not require a reader restart. Synergy must connect
to the port assigned to each lane. V3 lane-less replies are supported; outgoing
commands retain their lane IDs and existing transaction metadata.

`laneID` identifies a lane, not a particular request. The separate review finding
about distinguishing duplicate replies to different requests in the same lane
remains open; this change does not add request-ID acknowledgement correlation.

## Gate eligibility

James confirmed the rule on 2026-09-05: the tag must be active and its balance
must be **greater than or equal to the returned fare**. The configured active
status is `1` (`eligibility.allowedStatuses: ["1"]`). Account type, direct debit,
and entitlement flags do not bypass this rule.

Balance and `fare.fareValue` from `getTagStatus` are compared in ringgit using
decimal arithmetic. The outgoing `Fare` remains integer sen. An active tag with
RM3.50 balance and RM3.50 fare qualifies; RM3.49 balance does not. Zero balance
qualifies for a zero fare when the tag is active. `PaidAmount` does not change
the balance requirement. Missing/invalid fare or balance fails closed.

The previous fixed `minimumBalance` setting has been removed. Lookup results
report `requiredBalance` from the returned fare. Existing authentication,
metadata validation, passage deadline and Synergy acknowledgement checks still
apply; Synergy handles billing.

## Fast authorization and stopped-car fallback

The fast antenna is the early authorization opportunity. Each fast sensor
trigger opens the configured RF window, including when the lane ahead is
occupied. Once `fastMinReads` is met, the driver checks active status and balance
against fare. No additional candidate-settling delay is introduced.

If mid and slow were clear at the fast trigger, a valid car can open the gate.
The fast sensor itself is occupied by this car and is not part of that clearance
test. Its subsequent movement into mid does not invalidate the original clear
arrival. If the lane ahead was occupied, the preceding sensor passage must
already have a successful Synergy authorization. The server then polls that
lane with NOP immediately before addQueue and requires an open lane and gate.
An open gate with queue count zero still meets this precondition; the resulting
addQueue acknowledgement must confirm a positive queue as usual. Failure of
the precondition returns `GATE_NOT_OPEN` with `notSent: true` and leaves the car
to use slow fallback. An unvalidated preceding passage returns `LANE_OCCUPIED`.

Slow is the fallback for a car stopped at the gate after fast could not authorize
it. The reader continues opening slow read windows while the slow sensor is
occupied, so the configured `slowPost` is not a permanent cutoff. A fresh read
meeting `slowMinReads` performs the same status/balance/fare checks and can
submit addQueue. Known failures can be retried from fresh RF observations while
stopped, with a one-second minimum retry delay and the existing RF squelch.
There is no deferred replay of an expired lookup or command.

`lanePassage.py` assigns a passage ID at each fast trigger and associates slow
arrivals with those passages in sensor travel order. A missed fast RFID read
still has a sensor passage. Each RFID lookup attempt has its own ID; Synergy's
`txID` is the shared passage ID. Responses update the matching passage and
attempt ID, rather than matching only by TID. A passage already authorized on
fast is not submitted again at slow; slow also waits for a pending fast result.
Authorized tags remain squelched on the slow side while present, preventing a
lingering tag from becoming the next car's fallback candidate.

Each board's `slowClearDebounceMs` (default/MEX: 50 ms) preserves passage identity
through brief slow-sensor clear pulses. Slow authorization pauses immediately
when the sensor clears; the 50 ms debounce delays retiring that passage and
keeps the lane ahead classified occupied during a possible dropout.
This does not delay fast authorization or the initial slow read. A stable slow
clear ends the passage and cancels unsent lookups. The existing 1500 ms all-lane
clear debounce remains separate. `fastClearDebounceMs` (default/MEX: 5 ms)
prevents a brief fast clear/reassertion from creating another arrival; the
initial fast edge still opens its RF window immediately. A new fast arrival
with a clear approach retires any obsolete, unpaired downstream passages.
Startup occupancy is represented as unknown
downstream passages, without assuming those cars were validated before restart.
The sensor ordering and debounce setting should be checked against development
traffic, including close-following cars and long vehicles.

A command with uncertain delivery blocks automatic slow fallback for that
passage (`DELIVERY_UNKNOWN`); reconcile it by txID. A confirmed unsent command
can use a later fresh slow attempt. Synergy continues to own queue decrement,
normal gate closure, and billing.

`_requireOpenGate` is private to the same-host driver/server connection, just
like `_authorizationDeadline`; neither reaches the Synergy receiver. Restart
both reader and server to activate this behavior. The existing limitation about
correlating same-lane responses with individual requests remains open.

## Passage deadlines

`driverConfig.driverSynergy.tagStatus.authorizationMaxAgeSeconds` in `akira.cfg`
sets the maximum read-to-send age (default and MEX setting: **2 seconds**).
The driver subtracts the read's existing age at arrival and uses a monotonic
clock for the remaining budget, covering queueing, HTTP lookup/failover and
local dispatch. Slow uses the latest actual RF observation (`lastSeen`) so a
car waiting at the gate can qualify from fresh reads. It does not renew an old
observation merely because a callback runs later. Reads more than one second
in the future are rejected too.
`resultMaxAgeSeconds` remains the legacy cache age; it does not extend the
passage deadline.

Each lane has its own bounded lookup queue, worker and HTTP session. Delays in
one lane's HTTP lookup do not block another lane. The driver checks freshness
before each API attempt, after lookup and immediately before sending either
`addQueue` or a lookup-failure sign. HTTP timeouts are capped by the remaining
budget; a late response cannot authorize a passage even if an HTTP call itself
outlasts that budget.

`laneClear(lane)` cancels that lane's queued/in-flight lookups. Cancelled or
expired work produces a negative result (`PASSAGE_CANCELLED` or
`PASSAGE_EXPIRED`) without changing the gate or sign. A new read after lane-clear
belongs to a new passage generation.

The driver passes a private `_authorizationDeadline` monotonic timestamp over
the same-host Unix socket. The server strips it before the partner protocol,
limits its local queue deadline, and checks the deadline before each send or
retry. Restart both reader and server to activate the complete deadline path.
A lane-clear cannot recall a command already submitted to the server or partner;
an acknowledgement of an already-submitted command remains an acknowledgement.

## Storage failures and reconciliation

Reader, lookup, dispatch and server status files are best-effort diagnostics.
Their write errors, and logging errors, cannot turn an acknowledged command
into a lookup failure, trigger a second sign command, or kill the lookup worker.
The worker delivers each result before writing lookup-status diagnostics.

Before submitting `addQueue`, the driver records a transaction intent under
`synergy/transactions/<sha256-of-txID>.json`. Each file contains the original
`txID`, command and subsequent transport result. If the initial intent cannot
be written, dispatch fails closed with `AUDIT_UNAVAILABLE` and nothing is sent.
This is distinct from a failure writing an optional status snapshot.

Records have states `acknowledged`, `not_sent`, or `delivery_unknown`.
`acknowledged` records the transport acknowledgement; the driver's result also
checks lane/gate/queue state to decide `gateAuthorized`. A record left at
`delivery_unknown` needs reconciliation against Synergy using its `txID`.

If writing the result fails after dispatch, the returned outcome is preserved
and the driver retries **only the audit-file write** in the background. Pending
audit results are held in bounded process memory; reaching the limit blocks
new authorizations. A process exit before a failed write is recovered leaves
the pre-send intent for manual reconciliation. These files are never a command
queue and are never replayed. Archive reconciled transaction records as part of
operational storage maintenance.
