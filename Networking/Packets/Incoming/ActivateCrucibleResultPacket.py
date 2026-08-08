from Networking.Packets.Packet import Packet

class ActivateCrucibleResultPacket(Packet):
    def __init__(self):
        self.type = "ACTIVATECRUCIBLERESULT"
        # Result of a prior outgoing ACTIVATECRUCIBLE (180) - single bool body,
        # confirmed via realmlib (unknown181-packet.ts) and RealmShark
        # (UnknownPacket181.java), both agreeing on a lone readBoolean().
        self.result : bool = False
        return

    def read(self, reader):
        self.result = reader.readBool()
        return

    def write(self, writer):
        writer.writeBool(self.result)
        return
