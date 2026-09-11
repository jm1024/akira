#!/usr/bin/env python3
"""Simulated single-lane controller for Synergy integration testing.

The simulator connects to the Akira ALC server, receives compact LF-delimited
JSON commands, and returns the current lane state. It implements NOP,
addQueue, setSignMsg, and closeGate behavior, deduplicates retransmitted
addQueue txIDs, and simulates queued vehicles passing after a configurable
delay. State is retained across reconnects for the lifetime of the process.
"""

import argparse
import fcntl
import heapq
import json
import os
import signal
import socket
import sys
import time
import threading
from functools import wraps
import traceback
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from synergyProtocol import configured_lane_ids, lane_endpoints, validate_lane_id


DEFAULT_HOST = "127.0.0.1"
DEFAULT_RECONNECT_SECONDS = 2.0
DEFAULT_PASSAGE_SECONDS = 3.0
DEFAULT_MAX_LINE_BYTES = 64 * 1024
DEFAULT_MAX_SEEN_TXIDS = 10000
DEFAULT_SIGN_MESSAGE = "Selamat Datang"
PROJECT_ROOT = Path(
    os.environ.get("AKIRA_ROOT", Path(__file__).resolve().parent.parent)
).resolve()
LOG_LOCK = threading.Lock()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def compact_json(message):
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False)


def log(event, **details):
    record = {"time": utc_now(), "event": event}
    record.update(details)
    label = {
        "server_command_received": "SERVER -> TEST CLIENT (received)",
        "client_response_sent": "TEST CLIENT -> SERVER (sent)",
    }.get(event, "TEST CLIENT (status)")
    with LOG_LOCK:
        print(label + "\n" + compact_json(record) + "\n-------------------------", flush=True)


def atomic_write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, ensure_ascii=False)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def acquire_singleton_lock(lock_file):
    lock_path = Path(lock_file)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError(f"another Akira client owns {lock_file}")
    lock.seek(0)
    lock.truncate()
    lock.write(f"{os.getpid()}\n")
    lock.flush()
    return lock


def status_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return wrapped


class SimulatorStatus:
    COUNTERS = ("messagesReceived", "responsesSent", "responsesDropped", "duplicateAddQueue",
                "passages", "connections", "disconnects", "connectionErrors")

    def __init__(self, path, host, lane_ports):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.last_write = 0.0
        self.data = {
            "startedAt": utc_now(), "host": host, "lanePorts": dict(lane_ports),
            "connected": False, "anyConnected": False,
            "lanes": {lane: dict(laneID=lane, port=port, connected=False,
                                 **{key: 0 for key in self.COUNTERS})
                      for lane, port in lane_ports.items()},
            "lastCommand": None, "lastCommandAt": None,
            **{key: 0 for key in self.COUNTERS},
        }
        self.write(force=True)

    @status_locked
    def update_lane(self, lane_state):
        self.data["lanes"][lane_state["laneID"]].update(lane_state)

    @status_locked
    def write(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_write < 1.0:
            return
        try:
            self.data.pop("statusWriteError", None)
            atomic_write_json(self.path, self.data)
        except Exception as error:
            self.data["statusWriteError"] = str(error)
            log("status_write_failed", error=str(error))
        self.last_write = now

    def _count(self, key, lane_id):
        self.data[key] += 1
        self.data["lanes"][lane_id][key] += 1

    def _connection_summary(self):
        lanes = self.data["lanes"].values()
        self.data["connected"] = all(lane["connected"] for lane in lanes)
        self.data["anyConnected"] = any(lane["connected"] for lane in lanes)
        self.write(force=True)

    @status_locked
    def connected(self, lane_id):
        self.data["lanes"][lane_id]["connected"] = True
        self._count("connections", lane_id)
        self._connection_summary()

    @status_locked
    def disconnected(self, lane_id):
        self.data["lanes"][lane_id]["connected"] = False
        self._count("disconnects", lane_id)
        self._connection_summary()

    @status_locked
    def connection_error(self, lane_id):
        self._count("connectionErrors", lane_id)
        self.write()

    @status_locked
    def command(self, operation, lane_state, duplicate=False):
        lane_id = lane_state["laneID"]
        self.data["lastCommand"] = operation
        self.data["lastCommandLaneID"] = lane_id
        self.data["lastCommandAt"] = utc_now()
        self._count("messagesReceived", lane_id)
        if duplicate:
            self._count("duplicateAddQueue", lane_id)
        self.update_lane(lane_state)
        self.write(force=operation != "NOP")

    @status_locked
    def response(self, lane_id):
        self._count("responsesSent", lane_id)
        self.write()

    @status_locked
    def response_dropped(self, lane_id):
        self._count("responsesDropped", lane_id)
        self.write(force=True)

    @status_locked
    def passage(self, lane_state):
        self._count("passages", lane_state["laneID"])
        self.update_lane(lane_state)
        self.write(force=True)


class LaneSimulator:
    def __init__(
        self,
        lane_state,
        gate_state,
        sign_message,
        passage_seconds,
        max_seen_txids,
        status,
        lane_id,
    ):
        self.lane_id = validate_lane_id(lane_id)
        self.lane_state = lane_state
        self.gate_state = gate_state
        self.sign_message = sign_message
        self.queue_count = 0
        self.passage_seconds = passage_seconds
        self.max_seen_txids = max_seen_txids
        self.status = status
        self.seen_txids = OrderedDict()
        self.passage_deadlines = []
        self.last_passage_deadline = 0.0
        self.status.update_lane(self.state())
        self.status.write(force=True)

    def state(self):
        return {
            "laneID": self.lane_id,
            "laneState": self.lane_state,
            "gateState": self.gate_state,
            "signMsg": self.sign_message,
            "queueCount": self.queue_count,
        }

    def _remember_txid(self, txid):
        self.seen_txids[txid] = None
        self.seen_txids.move_to_end(txid)
        while len(self.seen_txids) > self.max_seen_txids:
            self.seen_txids.popitem(last=False)

    def _schedule_passage(self):
        now = time.monotonic()
        base = max(now, self.last_passage_deadline)
        deadline = base + self.passage_seconds
        heapq.heappush(self.passage_deadlines, deadline)
        self.last_passage_deadline = deadline

    def process_passages(self):
        now = time.monotonic()
        changed = False
        while self.passage_deadlines and self.passage_deadlines[0] <= now:
            heapq.heappop(self.passage_deadlines)
            if self.queue_count > 0:
                self.queue_count -= 1
                changed = True
                if self.queue_count == 0:
                    self.gate_state = 0
                self.status.passage(self.state())
                log("vehicle_passed", laneID=self.lane_id, queueCount=self.queue_count, gateState=self.gate_state)
        if not self.passage_deadlines:
            self.last_passage_deadline = 0.0
        return changed

    def seconds_until_passage(self):
        if not self.passage_deadlines:
            return None
        return max(0.0, self.passage_deadlines[0] - time.monotonic())

    def handle(self, command):
        if not isinstance(command, dict):
            raise ValueError("command must be a JSON object")
        validate_lane_id(command.get("laneID"), (self.lane_id,))

        self.process_passages()
        operation = command.get("op")
        duplicate = False

        if operation == "NOP":
            pass
        elif operation == "addQueue":
            txid = command.get("txID")
            if not isinstance(txid, str) or not txid:
                raise ValueError("addQueue requires a non-empty txID")
            if txid in self.seen_txids:
                duplicate = True
            else:
                self._remember_txid(txid)
                self.queue_count += 1
                self.gate_state = 1
                if isinstance(command.get("signMsg"), str):
                    self.sign_message = command["signMsg"]
                self._schedule_passage()
                if self.queue_count >= 4:
                    log("suspicious_queue_count", laneID=self.lane_id, queueCount=self.queue_count)
        elif operation == "setSignMsg":
            sign_message = command.get("signMsg")
            if not isinstance(sign_message, str):
                raise ValueError("setSignMsg requires signMsg")
            self.sign_message = sign_message
        elif operation == "closeGate":
            sign_message = command.get("signMsg")
            if not isinstance(sign_message, str):
                raise ValueError("closeGate requires signMsg")
            self.sign_message = sign_message
            self.queue_count = 0
            self.gate_state = 0
            self.passage_deadlines.clear()
            self.last_passage_deadline = 0.0
        else:
            log("unknown_command", op=operation)

        lane_state = self.state()
        self.status.command(operation, lane_state, duplicate=duplicate)
        if duplicate:
            log("duplicate_add_queue", laneID=self.lane_id, txID=command.get("txID"))
        return lane_state


class AkiraTestClient:
    def __init__(self, args):
        self.args = args
        self.stop_requested = False
        self.stop_event = threading.Event()
        self.dropped_response_keys = {lane: OrderedDict() for lane in args.lanes}
        self.status = SimulatorStatus(args.status_file, args.host, args.lane_ports)
        self.simulators = {
            lane_id: LaneSimulator(
                lane_id=lane_id,
                lane_state=args.lane_state,
                gate_state=args.gate_state,
                sign_message=args.sign_message,
                passage_seconds=args.passage_seconds,
                max_seen_txids=args.max_seen_txids,
                status=self.status,
            )
            for lane_id in args.lanes
        }

    def process_passages(self, lane_id=None):
        simulators = self.simulators.values() if lane_id is None else [self.simulators[lane_id]]
        for simulator in simulators:
            simulator.process_passages()

    def seconds_until_passage(self):
        waits = [simulator.seconds_until_passage() for simulator in self.simulators.values()]
        return min((wait for wait in waits if wait is not None), default=None)

    def handle_command(self, command, port_lane=None):
        if not isinstance(command, dict):
            raise ValueError("command must be a JSON object")
        lane_id = validate_lane_id(command.get("laneID"), self.simulators)
        if port_lane is not None and lane_id != port_lane:
            raise ValueError(f"command laneID {lane_id!r} does not match port lane {port_lane!r}")
        return self.simulators[lane_id].handle(command)

    def request_stop(self, _signum=None, _frame=None):
        self.stop_requested = True
        self.stop_event.set()

    def _send_state(self, client_socket, lane_state):
        if self.args.response_delay_ms:
            time.sleep(self.args.response_delay_ms / 1000.0)
        wire_state = {key: value for key, value in lane_state.items()
                      if not (self.args.omit_lane_id and key == "laneID")}
        payload = compact_json(wire_state).encode("utf-8") + b"\n"
        client_socket.settimeout(1.0)
        client_socket.sendall(payload)
        self.status.response(lane_state["laneID"])
        return wire_state

    def _should_drop_response(self, command):
        if command.get("op") != self.args.drop_first_response_op:
            return False
        keys = self.dropped_response_keys[command["laneID"]]
        key = compact_json(command)
        if key in keys:
            return False
        keys[key] = None
        while len(keys) > self.args.max_seen_txids:
            keys.popitem(last=False)
        self.status.response_dropped(command["laneID"])
        log("response_dropped_for_test", op=command.get("op"), laneID=command.get("laneID"))
        return True

    def handle_connection(self, client_socket, lane_id, port):
        client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        client_socket.settimeout(0.1)
        buffer = bytearray()

        while not self.stop_requested:
            self.process_passages(lane_id)
            passage_wait = self.simulators[lane_id].seconds_until_passage()
            timeout = 0.1 if passage_wait is None else min(0.1, passage_wait)
            client_socket.settimeout(max(0.001, timeout))

            try:
                chunk = client_socket.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionError("server closed the connection")
            buffer.extend(chunk)

            if len(buffer) > self.args.max_line_bytes and b"\n" not in buffer:
                raise ValueError("unterminated server message exceeds maximum size")

            while b"\n" in buffer:
                raw, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                if not raw.strip():
                    continue
                if len(raw) > self.args.max_line_bytes:
                    log("invalid_server_message", laneID=lane_id, port=port, error="line exceeds maximum size")
                    continue
                try:
                    command = json.loads(raw.decode("utf-8"))
                    if isinstance(command, dict) and command.get("op") != "NOP":
                        log("server_command_received", laneID=lane_id, port=port, command=command)
                    lane_state = self.handle_command(command, port_lane=lane_id)
                    if not self._should_drop_response(command):
                        wire_state = self._send_state(client_socket, lane_state)
                        if command.get("op") != "NOP":
                            log(
                                "client_response_sent",
                                laneID=lane_id, port=port,
                                op=command.get("op"),
                                txID=command.get("txID"),
                                response=wire_state,
                            )
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    log("invalid_server_message", laneID=lane_id, port=port, error=str(error))

    def run_lane(self, lane_id, port):
        exit_code = 0
        while not self.stop_requested:
            was_connected = False
            try:
                log("connecting", host=self.args.host, laneID=lane_id, port=port)
                client_socket = socket.create_connection(
                    (self.args.host, port),
                    timeout=self.args.connect_timeout_seconds,
                )
                self.status.connected(lane_id)
                was_connected = True
                log("connected", host=self.args.host, laneID=lane_id, port=port)
                try:
                    self.handle_connection(client_socket, lane_id, port)
                finally:
                    client_socket.close()
            except Exception as error:
                self.status.connection_error(lane_id)
                if self.args.once and not was_connected:
                    exit_code = 1
                if not self.stop_requested:
                    log("connection_lost", laneID=lane_id, port=port, error=str(error))
                    if self.args.debug:
                        traceback.print_exc()
            finally:
                if was_connected:
                    self.status.disconnected(lane_id)

            if self.args.once or self.stop_requested:
                break
            deadline = time.monotonic() + self.args.reconnect_seconds
            while not self.stop_requested and time.monotonic() < deadline:
                self.process_passages(lane_id)
                self.stop_event.wait(max(0, min(0.1, deadline - time.monotonic())))

        log("lane_client_stopped", laneID=lane_id, port=port)
        return exit_code

    def run(self):
        return self.run_lane(self.args.lanes[0], self.args.port)


def non_negative_float(value):
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def positive_float(value):
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def positive_int(value):
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", "--lanes", dest="lane",
                        help="single lane ID; normally inferred from the configured port")
    parser.add_argument("--omit-lane-id", action="store_true", help="send V3 lane-less replies")
    parser.add_argument("--host", default=os.environ.get("AKIRA_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="server TCP port to connect to (one port per process)",
    )
    parser.add_argument(
        "--reconnect-seconds",
        type=positive_float,
        default=float(
            os.environ.get("AKIRA_RECONNECT_SECONDS", DEFAULT_RECONNECT_SECONDS)
        ),
    )
    parser.add_argument(
        "--connect-timeout-seconds",
        type=positive_float,
        default=3.0,
    )
    parser.add_argument(
        "--passage-seconds",
        type=positive_float,
        default=float(os.environ.get("AKIRA_PASSAGE_SECONDS", DEFAULT_PASSAGE_SECONDS)),
        help="seconds for each queued vehicle to pass",
    )
    parser.add_argument("--lane-state", type=int, default=1)
    parser.add_argument("--gate-state", type=int, choices=(0, 1), default=0)
    parser.add_argument("--sign-message", default=DEFAULT_SIGN_MESSAGE)
    parser.add_argument(
        "--response-delay-ms",
        type=non_negative_float,
        default=0.0,
        help="optional artificial response latency",
    )
    parser.add_argument(
        "--drop-first-response-op",
        choices=("addQueue", "setSignMsg", "closeGate"),
        help="drop the first response for each matching command to test retransmission",
    )
    parser.add_argument(
        "--max-line-bytes",
        type=positive_int,
        default=DEFAULT_MAX_LINE_BYTES,
    )
    parser.add_argument(
        "--max-seen-txids",
        type=positive_int,
        default=DEFAULT_MAX_SEEN_TXIDS,
    )
    parser.add_argument("--status-file", help="default: synergy/client-status-<port>.json")
    parser.add_argument("--lock-file", help="default: /tmp/clientSynergyTest-<port>.lock")
    parser.add_argument("--once", action="store_true", help="do not reconnect")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError("--port must be between 1 and 65535")
        configured = configured_lane_ids(PROJECT_ROOT)
        _bind, ports = lane_endpoints(PROJECT_ROOT, configured)
        port_lane = next((lane for lane, port in ports.items() if port == args.port), None)
        lane = args.lane or port_lane
        if lane is None:
            raise ValueError("port is not mapped in akira.cfg; supply --lane for a test port")
        validate_lane_id(lane, configured)
        if port_lane is not None and lane != port_lane:
            raise ValueError(f"port {args.port} belongs to lane {port_lane}, not {lane}")
        args.lanes = (lane,)
        args.lane_ports = {lane: args.port}
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.error(f"invalid lane configuration: {error}")
    if args.status_file is None:
        args.status_file = str(PROJECT_ROOT / "synergy" / f"client-status-{args.port}.json")
    if args.lock_file is None:
        args.lock_file = f"/tmp/clientSynergyTest-{args.port}.lock"
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        lock = acquire_singleton_lock(args.lock_file)
    except RuntimeError as error:
        print(f"clientAkiraTest: {error}", file=sys.stderr)
        return 1

    client = AkiraTestClient(args)
    signal.signal(signal.SIGINT, client.request_stop)
    signal.signal(signal.SIGTERM, client.request_stop)
    try:
        return client.run()
    except KeyboardInterrupt:
        client.request_stop()
        return 0
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
