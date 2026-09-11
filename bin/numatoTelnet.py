"""Blocking Telnet transport for Numato Ethernet GPIO and relay boards."""

import os
import sys
import time


LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from telnetlib3.sync import TelnetConnection


class NumatoConnection:
    """Small text-oriented wrapper around telnetlib3's blocking client."""

    def __init__(self, host, port=23, timeout=5, connection_factory=TelnetConnection):
        self.timeout = timeout
        self.connection = connection_factory(
            host,
            port,
            timeout=timeout,
            connect_timeout=timeout,
            encoding="ascii",
        )
        self.connection.connect()

    @staticmethod
    def _text(data):
        if isinstance(data, bytes):
            return data.decode("ascii", errors="ignore")
        return data or ""

    def read_until(self, marker, timeout=None):
        data = self.connection.read_until(marker, timeout=timeout)
        return self._text(data)

    def readline(self, timeout=None):
        try:
            data = self.connection.readline(timeout=timeout)
        except TimeoutError:
            return ""
        return self._text(data)

    def read_available(self, timeout=0.2, settle_timeout=0.1):
        chunks = []
        try:
            data = self.connection.read_some(timeout=timeout)
        except TimeoutError:
            return ""
        chunks.append(self._text(data))

        # Numato responses can arrive as several TCP/Telnet fragments. Once
        # the first fragment arrives, drain the rest until the stream is quiet.
        drain_deadline = time.monotonic() + max(timeout, settle_timeout)
        while time.monotonic() < drain_deadline:
            try:
                data = self.connection.read_some(
                    timeout=min(settle_timeout, drain_deadline - time.monotonic())
                )
            except TimeoutError:
                break
            chunks.append(self._text(data))
        return "".join(chunks)

    def write_line(self, line):
        self.connection.write(str(line) + "\r\n")
        self.connection.flush(timeout=self.timeout)

    def close(self):
        self.connection.close()
