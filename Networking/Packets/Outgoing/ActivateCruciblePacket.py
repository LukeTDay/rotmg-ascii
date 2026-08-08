from Networking.Packets.Packet import Packet

class ActivateCruciblePacket(Packet):
    def __init__(self):
        self.type = "ACTIVATECRUCIBLE"
        self.crucibleID : str = ""
        self.activate : bool = True
        # Trailing raw unsigned crucible-type byte - was missing entirely from this
        # class (read/write only handled crucibleID+activate), confirmed via the
        # local realmlib reference (realmlib/src/packets/outgoing/
        # activate-crucible-packet.ts, which documents this exact 3-field layout).
        # Since this packet is no longer forced through DECODE_ONLY_PACKETS, a
        # missing field here meant write() dropped this trailing byte on every
        # re-encode, sending the server a truncated packet.
        self.crucibleType : int = 0
        return

    def read(self, reader):
        self.crucibleID = reader.readStr()
        self.activate = reader.readBool()
        self.crucibleType = reader.readUnsignedByte()
        return

    def write(self, writer):
        writer.writeStr(self.crucibleID)
        writer.writeBool(self.activate)
        writer.writeUnsignedByte(self.crucibleType)
        return