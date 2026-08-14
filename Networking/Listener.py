import socket
import struct
import queue
import time

import Constants.PacketIds as PacketIds
import Networking.Reader as Reader
import Networking.PacketHelper as PacketHelper
import Crypto.RC4 as RC4
import Crypto.rotmg_keys as rotmg_keys
from Data.MoveRecord import MoveRecord
from Data.WorldPosData import WorldPosData
from Networking.PacketLogSettings import PacketLogSettings
from Networking.Ticker import Ticker

HEADERSIZE = 5


class Listener:
    """Owns the read side of the game socket. Decodes each packet inline and, for
    types needing a fast reply, sends it immediately from this thread (via the
    outbound queue) rather than waiting on the render loop, per the server's ack timeouts."""

    def __init__(
        self,
        sock: socket.socket,
        incomingQueue: "queue.Queue",
        outgoingQueue: "queue.Queue",
        ticker: Ticker,
        connectedTime: int,
        debugger,
        packetLogSettings: PacketLogSettings,
    ) -> None:
        self.sock = sock
        self.incomingQueue = incomingQueue
        self.outgoingQueue = outgoingQueue
        self.ticker = ticker
        self.connectedTime = connectedTime
        self.debugger = debugger
        self.packetLogSettings = packetLogSettings
        self.reader = Reader.Reader()
        self.decoder = RC4.RC4(rotmg_keys.INCOMING_KEY)
        self.objectId = -1
        self.active = True

    def start(self):
        while self.active:
            try:
                header = self._recvExact(HEADERSIZE)
                if header is None:
                    break
                size = struct.unpack("!i", header[:4])[0]
                packetId = header[4]
                body = self._recvExact(size - HEADERSIZE)
                if body is None:
                    break
            except (ConnectionResetError, ConnectionAbortedError, OSError):
                break

            body = self.decoder.process(body)

            try:
                packetType = PacketIds.idToType[packetId]
            except KeyError:
                continue
            if "UNKNOWN" in packetType:
                continue
            try:
                packet = PacketHelper.createPacket(packetType)
            except ValueError:
                self.debugger.warning(f"Received unknown/unhandled packet type: {packetType}")
                continue

            self.reader.reset(header + body)
            packet.read(self.reader)
            if self.packetLogSettings.shouldLog(packet.type):
                self.debugger.debug(self.packetLogSettings.formatLine("S>C", packet))
            self._handlePacket(packet)

    def stop(self):
        self.active = False

    def _recvExact(self, length):
        data = bytearray()
        while len(data) < length:
            chunk = self.sock.recv(length - len(data))
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data)

    def _getTime(self) -> int:
        return int(time.time() * 1000) - self.connectedTime

    def _handlePacket(self, packet):
        packetType = packet.type

        if packetType == "RECONNECT":
            self.debugger.info(
                f"RECONNECT received - moving to {packet.name!r} "
                f"(host={packet.host!r} port={packet.port} gameId={packet.gameId})"
            )
            # Falls through to the universal incomingQueue.put() below - socket teardown/reopen
            # happens in the renderer, since this thread can't join/replace itself mid-recv().
        elif packetType == "PING":
            pong = PacketHelper.createPacket("PONG")
            pong.serial = packet.serial
            pong.time = self._getTime()
            self.outgoingQueue.put(pong)
        elif packetType == "UPDATE":
            ack = PacketHelper.createPacket("UPDATEACK")
            self.outgoingQueue.put(ack)
            for obj in packet.newObjs:
                if obj.status.objectId == self.objectId:
                    self.ticker.setPos(obj.status.pos)
        elif packetType == "GOTO":
            ack = PacketHelper.createPacket("GOTOACK")
            ack.time = self._getTime()
            self.outgoingQueue.put(ack)
            if packet.objectId == self.objectId:
                self.ticker.setPos(packet.pos)
        elif packetType == "SERVERPLAYERSHOOT":
            if packet.ownerId == self.objectId:
                ack = PacketHelper.createPacket("SHOOTACK")
                ack.time = self._getTime()
                self.outgoingQueue.put(ack)
        elif packetType == "ENEMYSHOOT":
            ack = PacketHelper.createPacket("ENEMYSHOOTACK")
            ack.time = self._getTime()
            ack.count = min(1, packet.numShots)
            self.outgoingQueue.put(ack)
        elif packetType == "AOE":
            ack = PacketHelper.createPacket("AOEACK")
            ack.time = self._getTime()
            ack.pos = self.ticker.pos.clone() if self.ticker.pos is not None else WorldPosData()
            self.outgoingQueue.put(ack)
        elif packetType == "NEWTICK":
            move = PacketHelper.createPacket("MOVE")
            move.tickId = packet.tickId
            move.time = packet.serverRealTimeMS
            records = self.ticker.drainRecords()
            if len(records) == 0 and self.ticker.pos is not None:
                # An empty records list gets the client disconnected for lagging.
                records = [MoveRecord(self.ticker.lastFrameTime, self.ticker.pos.x, self.ticker.pos.y)]
            move.records = records
            self.outgoingQueue.put(move)
        elif packetType == "CREATESUCCESS":
            self.objectId = packet.objectId
            self.debugger.info(f"CREATESUCCESS received - objectId={packet.objectId}")
        elif packetType == "FAILURE":
            self.debugger.error(f"FAILURE received: {packet.errorDescription}")

        self.incomingQueue.put(packet)
