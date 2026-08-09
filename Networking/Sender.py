import socket
import queue

import Constants.PacketIds as PacketIds
import Networking.Writer as Writer
import Crypto.RC4 as RC4
import Crypto.rotmg_keys as rotmg_keys


class Sender:
    """Owns the write side of the game socket. Drains the outbound queue with a
    blocking get() and calls sendall - nothing else should ever call send()."""

    def __init__(self, sock: socket.socket, outgoingQueue: "queue.Queue", debugger) -> None:
        self.sock = sock
        self.outgoingQueue = outgoingQueue
        self.debugger = debugger
        self.writer = Writer.Writer()
        self.encoder = RC4.RC4(rotmg_keys.OUTGOING_KEY)
        self.active = True

    def start(self):
        while self.active:
            packet = self.outgoingQueue.get()
            if packet is None:
                # Sentinel pushed by stop() - unblocks the get() so the thread can exit.
                break
            self._sendPacket(packet)

    def stop(self):
        self.active = False
        self.outgoingQueue.put(None)

    def _sendPacket(self, packet):
        self.writer.reset()
        packet.write(self.writer)
        self.writer.writeHeader(PacketIds.typeToId[packet.type])
        self.writer.buffer[5:] = self.encoder.process(self.writer.buffer[5:])
        try:
            self.sock.sendall(bytes(self.writer.buffer))
        except OSError as e:
            # Socket already torn down by a disconnect/reconnect in flight.
            self.debugger.warning(f"Dropped outgoing {packet.type} packet - socket already closed: {e}")
