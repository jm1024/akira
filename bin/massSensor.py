"""Numato GPIO parsing and physical-to-logical mass sensor mapping."""

import re


MASS_ROLES = ("fast", "mid", "slow")
LEGACY_ROLE_KEYS = {
    "fast": "trip",
    "mid": "main",
    "slow": "rear",
}
DEFAULT_CLEAR_DEBOUNCE_MS = 1500
DEFAULT_SLOW_CLEAR_DEBOUNCE_MS = 50


def physicalPort(value):
    """Return a zero-based Numato port for physical or legacy IO labels."""
    if isinstance(value, bool):
        raise ValueError(f"invalid GPIO port {value!r}")
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError) as ex:
        raise ValueError(f"invalid GPIO port {value!r}") from ex

    # Legacy Akira configs named the Numato bits 100 through 115.
    if 100 <= port <= 115:
        port -= 100
    if not 0 <= port <= 15:
        raise ValueError(f"GPIO port {value!r} is outside 0-15")
    return port


def normalizeConfig(config):
    """Validate and normalize one mass board configuration."""
    normalized = dict(config)
    configuredPorts = config.get("ports")

    if configuredPorts is None:
        missing = [key for key in LEGACY_ROLE_KEYS.values() if key not in config]
        if missing:
            raise ValueError("mass sensor lacks ports or legacy keys: " + ", ".join(missing))
        configuredPorts = {
            role: [config[legacyKey]]
            for role, legacyKey in LEGACY_ROLE_KEYS.items()
        }
    elif not isinstance(configuredPorts, dict):
        raise ValueError("mass sensor ports must be an object")

    ports = {}
    assigned = {}
    for role in MASS_ROLES:
        values = configuredPorts.get(role)
        if not isinstance(values, list) or not values:
            raise ValueError(f"mass sensor ports.{role} must be a non-empty list")
        ports[role] = [physicalPort(value) for value in values]
        if len(ports[role]) != len(set(ports[role])):
            raise ValueError(f"mass sensor ports.{role} contains a duplicate port")
        for port in ports[role]:
            if port in assigned:
                raise ValueError(
                    f"GPIO port {port} is assigned to both {assigned[port]} and {role}"
                )
            assigned[port] = role

    try:
        activeState = int(config.get("activeState", 1))
    except (TypeError, ValueError) as ex:
        raise ValueError("mass sensor activeState must be 0 or 1") from ex
    if activeState not in (0, 1):
        raise ValueError("mass sensor activeState must be 0 or 1")

    try:
        clearDebounceMs = int(
            config.get("clearDebounceMs", DEFAULT_CLEAR_DEBOUNCE_MS)
        )
    except (TypeError, ValueError) as ex:
        raise ValueError("mass sensor clearDebounceMs must be a non-negative integer") from ex
    if clearDebounceMs < 0:
        raise ValueError("mass sensor clearDebounceMs must be a non-negative integer")

    normalized["ports"] = ports
    normalized["activeState"] = activeState
    normalized["clearDebounceMs"] = clearDebounceMs
    try:
        slowClearDebounceMs = int(config.get("slowClearDebounceMs", DEFAULT_SLOW_CLEAR_DEBOUNCE_MS))
    except (TypeError, ValueError) as ex:
        raise ValueError("mass sensor slowClearDebounceMs must be a non-negative integer") from ex
    if slowClearDebounceMs < 0:
        raise ValueError("mass sensor slowClearDebounceMs must be a non-negative integer")
    normalized["slowClearDebounceMs"] = slowClearDebounceMs
    try:
        fastClearDebounceMs = int(config.get("fastClearDebounceMs", 5))
    except (TypeError, ValueError) as ex:
        raise ValueError("mass sensor fastClearDebounceMs must be a non-negative integer") from ex
    if fastClearDebounceMs < 0:
        raise ValueError("mass sensor fastClearDebounceMs must be a non-negative integer")
    normalized["fastClearDebounceMs"] = fastClearDebounceMs
    return normalized


def parseGpio(text):
    """Parse a Numato 16-bit readall or notification response."""
    if not text:
        return None
    matches = re.findall(
        r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{4})(?![0-9A-Fa-f])",
        str(text),
    )
    if not matches:
        return None

    value = int(matches[0], 16)
    bits = f"{value:016b}"[::-1]
    return {str(port + 100): int(bits[port]) for port in range(16)}


def rawPortStates(rawState):
    """Return available raw values keyed by physical port number strings."""
    ports = {}
    for port in range(16):
        legacyKey = str(port + 100)
        physicalKey = str(port)
        if legacyKey in rawState:
            ports[physicalKey] = int(rawState[legacyKey])
        elif physicalKey in rawState:
            ports[physicalKey] = int(rawState[physicalKey])
    return ports


def logicalState(rawState, config):
    """Aggregate raw GPIO inputs into fast, mid, slow, and occupied states."""
    normalized = normalizeConfig(config)
    rawPorts = rawPortStates(rawState)
    configured = {
        port
        for role in MASS_ROLES
        for port in normalized["ports"][role]
    }
    missing = sorted(port for port in configured if str(port) not in rawPorts)
    if missing:
        raise ValueError("GPIO response lacks configured ports: " + ", ".join(map(str, missing)))

    activeState = normalized["activeState"]
    logical = {
        role: int(any(rawPorts[str(port)] == activeState for port in normalized["ports"][role]))
        for role in MASS_ROLES
    }
    logical["occupied"] = int(any(logical[role] for role in MASS_ROLES))
    logical["ports"] = rawPorts

    # Compatibility for older state readers during the schema transition.
    logical["trip"] = logical["fast"]
    logical["main"] = logical["mid"]
    logical["rear"] = logical["slow"]
    return logical


def occupied(state, config=None):
    """Return whether a logical or legacy/raw mass state is occupied."""
    if "occupied" in state:
        return bool(int(state["occupied"]))
    if all(role in state for role in MASS_ROLES):
        return any(bool(int(state[role])) for role in MASS_ROLES)
    if all(key in state for key in LEGACY_ROLE_KEYS.values()):
        return any(bool(int(state[key])) for key in LEGACY_ROLE_KEYS.values())
    if config is not None:
        return bool(logicalState(state, config)["occupied"])
    return False
