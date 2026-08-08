from Networking.Packets.Packet import Packet

class PartyInviteResponsePacket(Packet):
    def __init__(self):
        self.type = "PARTYINVITERESPONSE"
        self.party_id = 0
        self.accept_invite = 0
    
    def read(self, reader):
        self.party_id = reader.readInt32()
        self.accept_invite = reader.readByte()

    def write(self, writer):
        writer.writeInt32(self.party_id)
        writer.writeByte(self.accept_invite)