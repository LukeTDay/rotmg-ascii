from Networking.Packets.Packet import Packet

class IncomingPartyInvitePacket(Packet):
    def __init__(self):
        self.type = "IncomingPartyInvite"
        self.party_id = 0
        self.invite_name = ""

    def read(self, reader):
        self.party_id = reader.readInt32()
        self.invite_name = reader.readStr()

    def write(self, writer):
        writer.writeInt32(self.party_id)
        writer.writeStr(self.invite_name)