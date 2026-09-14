#!/usr/bin/env python3
"""Configuration and queue-routing helpers for the RTS TCP channels."""

import base64
import json
import re
from pathlib import Path

from synergyProtocol import configured_lane_ids, validate_lane_id


RFID_CHANNEL = "rfid"
ANPR_CHANNEL = "anpr"
CHANNELS = (RFID_CHANNEL, ANPR_CHANNEL)
_LANE_TOKEN = re.compile(r"\.rts-lane-([A-Za-z0-9_-]+)(?=\.rts-(?:r|t|resp)$)")
_STATE_LANE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def lane_id_maps(project_root):
    """Return one-to-one local and RTS wire lane-ID mappings."""
    project_root = Path(project_root)
    config = json.loads((project_root / "etc/akira.cfg").read_text())
    local_ids = configured_lane_ids(project_root)
    driver = config.get("driverConfig", {}).get("driverRts", {})
    if not isinstance(driver, dict):
        raise ValueError("driverConfig.driverRts must be an object")
    aliases = driver.get("laneAliases")
    if aliases is None:
        aliases = {lane_id: lane_id for lane_id in local_ids}
    if not isinstance(aliases, dict):
        raise ValueError("driverConfig.driverRts.laneAliases must be an object")
    unknown = set(aliases) - set(local_ids)
    missing = set(local_ids) - set(aliases)
    if unknown:
        raise ValueError(f"RTS aliases configured for unknown lanes: {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"missing RTS aliases for lanes: {', '.join(sorted(missing))}")

    local_to_wire = {}
    wire_to_local = {}
    for local_id in local_ids:
        wire_id = validate_lane_id(str(aliases[local_id]))
        if wire_id in wire_to_local:
            raise ValueError(f"duplicate RTS wire lane ID: {wire_id!r}")
        local_to_wire[local_id] = wire_id
        wire_to_local[wire_id] = local_id
    return local_to_wire, wire_to_local


def wire_lane_id(project_root, local_lane_id):
    local_lane_id = validate_lane_id(str(local_lane_id))
    local_to_wire, _wire_to_local = lane_id_maps(project_root)
    try:
        return local_to_wire[local_lane_id]
    except KeyError as error:
        raise ValueError(f"unknown local lane ID: {local_lane_id!r}") from error


def local_lane_id(project_root, wire_lane_id):
    wire_lane_id = validate_lane_id(str(wire_lane_id))
    _local_to_wire, wire_to_local = lane_id_maps(project_root)
    try:
        return wire_to_local[wire_lane_id]
    except KeyError as error:
        raise ValueError(f"unknown RTS wire lane ID: {wire_lane_id!r}") from error


def lane_endpoints(project_root, lane_ids=None):
    """Return the configured bind address and RFID/ANPR port pair per lane."""
    project_root = Path(project_root)
    config = json.loads((project_root / "etc/akira.cfg").read_text())
    if lane_ids is None:
        lane_ids = configured_lane_ids(project_root)
    else:
        lane_ids = tuple(validate_lane_id(str(lane)) for lane in lane_ids)
    server = config.get("driverConfig", {}).get("serverRts", {})
    if not isinstance(server, dict):
        raise ValueError("driverConfig.serverRts must be an object")
    mapping = server.get("lanePorts")
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("configure driverConfig.serverRts.lanePorts")

    configured = configured_lane_ids(project_root)
    lane_id_maps(project_root)
    unknown = set(mapping) - set(configured)
    missing = set(lane_ids) - set(mapping)
    if unknown:
        raise ValueError(f"RTS ports configured for unknown lanes: {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"missing RTS ports for lanes: {', '.join(sorted(missing))}")

    validated = {}
    all_ports = []
    for lane in configured:
        if lane not in mapping:
            continue
        endpoints = mapping[lane]
        if not isinstance(endpoints, dict) or set(endpoints) != set(CHANNELS):
            raise ValueError(f"lane {lane} must configure exactly rfid and anpr RTS ports")
        validated[lane] = {}
        for channel in CHANNELS:
            port = endpoints[channel]
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError(f"invalid RTS {channel} port for lane {lane}: {port!r}")
            validated[lane][channel] = port
            all_ports.append(port)
    if len(all_ports) != len(set(all_ports)):
        raise ValueError("every RTS lane/channel must have a unique TCP port")

    bind = server.get("bind", "0.0.0.0")
    if not isinstance(bind, str) or not bind.strip():
        raise ValueError("serverRts.bind must be a non-empty address")
    return bind, {lane: validated[lane] for lane in lane_ids}


def encode_lane(lane_id):
    lane_id = validate_lane_id(str(lane_id))
    return base64.urlsafe_b64encode(lane_id.encode("utf-8")).decode("ascii").rstrip("=")


def decode_lane(token):
    padding = "=" * (-len(token) % 4)
    try:
        lane_id = base64.urlsafe_b64decode(token + padding).decode("utf-8")
    except Exception as error:
        raise ValueError("invalid RTS queue lane token") from error
    return validate_lane_id(lane_id)


def queue_filename(identifier, lane_id, extension):
    if extension not in (".rts-r", ".rts-t", ".rts-resp"):
        raise ValueError(f"unsupported RTS queue extension: {extension}")
    return f"{identifier}.rts-lane-{encode_lane(lane_id)}{extension}"


def queue_lane(filename):
    match = _LANE_TOKEN.search(Path(filename).name)
    return decode_lane(match.group(1)) if match else None


def lane_state_filename(lane_id):
    lane_id = validate_lane_id(str(lane_id))
    if not _STATE_LANE.fullmatch(lane_id):
        raise ValueError(f"lane ID is unsafe for a state filename: {lane_id!r}")
    return f"akiraEnabled.{lane_id}.rts"
