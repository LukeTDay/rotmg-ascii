from Networking.Packets.Packet import Packet

class PartyJoinRequestPacket(Packet):
    def __init__(self):
        self.type = "PARTYJOINREQUEST"
        self.party_id = 0
        self.unknown = 0

    def read(self, reader):
        # Java: partyId = buffer.readInt();
        self.party_id = reader.readInt32()

        # Java: unknown = buffer.readByte();
        self.unknown = reader.readByte()

    def write(self, writer):
        writer.writeInt32(self.party_id)
        writer.writeByte(self.unknown)
