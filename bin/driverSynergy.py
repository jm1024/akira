#!/usr/bin/env python3
"""Synergy driver for immediate RFID authorization and lane commands.

An accepted fast-side reader observation triggers a non-blocking balance/status
lookup and, when eligible, immediately submits ``addQueue`` to Synergy. Slow
reads provide the stopped-car fallback for the same sensor passage. A read
is reported valid only after the lane controller confirms that the lane and gate
are open and the queue is non-empty. Each passage can submit once successfully;
an uncertain delivery cannot be retried by fallback. MCP is not in this path.
"""

from collections import OrderedDict
import hashlib
import json
import math
import os
import queue
import re
import socket
import threading
import time
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import akiraCore
from synergyProtocol import validate_transaction_fields


PROJECT_ROOT = Path(
    os.environ.get("AKIRA_ROOT", Path(__file__).resolve().parent.parent)
).resolve()
DEFAULT_DATA_DIR = str(PROJECT_ROOT / "synergy")
DEFAULT_LANE_ID = ""
DEFAULT_CONCESSION_ID = "SP"
DEFAULT_PLAZA_CODE = "001"
DEFAULT_LANE_CODE = "S08"
DEFAULT_SIGN_MESSAGE = "Selamat Datang"
DEFAULT_NO_TAG_MESSAGE = "Tiada Tag"
DEFAULT_TIMEZONE_OFFSET = "+08:00"
DEFAULT_LOOKUP_MAX_AGE_SECONDS = 30.0
DEFAULT_AUTHORIZATION_MAX_AGE_SECONDS = 2.0
DEFAULT_LOOKUP_QUEUE_SIZE = 256
DEFAULT_MAX_SEEN_TXIDS = 10000
DEFAULT_DISPATCH_TIMEOUT_SECONDS = 0.5
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024
TAG_INAUTHENTIC = "INAUTHENTIC"


def _safe_log(message):
    try:
        akiraCore.log(message)
    except Exception:
        try:
            os.write(2, (message + "\n").encode("utf-8", errors="replace"))
        except Exception:
            pass


def _write_diagnostic(path, value):
    try:
        _atomic_write_json(path, value)
        return True
    except Exception as error:
        _safe_log(f"driverSynergy could not write {path}: {error}")
        return False


def _timezone_from_offset(value):
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value)
    if not match:
        raise ValueError("timezone offset must use +HH:MM or -HH:MM")
    hours, minutes = int(match.group(2)), int(match.group(3))
    if hours > 23 or minutes > 59:
        raise ValueError("invalid timezone offset")
    delta = timedelta(hours=hours, minutes=minutes)
    if match.group(1) == "-":
        delta = -delta
    return timezone(delta)


def _as_datetime(value, default_timezone):
    if value is None or value == "":
        parsed = datetime.now(default_timezone)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    else:
        raise ValueError("date must be a datetime or ISO-8601 string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_timezone)
    return parsed


def _atomic_write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _safe_filename(value):
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-.")
    return cleaned[:80] or uuid.uuid4().hex


def _first_value(mappings, names):
    """Return the first matching response field, ignoring key case."""
    wanted = {name.lower() for name in names}
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        for key, value in mapping.items():
            if str(key).lower() in wanted:
                return value
    return None


def _decimal(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error


def _driver_config():
    drivers = akiraCore.config.get("driverConfig", {})
    if not isinstance(drivers, dict):
        raise ValueError("driverConfig must be an object")
    config = drivers.get("driverSynergy", {})
    if not isinstance(config, dict):
        raise ValueError("driverConfig.driverSynergy must be an object")
    return config


def _integer_code(value, field):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{field} must be an integer or integer string")
    if not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError(f"{field} must be an unsigned integer")
    return int(value)


def _fare_sen(value):
    amount = _decimal(value, "fareValue")
    if not amount.is_finite() or amount < 0:
        raise ValueError("fareValue must be finite and non-negative")
    sen = amount * 100
    if sen != sen.to_integral_value():
        raise ValueError("fareValue must not contain fractional sen")
    return int(sen)


class AkiraDriver:
    def __init__(
        self,
        data_dir=DEFAULT_DATA_DIR,
        lane_id=DEFAULT_LANE_ID,
        concession_id=DEFAULT_CONCESSION_ID,
        plaza_code=DEFAULT_PLAZA_CODE,
        lane_code=DEFAULT_LANE_CODE,
        sign_message=DEFAULT_SIGN_MESSAGE,
        no_tag_message=DEFAULT_NO_TAG_MESSAGE,
        timezone_offset=DEFAULT_TIMEZONE_OFFSET,
        driver_config=None,
        http_session=None,
    ):
        self.data_dir = Path(data_dir)
        self.dispatch_socket = self.data_dir / "live.sock"
        self.dispatch_status = self.data_dir / "dispatch-status.json"
        self.reader_status = self.data_dir / "reader-status.json"
        self.transaction_status = self.data_dir / "transaction-status.json"
        self.tag_status_dir = self.data_dir / "tag-status"
        self.lookup_status = self.data_dir / "tag-status.json"
        self.lane_id = lane_id
        self.concession_id = concession_id
        self.plaza_code = plaza_code
        self.lane_code = lane_code
        self.sign_message = sign_message
        self.no_tag_message = no_tag_message
        self.default_timezone = _timezone_from_offset(timezone_offset)

        driver_config = dict(driver_config or {})
        tag_status = driver_config.get("tagStatus", {})
        eligibility = driver_config.get("eligibility", {})
        dispatch = driver_config.get("dispatch", {})
        if not isinstance(tag_status, dict):
            raise ValueError("driverSynergy.tagStatus must be an object")
        if not isinstance(eligibility, dict):
            raise ValueError("driverSynergy.eligibility must be an object")
        if not isinstance(dispatch, dict):
            raise ValueError("driverSynergy.dispatch must be an object")

        try:
            self.dispatch_timeout = float(
                dispatch.get("timeoutSeconds", DEFAULT_DISPATCH_TIMEOUT_SECONDS)
            )
            self.max_response_bytes = int(
                dispatch.get("maxResponseBytes", DEFAULT_MAX_RESPONSE_BYTES)
            )
        except (TypeError, ValueError) as error:
            raise ValueError("Synergy dispatch timeout and response limit must be numeric") from error
        if self.dispatch_timeout <= 0:
            raise ValueError("driverSynergy.dispatch.timeoutSeconds must be positive")
        if self.max_response_bytes <= 0:
            raise ValueError("driverSynergy.dispatch.maxResponseBytes must be positive")

        endpoints = tag_status.get("endpoints", [])
        if not isinstance(endpoints, list) or not endpoints:
            raise ValueError("driverSynergy.tagStatus.endpoints must be a non-empty list")
        self.tag_status_endpoints = []
        for endpoint in endpoints:
            if not isinstance(endpoint, str) or not endpoint.strip():
                raise ValueError("tag-status endpoints must be non-empty strings")
            self.tag_status_endpoints.append(endpoint.strip())

        self.tag_status_method = str(tag_status.get("method", "POST")).upper()
        if self.tag_status_method not in ("GET", "POST"):
            raise ValueError("driverSynergy.tagStatus.method must be GET or POST")

        request_config = tag_status.get("request", {})
        if not isinstance(request_config, dict):
            raise ValueError("driverSynergy.tagStatus.request must be an object")
        self.tag_status_op = str(request_config.get("op", "")).strip()
        self.tag_status_tid_parameter = str(
            request_config.get("tidParameter", "")
        ).strip()
        if not self.tag_status_op or not self.tag_status_tid_parameter:
            raise ValueError("tag-status request op and tidParameter are required")
        self.tag_status_plaza = request_config.get("plaza", "")
        if not isinstance(self.tag_status_plaza, str):
            raise ValueError("tag-status request plaza must be a string")
        self.tag_status_plaza = self.tag_status_plaza.strip()

        try:
            self.tag_status_timeout = float(tag_status.get("timeoutSeconds", 2))
            self.lookup_max_age = float(
                tag_status.get("resultMaxAgeSeconds", DEFAULT_LOOKUP_MAX_AGE_SECONDS)
            )
            self.authorization_max_age = float(tag_status.get(
                "authorizationMaxAgeSeconds", DEFAULT_AUTHORIZATION_MAX_AGE_SECONDS
            ))
        except (TypeError, ValueError) as error:
            raise ValueError("tag-status timeout and result age must be numeric") from error
        if any(not math.isfinite(value) or value <= 0 for value in (
            self.tag_status_timeout, self.lookup_max_age, self.authorization_max_age,
            self.dispatch_timeout,
        )):
            raise ValueError("tag-status timeout and result age must be positive")

        self.fail_mode = str(tag_status.get("failMode", "closed")).lower()
        if self.fail_mode not in ("closed", "open"):
            raise ValueError("driverSynergy.tagStatus.failMode must be closed or open")

        allowed_statuses = eligibility.get("allowedStatuses", [])
        if not isinstance(allowed_statuses, list) or not allowed_statuses:
            raise ValueError("driverSynergy.eligibility.allowedStatuses must be a non-empty list")
        self.allowed_statuses = {
            str(status).strip().upper() for status in allowed_statuses
            if str(status).strip()
        }
        if not self.allowed_statuses:
            raise ValueError("driverSynergy eligibility has no usable allowed status")

        self.http = http_session
        self.lookup_queues = {}
        self.response_queue = queue.Queue()
        self.worker_lock = threading.RLock()
        self.workers = {}
        self.lane_generations = {}
        self.passage_results = OrderedDict()
        self.ended_passages = OrderedDict()
        self.paused_passages = set()
        self.audit_pending = {}
        self.audit_lock = threading.Lock()
        self.audit_worker = None
        self.seen_txids = OrderedDict()
        self.seen_txids_lock = threading.Lock()

        if not isinstance(lane_id, str):
            raise ValueError("Akira default lane ID must be a string")
        if not all(isinstance(value, str) and value for value in (
            concession_id, plaza_code, lane_code, sign_message,
        )):
            raise ValueError("Akira deployment identifiers and sign message are required")

    def _start_worker(self, lane):
        with self.worker_lock:
            jobs = self.lookup_queues.setdefault(lane, queue.Queue(maxsize=DEFAULT_LOOKUP_QUEUE_SIZE))
            worker = self.workers.get(lane)
            if worker is not None and worker.is_alive():
                return jobs
            worker = threading.Thread(
                target=self._lookup_worker,
                args=(jobs, self.http or requests.Session()),
                name=f"driverSynergyTagStatus-{lane}",
                daemon=True,
            )
            self.workers[lane] = worker
            worker.start()
            return jobs

    def _expired(self, job):
        with self.worker_lock:
            if (job["lane"], job.get("passageID")) in self.ended_passages:
                return self._local_failure(job, "PASSAGE_CANCELLED", "Vehicle left the gate sensor")
            if (job["lane"], job.get("passageID")) in self.paused_passages:
                return self._local_failure(job, "PASSAGE_PAUSED", "Gate sensor is clear")
            if job.get("generation") != self.lane_generations.get(job["lane"], 0):
                return self._local_failure(job, "PASSAGE_CANCELLED", "Lane cleared before dispatch")
        if time.monotonic() >= job["deadline"]:
            return self._local_failure(job, "PASSAGE_EXPIRED", "Read exceeded authorization deadline")
        return None

    def _retry_audits(self):
        while True:
            time.sleep(1)
            with self.audit_lock:
                pending = list(self.audit_pending.items())
                if not pending:
                    self.audit_worker = None
                    return
            for path, record in pending:
                if _write_diagnostic(path, record):
                    with self.audit_lock:
                        self.audit_pending.pop(path, None)

    def _record_dispatch(self, path, record):
        if _write_diagnostic(path, record):
            return
        with self.audit_lock:
            self.audit_pending[path] = record
            if self.audit_worker is None:
                self.audit_worker = threading.Thread(
                    target=self._retry_audits, name="driverSynergyAudit", daemon=True
                )
                self.audit_worker.start()

    def _timestamp(self, value=None):
        return _as_datetime(value, self.default_timezone).astimezone(
            self.default_timezone
        )

    def _dispatch_failure(self, command, code, error, started_at):
        return {
            "ok": False,
            "code": code,
            "operation": command.get("op"),
            "requestedAt": started_at,
            "respondedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "error": str(error),
        }

    def _dispatch(self, command, job=None):
        """Send one live command; never persist it for deferred delivery."""
        started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        audit_path = None
        if command.get("op") == "addQueue":
            audit_path = self.data_dir / "transactions" / (
                hashlib.sha256(command["txID"].encode("utf-8")).hexdigest() + ".json"
            )
            # Write intent before sending. An unfinished record means delivery is
            # unknown and needs reconciliation; it must never be replayed.
            try:
                with self.audit_lock:
                    if len(self.audit_pending) >= DEFAULT_MAX_SEEN_TXIDS:
                        raise OSError("transaction audit retry buffer is full")
                _atomic_write_json(audit_path, {
                    "state": "delivery_unknown", "requestedAt": started_at,
                    "command": command,
                })
            except Exception as error:
                _safe_log(f"driverSynergy cannot record transaction intent: {error}")
                return self._dispatch_failure(command, "AUDIT_UNAVAILABLE", error, started_at)
        local_command = dict(command)
        if job is not None:
            local_command["_authorizationDeadline"] = job["deadline"]
            if job.get("requireOpenGate"):
                local_command["_requireOpenGate"] = True
        payload = json.dumps(
            local_command, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8") + b"\n"
        result = None
        send_attempted = False
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(self.dispatch_timeout)
        try:
            client.connect(str(self.dispatch_socket))
            # Serialize the final check/send with lane_clear; no lock is held
            # while waiting for Synergy's acknowledgement.
            with self.worker_lock:
                expired = self._expired(job) if job is not None else None
                if expired:
                    result = self._dispatch_failure(command, expired["code"], expired["name"], started_at)
                else:
                    if job is not None:
                        client.settimeout(min(self.dispatch_timeout, max(0.001, job["deadline"] - time.monotonic())))
                    send_attempted = True
                    client.sendall(payload)
            if result is None:
                response = bytearray()
                while b"\n" not in response:
                    chunk = client.recv(4096)
                    if not chunk:
                        raise ConnectionError("serverSynergy closed the live dispatch socket")
                    response.extend(chunk)
                    if len(response) > self.max_response_bytes:
                        raise ValueError("serverSynergy response exceeds configured size")
                raw, _, _remainder = response.partition(b"\n")
                result = json.loads(raw.decode("utf-8"))
                if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
                    raise ValueError("serverSynergy returned an invalid dispatch response")
        except FileNotFoundError as error:
            result = self._dispatch_failure(
                command, "SERVER_UNAVAILABLE", error, started_at
            )
        except (ConnectionRefusedError, ConnectionError, socket.timeout, OSError) as error:
            code = "TIMEOUT" if isinstance(error, socket.timeout) else "SERVER_UNAVAILABLE"
            result = self._dispatch_failure(command, code, error, started_at)
        except Exception as error:
            result = self._dispatch_failure(
                command, "INVALID_RESPONSE", error, started_at
            )
        finally:
            client.close()

        status = {
            "recordedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "command": command,
            "result": result,
        }
        result["sendAttempted"] = send_attempted
        if audit_path is not None:
            self._record_dispatch(audit_path, dict(status, state=(
                "acknowledged" if result.get("ok") else
                "not_sent" if not send_attempted or result.get("notSent") else "delivery_unknown"
            )))
        _write_diagnostic(self.dispatch_status, status)
        if not result.get("ok"):
            _safe_log(
                f"driverSynergy live dispatch failed op:{command.get('op')} "
                f"code:{result.get('code')} error:{result.get('error', '')}"
            )
        return result

    def _msg_id(self, timestamp):
        local = timestamp.astimezone(self.default_timezone)
        milliseconds = local.strftime("%f")[:3]
        return (
            f"{self.concession_id}{self.plaza_code}{self.lane_code}"
            f"{local:%Y%m%d%H%M%S}{milliseconds}"
        )

    def _tag_status_path(self, lane, tag_id):
        return self.tag_status_dir / (
            f"{_safe_filename(lane)}-{_safe_filename(tag_id)}.json"
        )

    def _store_lookup(self, result):
        _write_diagnostic(self.lookup_status, result)
        _write_diagnostic(
            self._tag_status_path(result.get("lane", ""), result.get("tid", "")),
            result,
        )

    def _lookup_failure(self, job, error, attempts):
        return {
            "id": str(job["id"]),
            "type": "tagResult",
            "tid": str(job["tid"]),
            "lane": str(job["lane"]),
            "passageID": job.get("passageID"),
            "side": job.get("side"),
            "date": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "valid": False,
            "eligible": False,
            "code": "LOOKUP_ERROR",
            "name": "Tag status lookup failed",
            "outcome": "error",
            "error": str(error),
            "attempts": attempts,
        }

    def _evaluate_lookup(self, job, response_data, endpoint, attempts):
        tag = response_data.get("tag")
        body = response_data.get("body")
        data = response_data.get("data")
        mappings = [tag, body, data, response_data]

        response_tid = _first_value(
            mappings, ("tid", "tagID", "TagID", "tagId")
        )
        if response_tid not in (None, "") and str(response_tid) != str(job["tid"]):
            raise ValueError("tag-status response TID does not match request")

        api_error = str(
            response_data.get("error") or response_data.get("message") or ""
        ).strip()
        if tag is None and api_error.lower() == "tag not found":
            return {
                "id": str(job["id"]),
                "type": "tagResult",
                "tid": str(job["tid"]),
                "lane": str(job["lane"]),
                "date": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "valid": False,
                "eligible": False,
                "code": "TAG_NOT_FOUND",
                "name": "Tag not found",
                "outcome": "ineligible",
                "tagStatus": None,
                "balance": None,
                "requiredBalance": None,
                "endpoint": endpoint,
                "attempts": attempts,
            }

        status_value = _first_value(
            mappings, ("status", "tagStatus", "TagStatus")
        )
        balance_value = _first_value(
            mappings, ("balance", "acctBal", "AcctBal", "accountBalance")
        )
        if status_value in (None, ""):
            raise ValueError("tag-status response is missing status")
        if balance_value in (None, ""):
            raise ValueError("tag-status response is missing balance")

        status = str(status_value).strip().upper()
        balance = _decimal(balance_value, "balance")
        if not balance.is_finite():
            raise ValueError("balance must be finite")

        fare = response_data.get("fare")
        if not isinstance(fare, dict):
            raise ValueError("tag-status response is missing fare data")
        if self.tag_status_plaza and str(fare.get("plazaCode", "")) != self.tag_status_plaza:
            raise ValueError("fare plaza does not match the configured lookup plaza")
        fare_sen = _fare_sen(fare.get("fareValue"))
        # API balance and fareValue are ringgit; wire Fare is integer sen.
        # Account product does not bypass the active-tag/sufficient-balance rule.
        required_balance = Decimal(fare_sen) / Decimal(100)
        status_allowed = status in self.allowed_statuses
        balance_allowed = balance >= required_balance
        valid = status_allowed and balance_allowed

        if not status_allowed:
            code = f"STATUS_{status or 'UNKNOWN'}"
            name = f"Tag status {status or 'unknown'} is not allowed"
        elif not balance_allowed:
            code = "INSUFFICIENT_BALANCE"
            name = "Tag balance is below the fare"
        else:
            code = "00"
            name = "Eligible tag"

        result = {
            "id": str(job["id"]),
            "type": "tagResult",
            "tid": str(job["tid"]),
            "lane": str(job["lane"]),
            "date": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "valid": valid,
            "eligible": valid,
            "code": code,
            "name": name,
            "outcome": "eligible" if valid else "ineligible",
            "tagStatus": status,
            "balance": float(balance),
            "requiredBalance": float(required_balance),
            "fareDetails": dict(fare),
            "endpoint": endpoint,
            "attempts": attempts,
        }

        if valid:
            fields = {
                "TagStatus": _integer_code(status_value, "TagStatus"),
                "AccountType": _integer_code(_first_value(mappings, ("type", "accountType")), "AccountType"),
                "VehiclePlateNo": _first_value(mappings, ("vehiclePlateNum", "vehiclePlateNo")),
                "TcClass": _integer_code(fare.get("vehicleClass"), "TcClass"),
                "Fare": fare_sen,
                "EntryLane": _integer_code(job.get("lane"), "EntryLane"),
            }
            fields["VehicleClass"] = _integer_code(
                job.get("VehicleClass", fields["TcClass"]), "VehicleClass"
            )
            fields["PaidAmount"] = _integer_code(
                job.get("PaidAmount", fields["Fare"]), "PaidAmount"
            )
            validate_transaction_fields(fields)
            result["synergyFields"] = fields
        return result

    def _perform_lookup(self, job, http):
        payload = {
            "op": self.tag_status_op,
            self.tag_status_tid_parameter: str(job["tid"]),
        }
        if self.tag_status_plaza:
            payload["plaza"] = self.tag_status_plaza
        failures = []
        for attempt, endpoint in enumerate(self.tag_status_endpoints, start=1):
            expired = self._expired(job)
            if expired:
                return expired
            try:
                request_args = {
                    "method": self.tag_status_method,
                    "url": endpoint,
                    "timeout": min(self.tag_status_timeout, max(0.001, job["deadline"] - time.monotonic())),
                }
                if self.tag_status_method == "GET":
                    request_args["params"] = payload
                else:
                    request_args["json"] = payload
                response = http.request(**request_args)
                response.raise_for_status()
                response_data = response.json()
                if not isinstance(response_data, dict):
                    raise ValueError("tag-status response must be a JSON object")
                return self._evaluate_lookup(
                    job, response_data, endpoint, attempt
                )
            except Exception as error:
                failures.append(f"{endpoint}: {error}")

        return self._lookup_failure(job, "; ".join(failures), len(failures))

    def _claim_txid(self, tx_id):
        """Claim a reader transaction once, with bounded process-local memory."""
        with self.seen_txids_lock:
            if tx_id in self.seen_txids:
                self.seen_txids.move_to_end(tx_id)
                return False
            self.seen_txids[tx_id] = None
            while len(self.seen_txids) > DEFAULT_MAX_SEEN_TXIDS:
                self.seen_txids.popitem(last=False)
            return True

    def _local_failure(self, job, code, name):
        return {
            "id": str(job["id"]),
            "type": "tagResult",
            "tid": str(job.get("tid") or ""),
            "lane": str(job.get("lane") or ""),
            "passageID": job.get("passageID"),
            "side": job.get("side"),
            "date": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "valid": False,
            "eligible": False,
            "gateAuthorized": False,
            "code": code,
            "name": name,
            "outcome": "ineligible",
        }

    @staticmethod
    def _authentication_valid(job):
        """Unknown is normal when reader authentication is disabled or still pending."""
        return (
            job.get("tidAuthentic") != TAG_INAUTHENTIC
            and job.get("pwAuthentic") != TAG_INAUTHENTIC
        )

    def _authorize_read(self, job, result):
        expired = self._expired(job)
        if expired:
            return expired
        timestamp = self._timestamp(job.get("date"))
        tx_id = str(job.get("passageID") or job["id"])
        msg_id = str(job.get("msgID") or self._msg_id(timestamp))
        command = {
            "op": "addQueue",
            "txID": tx_id,
            "tagID": str(job["tid"]),
            # The reader resolves this lane from the configured antenna mapping.
            "laneID": str(job.get("lane") or self.lane_id),
            "msgID": msg_id,
            "signMsg": str(job.get("signMsg") or self.sign_message),
            "dateTime": timestamp.isoformat(timespec="milliseconds"),
        }
        command.update(result["synergyFields"])
        validate_transaction_fields(command)
        dispatch = self._dispatch(command, job=job)
        response = dispatch.get("response") if isinstance(dispatch, dict) else None
        response = response if isinstance(response, dict) else {}

        acknowledgement_error = None
        if not dispatch.get("ok"):
            acknowledgement_error = str(dispatch.get("code") or "DISPATCH_FAILED")
        elif response.get("laneID") != command["laneID"]:
            acknowledgement_error = "LANE_MISMATCH"
        elif response.get("laneState") != 1:
            acknowledgement_error = "LANE_NOT_OPEN"
        elif response.get("gateState") != 1:
            acknowledgement_error = "GATE_NOT_OPEN"
        elif (
            isinstance(response.get("queueCount"), bool)
            or not isinstance(response.get("queueCount"), int)
            or response.get("queueCount") < 1
        ):
            acknowledgement_error = "QUEUE_NOT_INCREMENTED"

        result = dict(result)
        result.update({
            "lookupCode": result.get("code"),
            "eligible": True,
            "gateAuthorized": acknowledgement_error is None,
            "txID": tx_id,
            "msgID": msg_id,
            "dispatch": dispatch,
            "deliveryUncertain": (
                acknowledgement_error is not None
                and not dispatch.get("notSent")
                and dispatch.get("sendAttempted", True)
                and dispatch.get("code") not in (
                    "DISCONNECTED", "BUSY", "INVALID_COMMAND", "AUDIT_UNAVAILABLE",
                    "PASSAGE_CANCELLED", "PASSAGE_EXPIRED", "PASSAGE_PAUSED",
                )
            ),
        })
        if acknowledgement_error is None:
            result.update({
                "valid": True,
                "code": "00",
                "name": "Tag authorized and queued by Synergy",
                "outcome": "authorized",
            })
        else:
            result.update({
                "valid": False,
                "code": acknowledgement_error,
                "name": "Synergy did not confirm an open queued lane",
                "outcome": "authorization_error",
            })
        return result

    def _passage_result(self, job):
        with self.worker_lock:
            return self.passage_results.get((job["lane"], job.get("passageID")))

    def _authorize_passage(self, job, result):
        if job.get("side") == "fast" and not job.get("laneClearAtFast", True):
            with self.worker_lock:
                previous = self.passage_results.get((job["lane"], job.get("previousPassageID")))
            if not previous or not previous.get("gateAuthorized"):
                return dict(result, valid=False, gateAuthorized=False,
                            code="LANE_OCCUPIED", outcome="authorization_error",
                            name="Lane occupied without a validated preceding car")
            job["requireOpenGate"] = True
        result = self._authorize_read(job, result)
        if result.get("gateAuthorized") or result.get("deliveryUncertain"):
            with self.worker_lock:
                key = (job["lane"], job.get("passageID"))
                self.passage_results[key] = result
                self.passage_results.move_to_end(key)
                while len(self.passage_results) > DEFAULT_MAX_SEEN_TXIDS:
                    self.passage_results.popitem(last=False)
        return result

    def _lookup_worker(self, jobs, http):
        while True:
            job = jobs.get()
            try:
                existing = self._passage_result(job)
                if existing:
                    code = "ALREADY_AUTHORIZED" if existing.get("gateAuthorized") else "DELIVERY_UNKNOWN"
                    result = dict(self._local_failure(job, code, "Passage already submitted to Synergy"),
                                  suppressSign=True, authorizedTid=existing.get("tid"),
                                  deliveryUncertain=bool(existing.get("deliveryUncertain")))
                else:
                    result = self._expired(job) or job.get("precheck") or self._perform_lookup(job, http)
                result = self._expired(job) or result
                if result.get("valid") is True:
                    result = self._authorize_passage(job, result)
                if result.get("eligible") is not True and not result.get("suppressSign") and not self._expired(job):
                    result["eligible"] = False
                    result["gateAuthorized"] = False
                    result["signDispatch"] = self.set_sign_msg(
                        self.no_tag_message, job.get("date"), lane=job.get("lane"), job=job
                    )
            except Exception as error:
                result = self._lookup_failure(job, error, 0)
            result.update(passageID=job.get("passageID"), side=job.get("side"))
            # Deliver the actual outcome before touching optional diagnostics.
            self.response_queue.put(result)
            try:
                self._store_lookup(result)
                if result["outcome"] == "error":
                    _safe_log(
                        f"driverSynergy getTagStatus failed lane:{result['lane']} "
                        f"tid:{result['tid']} {result.get('error', '')}"
                    )
            except Exception as error:
                _safe_log(f"driverSynergy could not store tag status: {error}")
            finally:
                jobs.task_done()

    def get_responses(self):
        responses = []
        while True:
            try:
                responses.append(self.response_queue.get_nowait())
            except queue.Empty:
                break
            else:
                self.response_queue.task_done()
        return responses

    def _load_lookup(self, lane, tag_id):
        path = self._tag_status_path(lane, tag_id)
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
            completed = _as_datetime(result.get("date"), timezone.utc)
            age = (datetime.now(timezone.utc) - completed.astimezone(timezone.utc)).total_seconds()
            if age < 0 or age > self.lookup_max_age:
                return None, "tag-status result is stale"
            if str(result.get("tid", "")) != str(tag_id):
                return None, "tag-status result has the wrong TID"
            if str(result.get("lane", "")) != str(lane):
                return None, "tag-status result has the wrong lane"
            return result, str(result.get("name") or result.get("outcome") or "lookup result")
        except FileNotFoundError:
            return None, "no tag-status result"
        except Exception as error:
            return None, f"invalid tag-status result: {error}"

    def read(self, data):
        """Authorize a fast read or a tracked stopped-car fallback asynchronously."""
        side = str(data.get("side") or "").lower()
        # A stopped car's first observation can be old; use its latest actual
        # RF observation, not the time the callback happens to run.
        timestamp = self._timestamp(data.get("lastSeen", data.get("date")) if side == "slow" else data.get("date"))
        with self.worker_lock:
            generation = self.lane_generations.get(str(data.get("lane") or ""), 0)
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        deadline = time.monotonic() + self.authorization_max_age - max(0, age)
        observation = {
            "recordedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "id": str(data.get("id") or uuid.uuid4()),
            "dateTime": timestamp.isoformat(timespec="milliseconds"),
            "tagID": str(data.get("tid") or ""),
            "lane": str(data.get("lane") or ""),
            "antenna": data.get("antenna"),
            "side": str(data.get("side") or ""),
            "rssi": data.get("rssi"),
            "tidAuthentic": data.get("tidAuthentic"),
            "pwAuthentic": data.get("pwAuthentic"),
            "lookup": "queued",
        }

        if side not in ("fast", "slow") or (side == "slow" and not data.get("passageID")):
            observation["lookup"] = "skipped"
            observation["reason"] = "authorization requires fast or a slow read linked to a sensor passage"
            _write_diagnostic(self.reader_status, observation)
            return observation

        if not self._claim_txid(observation["id"]):
            observation["lookup"] = "duplicate"
            observation["reason"] = "reader transaction ID was already submitted"
            _write_diagnostic(self.reader_status, observation)
            return observation

        job = {
            "id": observation["id"],
            "tid": observation["tagID"],
            "lane": observation["lane"],
            "date": observation["dateTime"],
            "tidAuthentic": observation["tidAuthentic"],
            "pwAuthentic": observation["pwAuthentic"],
            "msgID": data.get("msgID"),
            "signMsg": data.get("signMsg"),
            "deadline": deadline,
            "side": side,
            "passageID": str(data.get("passageID") or observation["id"]),
            "previousPassageID": data.get("previousPassageID"),
            "laneClearAtFast": data.get("laneClearAtFast", True),
        }
        for field in ("VehicleClass", "PaidAmount"):
            if field in data:
                job[field] = data[field]
        if not observation["tagID"]:
            job["precheck"] = self._local_failure(
                job, "MISSING_TID", "RFID read has no TID"
            )
        elif not self._authentication_valid(job):
            job["precheck"] = self._local_failure(
                job, "AUTHENTICATION_FAILED", "RFID authentication failed"
            )

        job["generation"] = generation
        if age < -1:
            job["deadline"] = time.monotonic()
        jobs = self._start_worker(job["lane"])
        try:
            jobs.put_nowait(job)
        except queue.Full:
            result = self._lookup_failure(job, "tag-status lookup queue is full", 0)
            self.response_queue.put(result)
            self._store_lookup(result)
        _write_diagnostic(self.reader_status, observation)
        return observation

    def trans(self, data):
        """Reject legacy MCP dispatch; reader passage authorization owns the gate."""
        result = {
            "ok": False,
            "code": "MCP_DISPATCH_DISABLED",
            "operation": None,
            "error": "driverSynergy.trans is disabled; reader passages authorize Synergy",
        }
        status = {
            "recordedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "sourceTransactionID": str(data.get("id") or ""),
            "tagID": str(data.get("tid") or ""),
            "operation": None,
            "eligible": False,
            "decisionReason": result["error"],
            "delivered": False,
            "dispatch": result,
        }
        _write_diagnostic(self.transaction_status, status)
        return result

    def set_sign_msg(self, sign_message, date_time=None, *, lane=None, job=None):
        timestamp = self._timestamp(date_time)
        command = {
            "op": "setSignMsg",
            "laneID": str(lane or self.lane_id),
            "signMsg": str(sign_message),
            "dateTime": timestamp.isoformat(timespec="milliseconds"),
        }
        return self._dispatch(command, job=job)

    def close_gate(self, sign_message=None, date_time=None, *, lane=None):
        timestamp = self._timestamp(date_time)
        command = {
            "op": "closeGate",
            "laneID": str(lane or self.lane_id),
            "signMsg": str(sign_message or self.sign_message),
            "dateTime": timestamp.isoformat(timespec="milliseconds"),
        }
        return self._dispatch(command)

    def lane_clear(self, lane):
        """Cancel unsent work; XLC owns normal queue decrement and gate closure."""
        with self.worker_lock:
            self.lane_generations[str(lane)] = self.lane_generations.get(str(lane), 0) + 1
            self.paused_passages = {key for key in self.paused_passages if key[0] != str(lane)}
        status = {
            "recordedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "lane": str(lane),
            "action": "cancel_pending_lookups",
            "reason": "XLC owns normal vehicle passage",
        }
        _write_diagnostic(self.data_dir / "lane-clear-status.json", status)
        return status

    def passage_end(self, lane, passage_id):
        with self.worker_lock:
            self.ended_passages[(str(lane), str(passage_id))] = True
            self.paused_passages.discard((str(lane), str(passage_id)))
            while len(self.ended_passages) > DEFAULT_MAX_SEEN_TXIDS:
                self.ended_passages.popitem(last=False)

    def passage_state(self, lane, passage_id, occupied):
        with self.worker_lock:
            key = (str(lane), str(passage_id))
            if occupied:
                self.paused_passages.discard(key)
            else:
                self.paused_passages.add(key)


def _default_driver():
    return AkiraDriver(
        data_dir=os.environ.get("AKIRA_DATA_DIR", DEFAULT_DATA_DIR),
        lane_id=os.environ.get("AKIRA_LANE_ID", DEFAULT_LANE_ID),
        concession_id=os.environ.get("AKIRA_CONCESSION_ID", DEFAULT_CONCESSION_ID),
        plaza_code=os.environ.get("AKIRA_PLAZA_CODE", DEFAULT_PLAZA_CODE),
        lane_code=os.environ.get("AKIRA_LANE_CODE", DEFAULT_LANE_CODE),
        sign_message=os.environ.get("AKIRA_SIGN_MESSAGE", DEFAULT_SIGN_MESSAGE),
        no_tag_message=os.environ.get("AKIRA_NO_TAG_MESSAGE", DEFAULT_NO_TAG_MESSAGE),
        timezone_offset=os.environ.get(
            "AKIRA_TIMEZONE_OFFSET", DEFAULT_TIMEZONE_OFFSET
        ),
        driver_config=_driver_config(),
    )


_DRIVER = _default_driver()


def read(data):
    return _DRIVER.read(data)


def getResponses():
    return _DRIVER.get_responses()


def trans(data):
    return _DRIVER.trans(data)


def setSignMsg(sign_message, date_time=None, *, lane=None):
    return _DRIVER.set_sign_msg(sign_message, date_time, lane=lane)


def closeGate(sign_message=None, date_time=None, *, lane=None):
    return _DRIVER.close_gate(sign_message, date_time, lane=lane)


def laneClear(lane):
    return _DRIVER.lane_clear(lane)


def passageEnd(lane, passage_id):
    return _DRIVER.passage_end(lane, passage_id)


def passageState(lane, passage_id, occupied):
    return _DRIVER.passage_state(lane, passage_id, occupied)


def noTag(lane, antenna=None):
    return _DRIVER.set_sign_msg(_DRIVER.no_tag_message, lane=lane)
