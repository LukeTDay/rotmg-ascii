from Networking.Packets.Packet import Packet

class CreatePacket(Packet):
    def __init__(self):
        self.type = "CREATE"
        self.classType = 0
        self.skinType = 0
        # Formerly assumed to be "isChallenger" - realmlib found every captured
        # CREATE sends 0 with no contrasting result to confirm that meaning, so
        # this stays unlabeled until a controlled capture identifies it.
        self.unknownFlag = False
        self.isSeasonal = False
        # Missing entirely from pyrelay/rotmg_mitm_py's older packet - realmlib
        # confirmed it's a real trailing field ("upgraded starter equipment");
        # omitting it undersends by a byte, which desyncs the next packet's
        # framing server-side ("bad message received").
        self.isUpgraded = True

    def write(self, writer):
        writer.writeShort(self.classType)
        writer.writeShort(self.skinType)
        writer.writeBool(self.unknownFlag)
        writer.writeBool(self.isSeasonal)
        writer.writeBool(self.isUpgraded)

    def read(self, reader):
        self.classType = reader.readShort()
        self.skinType = reader.readShort()
        self.unknownFlag = reader.readBool()
        self.isSeasonal = reader.readBool()
        self.isUpgraded = reader.readBool()
