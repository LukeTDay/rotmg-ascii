from Networking.Packets.Packet import Packet

class PartyRequestResponsePacket(Packet):
    def __init__(self):
        self.type = "PARTYREQUESTRESPONSE"

        self.player_name = ""
        self.class_id = 0
        self.skin_id = 0
        self.state = 0   # InviteState enum index (byte)

    def read(self, reader):
        # Java: playerName = buffer.readString();
        self.player_name = reader.readStr()

        # Java: classId = buffer.readShort();
        self.class_id = reader.readShort()

        # Java: skinId = buffer.readShort();
        self.skin_id = reader.readShort()

        # Java: state = InviteState.byOrdinal(buffer.readByte());
        # In Python we store the raw byte – plugin/user can map it to enum
        self.state = reader.readByte()

    def write(self, writer):
        writer.writeStr(self.player_name)
        writer.writeShort(self.class_id)
        writer.writeShort(self.skin_id)
        writer.writeByte(self.state)
