from Networking.Packets.Packet import Packet
from Data.SlotObjectData import *

class ClaimChestRewardPacket(Packet):
    def __init__(self):
        self.type = "CLAIMCHESTREWARD"
        self.unknownByte = 0
        self.slotObject = SlotObjectData()
        self.unknownShort = 0

    def read(self, reader):
        self.unknownByte = reader.readByte()
        self.slotObject = SlotObjectData()
        self.slotObject.read(reader)
        self.unknownShort = reader.readShort()

    def write(self, writer):
        writer.writeByte(self.unknownByte)
        self.slotObject.write(writer)
        writer.writeShort(self.unknownShort)
