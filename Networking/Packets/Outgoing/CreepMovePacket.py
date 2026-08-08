from Networking.Packets.Packet import Packet
from Data.WorldPosData import *

class CreepMovePacket(Packet):
    def __init__(self):
        self.type = "CREEPMOVE"
        self.objectId = 0
        self.serverTime = 0
        self.position = WorldPosData()
        self.hold = False

    def write(self, writer):
        writer.writeInt32(self.objectId)
        writer.writeInt32(self.serverTime)
        self.position.write(writer)
        writer.writeBool(self.hold)

    def read(self, reader):
        self.objectId = reader.readInt32()
        self.serverTime = reader.readInt32()
        self.position.read(reader)
        self.hold = reader.readBool()
