"""Validation for transaction fields shared by the Synergy driver and server."""

import json
from pathlib import Path


def validate_lane_id(lane_id, configured_lanes=None):
    if not isinstance(lane_id, str) or not lane_id or lane_id != lane_id.strip():
        raise ValueError("laneID must be a non-empty string without surrounding whitespace")
    if configured_lanes is not None and lane_id not in configured_lanes:
        raise ValueError(f"unknown laneID: {lane_id!r}")
    return lane_id


def configured_lane_ids(project_root, override=None):
    if override is None:
        config = json.loads((Path(project_root) / "etc/akira.cfg").read_text())
        lane_ids = [lane["number"] for lane in config.get("lanes", [])]
    else:
        lane_ids = [lane.strip() for lane in override.split(",")]
    if not lane_ids:
        raise ValueError("at least one configured lane is required")
    for lane_id in lane_ids:
        validate_lane_id(lane_id)
    if len(set(lane_ids)) != len(lane_ids):
        raise ValueError("configured lane IDs must be unique")
    return tuple(lane_ids)


def lane_endpoints(project_root, lane_ids, mapping_override=None, port_override=None):
    """Read per-lane ports; a single-port override requires one explicit lane."""
    config = json.loads((Path(project_root) / "etc/akira.cfg").read_text())
    server = config.get("driverConfig", {}).get("serverSynergy", {})
    if not isinstance(server, dict):
        raise ValueError("driverConfig.serverSynergy must be an object")
    if mapping_override is not None and port_override is not None:
        raise ValueError("use either --lane-ports or --port")
    if port_override is not None:
        if len(lane_ids) != 1:
            raise ValueError("--port requires exactly one lane; use --lanes 06 or --lane-ports")
        mapping = {lane_ids[0]: port_override}
    elif mapping_override is not None:
        mapping = {}
        for entry in mapping_override.split(","):
            lane, port = entry.strip().split("=", 1)
            validate_lane_id(lane, lane_ids)
            if lane in mapping:
                raise ValueError(f"duplicate lane port mapping: {lane}")
            mapping[lane] = int(port)
    else:
        mapping = server.get("lanePorts")
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("configure driverConfig.serverSynergy.lanePorts")
    known_lanes = (lane_ids if mapping_override is not None or port_override is not None
                   else [lane["number"] for lane in config.get("lanes", [])])
    for lane, port in mapping.items():
        validate_lane_id(lane, known_lanes)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError(f"invalid TCP port for lane {lane}: {port!r}")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("each lane must have a unique TCP port")
    missing = set(lane_ids) - mapping.keys()
    if missing:
        raise ValueError(f"missing TCP ports for lanes: {', '.join(sorted(missing))}")
    bind = server.get("bind", "0.0.0.0")
    if not isinstance(bind, str) or not bind.strip():
        raise ValueError("serverSynergy.bind must be a non-empty address")
    return bind, {lane: mapping[lane] for lane in lane_ids}


TRANSACTION_INTEGER_FIELDS = {
    "TagStatus": (0, 99),
    "AccountType": (0, 99),
    "EntryLane": (0, 999),
    "TcClass": (1, 8),
    "VehicleClass": (1, 8),
    "Fare": (0, None),
    "PaidAmount": (0, None),
}


def validate_transaction_fields(message):
    for field, (minimum, maximum) in TRANSACTION_INTEGER_FIELDS.items():
        value = message.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field} must be an integer")
        if value < minimum or (maximum is not None and value > maximum):
            raise ValueError(f"{field} is outside its permitted range")
    plate = message.get("VehiclePlateNo")
    if not isinstance(plate, str) or len(plate) > 24:
        raise ValueError("VehiclePlateNo must be a string of at most 24 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in plate):
        raise ValueError("VehiclePlateNo must not contain control characters")
